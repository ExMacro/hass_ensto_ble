"""Support for Ensto BLE devices."""
import logging
import asyncio
import time
from typing import Optional
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from .storage_manager import EnstoStorageManager
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from homeassistant.util import dt as dt_util
from .data_coordinator import EnstoRealTimeCoordinator

from .const import (
    MANUFACTURER_ID,
    ERROR_CODES_BYTE0,
    ERROR_CODES_BYTE1,
    ACTIVE_MODES,
    EXTERNAL_CONTROL_MODES,
    MODE_MAP,
    CURRENCY_MAP,
    CURRENCY_SYMBOLS,
    DEVICE_NAME_UUID,
    MODEL_NUMBER_UUID,
    SOFTWARE_REVISION_UUID,
    HARDWARE_REVISION_UUID,
    DATE_AND_TIME_UUID,
    DAYLIGHT_SAVING_UUID,
    HEATING_MODE_UUID,
    BOOST_UUID,
    FLOOR_LIMITS_UUID,
    FLOOR_SENSOR_TYPE_UUID,
    ADAPTIVE_TEMPERATURE_CONTROL_UUID,
    HEATING_POWER_UUID,
    FLOOR_AREA_UUID,
    CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID,
    ENERGY_UNIT_UUID,
    CALENDAR_CONTROL_UUID,
    CALENDAR_DAY_UUID,
    VACATION_TIME_UUID,
    CALENDAR_MODE_UUID,
    FACTORY_RESET_ID_UUID,
    MONITORING_DATA_UUID,
    REAL_TIME_INDICATION_POWER_CONSUMPTION_UUID,
    FORCE_CONTROL_UUID,
)

_LOGGER = logging.getLogger(__name__)

# Upper bound for packets in one split read; the largest payload (monitoring data) needs far fewer
MAX_SPLIT_PACKETS = 100

# Valid real-time temperature ranges (°C) from the protocol specification
ROOM_TEMP_RANGE = (-5.0, 35.0)
FLOOR_TEMP_RANGE = (-5.0, 50.0)

class EnstoThermostatManager:
    """Manager for Ensto BLE thermostats."""

    def __init__(self, hass: HomeAssistant, mac_address: str) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.mac_address = mac_address
        self.client: Optional[BleakClient] = None
        self._connect_lock = asyncio.Lock()
        self.scanner = None
        self.storage_manager = EnstoStorageManager(hass)
        self.model_number = None
        self.device_name = None
        self.real_time_coordinator = None
        self.connected_at: Optional[float] = None

    def get_real_time_coordinator(self):
        if not self.real_time_coordinator:
            self.real_time_coordinator = EnstoRealTimeCoordinator(self)
        return self.real_time_coordinator

    def supports_external_control(self) -> bool:
        """Check if firmware supports external control (1.14+)."""
        if not hasattr(self, 'sw_version') or not self.sw_version:
            return False
        try:
            # Parse version like "1.14.0;..." -> 1.14
            version_str = self.sw_version.split(';')[0]
            parts = version_str.split('.')
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            return (major, minor) >= (1, 14)
        except (ValueError, IndexError):
            _LOGGER.debug("Could not parse firmware version: %s", self.sw_version)
            return False

    def setup(self) -> None:
        """Set up the scanner when needed."""
        self.scanner = bluetooth.async_get_scanner(self.hass)

    async def initialize(self) -> None:
        """Initialize the connection."""
        await self.connect()

    async def cleanup(self) -> None:
        """Clean up the connection."""
        try:
            if self.client and self.client.is_connected:
                await self.client.disconnect()
        except Exception as e:
            _LOGGER.debug("Error during cleanup disconnect: %s", e)
        finally:
            self.client = None

    async def connect(self) -> None:
        """Establish connection to the device."""
        if await self._connect_lock.acquire():
            try:
                if self.client and self.client.is_connected:
                    return

                _LOGGER.debug("Finding device %s", self.mac_address)
                device = bluetooth.async_ble_device_from_address(self.hass, self.mac_address)
                if not device:
                    raise Exception(f"Device {self.mac_address} not found")

                # Use bleak-retry-connector
                _LOGGER.debug("Device [%s]: establishing connection", self.mac_address)
                self.client = await establish_connection(BleakClientWithServiceCache, device, self.mac_address)
                _LOGGER.debug("Device [%s]: connection established", self.mac_address)

                # always pair to set encryption
                _LOGGER.debug("Pairing with device %s", self.mac_address)
                await self.client.pair()
                _LOGGER.debug("Paired device %s", self.mac_address)

                # Check storage first
                stored_id = await self.read_device_info()
                
                if stored_id is None:
                    # No stored ID, need to get factory_reset_id from device
                    _LOGGER.info("No stored Factory Reset ID found, attempting pairing...")
                        
                    # Get Factory Reset ID from device
                    try:
                        device_id = await self.read_factory_reset_id()
                        if device_id:
                            _LOGGER.info("Got Factory Reset ID from device")
                            await self.write_device_info(self.mac_address, device_id)
                            stored_id = device_id
                        else:
                            raise Exception("Could not get Factory Reset ID from device")
                    except Exception as e:
                        _LOGGER.error("Error reading Factory Reset ID from device: %s", e)
                        raise
                
                # Write Factory Reset ID to device
                await self.write_factory_reset_id(stored_id)
                
                # Read and store model number and device name after successful connection
                self.model_number = await self.read_model_number()
                self.device_name = await self.read_device_name()
                
                _LOGGER.info("Successfully verified Factory Reset ID and read model number")
                self.connected_at = time.monotonic()

            except Exception as e:
                _LOGGER.error("Failed to connect: %s", str(e))
                self.client = None
                raise
            finally:
                self._connect_lock.release()
        else:
            raise Exception("Already connecting")

    async def ensure_connection(self) -> None:
        """Ensure that we have a connection to the device."""
        if not self.client or not self.client.is_connected:
            await self.connect()

    async def _ble_read(self, uuid: str, label: str = "") -> Optional[bytes]:
        """Read a single GATT characteristic.

        Not suitable for split-packet characteristics; use _ble_read_split() for those.

        Args:
            uuid:  UUID of the GATT characteristic to read.
            label: Human-readable name for log messages, e.g. "boost config".
                   Falls back to the UUID string when omitted.

        Returns:
            Raw bytes from the characteristic, or None on any failure.
        """
        name = label or uuid

        if not self.client or not self.client.is_connected:
            _LOGGER.error("Device not connected, cannot read %s.", name)
            return None

        try:
            return await self.client.read_gatt_char(uuid)
        except BleakError as e:
            _LOGGER.error("BLE error reading %s: %s", name, e)
            self.client = None
            return None
        except Exception as e:
            _LOGGER.error("Failed to read %s: %s", name, e)
            return None

    async def _ble_write(self, uuid: str, data: bytes | bytearray, label: str = "") -> bool:
        """Write a single GATT characteristic with response=True.

        Not suitable for split-packet characteristics; use _ble_write_split() for those.

        Args:
            uuid:  UUID of the GATT characteristic to write.
            data:  Payload bytes to send.
            label: Human-readable name for log messages, e.g. "boost config".
                   Falls back to the UUID string when omitted.

        Returns:
            True on success, False on any failure.
        """
        name = label or uuid

        if not self.client or not self.client.is_connected:
            _LOGGER.error("Device not connected, cannot write %s.", name)
            return False

        try:
            await self.client.write_gatt_char(uuid, data, response=True)
            return True
        except BleakError as e:
            _LOGGER.error("BLE error writing %s: %s", name, e)
            self.client = None
            return False
        except Exception as e:
            _LOGGER.error("Failed to write %s: %s", name, e)
            return False

    async def write_device_info(self, device_address: str, factory_reset_id: int) -> None:
        """Write device info to Home Assistant storage."""
        await self.storage_manager.async_save_device_data(device_address, factory_reset_id)

    async def read_device_info(self) -> Optional[int]:
        """Read device info from Home Assistant storage."""
        device_data = await self.storage_manager.async_load_device_data(self.mac_address)
        if device_data:
            return device_data.get("factory_reset_id")
        return None

    def find_ensto_devices(self):
        """Scan and find Ensto devices with manufacturer 0x2806 (big endian)."""
        discovered_devices = {}
        
        for discovery_info in bluetooth.async_discovered_service_info(self.hass):
            advertisement_data = discovery_info.advertisement
            if (advertisement_data and
                advertisement_data.manufacturer_data and
                MANUFACTURER_ID in advertisement_data.manufacturer_data):
                discovered_devices[discovery_info.address] = (discovery_info, advertisement_data)
        
        return discovered_devices

    def find_devices_in_pairing_mode(self):
        """Find BLE devices that are in pairing mode (PAIRINGFLAG=1)."""
        ensto_devices = self.find_ensto_devices()
        
        pairing_devices = {}
        for addr, (discovery_info, adv) in ensto_devices.items():
            try:
                service_info = bluetooth.async_last_service_info(self.hass, addr)
                fields = service_info.manufacturer_data[MANUFACTURER_ID].decode('ascii').split(';')
                if len(fields) >= 2 and fields[1] == "1":
                    _LOGGER.info("Device %s address %s is in pairing mode", discovery_info.name, discovery_info.address)
                    pairing_devices[addr] = (discovery_info, adv)
                else:
                    _LOGGER.debug("Device %s address %s is NOT in pairing mode", discovery_info.name, discovery_info.address)

            except Exception as e:
                _LOGGER.error("Error parsing manufacturer data: %s", e)
                
        return pairing_devices

    async def read_factory_reset_id(self) -> Optional[int]:
        """Read Factory Reset ID from the BLE device."""
        try:
            data = await self.client.read_gatt_char(FACTORY_RESET_ID_UUID)
            factory_reset_id = int.from_bytes(data[:4], byteorder="little")
            return factory_reset_id
        except Exception as e:
            raise Exception(f"Failed to read factory reset ID: {e}") from e

    async def write_factory_reset_id(self, factory_reset_id: int) -> None:
        """Write the Factory Reset ID to the BLE device."""
        try:
            id_bytes = factory_reset_id.to_bytes(4, byteorder="little")
            await self.client.write_gatt_char(FACTORY_RESET_ID_UUID, id_bytes)
        except Exception as e:
            raise Exception(f"Failed to write factory reset ID: {e}") from e

    async def _ble_read_split(self, uuid: str, label: str = "") -> Optional[bytes]:
        """Read a split-packet characteristic and return the combined payload.

        Each packet starts with a header byte; bit 0x40 marks the last packet.
        Packets are read with _ble_read(), so connection checks and BLE error
        handling are the same as for single reads.

        Args:
            uuid:  UUID of the GATT characteristic to read.
            label: Human-readable name for log messages, e.g. "monitoring data".
                   Falls back to the UUID string when omitted.

        Returns:
            Combined payload without trailing zero padding, or None on any failure.
        """
        combined = bytearray()

        for _ in range(MAX_SPLIT_PACKETS):
            packet = await self._ble_read(uuid, label)
            if packet is None:
                return None
            if not packet:
                break

            combined.extend(packet[1:])

            # Last packet has the 0x40 bit set in the header
            if packet[0] & 0x40:
                break
        else:
            _LOGGER.error("Too many packets reading %s", label or uuid)
            return None

        # Remove padding bytes (zeros from the end)
        return bytes(combined).rstrip(b'\x00')

    async def _ble_write_split(self, uuid: str, data: bytes, label: str = "") -> bool:
        """Write a split-packet characteristic as two packets.

        The payload is always split into two halves. The first packet has
        header 0x80 and the last packet header 0x40. Packets are written with
        _ble_write(), so connection checks and BLE error handling are the same
        as for single writes.

        Args:
            uuid:  UUID of the GATT characteristic to write.
            data:  Payload bytes to send.
            label: Human-readable name for log messages, e.g. "calendar day".
                   Falls back to the UUID string when omitted.

        Returns:
            True on success, False on any failure.
        """
        name = label or uuid
        chunk_size = (len(data) + 1) // 2
        chunks = [(0x80, data[:chunk_size]), (0x40, data[chunk_size:])]

        for index, (header, chunk) in enumerate(chunks, start=1):
            packet = bytearray([header]) + chunk
            _LOGGER.debug("Writing %s packet %d/%d: %s", name, index, len(chunks), packet.hex())

            if not await self._ble_write(uuid, packet, label):
                return False

            # Small delay between packets
            await asyncio.sleep(0.1)

        return True

    def parse_real_time_indication(self, data: bytes) -> dict:
        """
        Parse real time indication data packet.
        
        Data format:
        BYTE[0-1]: Target temperature (uint16_t, 50-500 scaled to 5.0-50.0)
        BYTE[2]: Temperature setting % (uint8_t, 0-100)
        BYTE[3-4]: Room temperature (int16_t, -50 to 350 scaled to -5.0 to 35.0)
        BYTE[5-6]: Floor temperature (int16_t, -50 to 500 scaled to -5.0 to 50.0)
        BYTE[7]: Active relay state (0=off, 1=on)
        BYTE[8-11]: Alarm code
        BYTE[12]: Active mode (1=manual, 2=calendar, 3=vacation)
        BYTE[13]: Active heating mode
        BYTE[14]: Boost mode (0=disabled, 1=enabled)
        BYTE[15-16]: Boost setpoint minutes
        BYTE[17-18]: Boost remaining minutes
        BYTE[19]: Potentiometer absolute % value (0-100)
        """
        if not data or len(data) < 20:
            _LOGGER.error("Invalid data length: %s", len(data) if data else 0)
            return {}

        try:
            # Target temperature (uint16, scaled)
            target_temp = int.from_bytes(data[0:2], byteorder='little') / 10
            
            # Temperature setting percentage
            temp_setting_percent = data[2]
            
            # Room temperature (int16, scaled)
            room_temp = int.from_bytes(data[3:5], byteorder='little', signed=True) / 10
            
            # Floor temperature (int16, scaled)
            floor_temp = int.from_bytes(data[5:7], byteorder='little', signed=True) / 10

            # The device can report invalid values (e.g. -277 °C) right after connecting
            if not ROOM_TEMP_RANGE[0] <= room_temp <= ROOM_TEMP_RANGE[1]:
                _LOGGER.debug("Ignoring out-of-range room temperature: %.1f", room_temp)
                room_temp = None
            if not FLOOR_TEMP_RANGE[0] <= floor_temp <= FLOOR_TEMP_RANGE[1]:
                _LOGGER.debug("Ignoring out-of-range floor temperature: %.1f", floor_temp)
                floor_temp = None
            
            # Active relay state
            relay_active = bool(data[7])
            
            # Parse alarm codes (first 2 bytes only, as others are reserved)
            alarm_bytes = data[8:10]
            active_alarms = []
            
            # Parse each byte and its corresponding error codes
            error_code_maps = [ERROR_CODES_BYTE0, ERROR_CODES_BYTE1]
            for byte_idx, error_map in enumerate(error_code_maps):
                byte_value = alarm_bytes[byte_idx]
                for bit_mask, error_msg in error_map.items():
                    if byte_value & bit_mask:
                        active_alarms.append(error_msg)
            
            # Store both raw code and parsed alarms
            alarm_code = int.from_bytes(alarm_bytes, byteorder='little')

            # Active modes
            active_mode = ACTIVE_MODES.get(data[12], "Unknown")

            # Active heating mode
            heating_mode = MODE_MAP.get(data[13], "Unknown")

            # Boost settings
            boost_enabled = bool(data[14])
            boost_setpoint = int.from_bytes(data[15:17], byteorder='little')
            boost_remaining = int.from_bytes(data[17:19], byteorder='little')
            
            # Potentiometer value
            potentiometer_value = data[19]
            
            return {
                "target_temperature": target_temp,
                "temperature_setting_percent": temp_setting_percent,
                "room_temperature": room_temp,
                "floor_temperature": floor_temp,
                "relay_active": relay_active,
                "alarm_code": alarm_code,
                "active_alarms": active_alarms,
                "active_mode": active_mode,
                "heating_mode": heating_mode,
                "boost_enabled": boost_enabled,
                "boost_setpoint_minutes": boost_setpoint,
                "boost_remaining_minutes": boost_remaining,
                "potentiometer_value": potentiometer_value
            }
        except Exception as e:
            _LOGGER.error("Error parsing real time indication: %s", e)
            return {}

    async def read_model_number(self) -> Optional[str]:
        """Read model number via GATT characteristic."""
        # Read the raw bytes
        model_number_raw = await self._ble_read(MODEL_NUMBER_UUID, "model number")
        if model_number_raw is None:
            return None

        # Decode using UTF-8
        try:
            return model_number_raw.decode('utf-8')
        except UnicodeDecodeError as e:
            _LOGGER.error("Failed to read model number: %s", e)
            return None

    async def set_heating_mode(self, mode: int) -> None:
        """Set heating mode."""
        try:
            await self.write_heating_mode(mode)
        except Exception as e:
            _LOGGER.error("Failed to set heating mode: %s", e)

    async def set_adaptive_temp_control(self, enabled: bool) -> None:
        """Set adaptive temperature control."""
        try:
            await self.write_adaptive_temp_control(enabled)
        except Exception as e:
            _LOGGER.error("Failed to set adaptive temperature control: %s", e)

    async def read_boost(self) -> dict:
        """Read boost configuration from device."""
        # Read raw data from device
        data = await self._ble_read(BOOST_UUID, "boost config")
        if not data:
            return None

        if len(data) < 8:
            _LOGGER.error("Invalid boost data length: %d", len(data))
            return None

        # Parse data
        enabled = bool(data[0])  # First byte is enable flag

        # Parse temperature offset (bytes 1-2 as signed int16)
        # Convert from raw value (2150 = 21.5 degrees)
        offset_raw = int.from_bytes(data[1:3], byteorder='little', signed=True)
        offset_degrees = offset_raw / 100.0

        # Parse percentage offset (byte 3)
        # Convert percentage offset byte to signed int (range -128 to 127)
        offset_percentage = int.from_bytes([data[3]], byteorder='little', signed=True)

        # Parse time setpoint (bytes 4-5 as unsigned int16)
        setpoint_minutes = int.from_bytes(data[4:6], byteorder='little')

        # Parse remaining time (bytes 6-7 as unsigned int16)
        remaining_minutes = int.from_bytes(data[6:8], byteorder='little')

        return {
            'enabled': enabled,
            'offset_degrees': offset_degrees,
            'offset_percentage': offset_percentage,
            'setpoint_minutes': setpoint_minutes,
            'remaining_minutes': remaining_minutes
        }

    async def write_boost(self, enabled: bool, offset_degrees: float, offset_percentage: int, duration_minutes: int) -> bool:
        """Write boost configuration to device."""
        # Validate input values
        if not (-20 <= offset_degrees <= 20):
            _LOGGER.error("Temperature offset must be between -20 and 20 degrees: %s", offset_degrees)
            return False
        if not (-100 <= offset_percentage <= 100):
            _LOGGER.error("Percentage offset must be between -100 and 100: %s", offset_percentage)
            return False
        if not (0 <= duration_minutes <= 65535):  # max value for uint16
            _LOGGER.error("Duration must be between 0 and 65535 minutes: %s", duration_minutes)
            return False

        # Convert temperature to raw value (multiply by 100)
        # e.g., 21.5 degrees becomes 2150
        offset_raw = int(round(offset_degrees * 100))

        # Create data packet (8 bytes)
        data = bytearray(8)
        data[0] = 1 if enabled else 0  # Enable/disable flag

        # Temperature offset as signed int16
        data[1:3] = offset_raw.to_bytes(2, byteorder='little', signed=True)

        # Percentage offset
        # Convert percentage offset to signed int8
        data[3] = offset_percentage.to_bytes(1, byteorder='little', signed=True)[0]

        # Duration setpoint as unsigned int16
        data[4:6] = duration_minutes.to_bytes(2, byteorder='little')

        # Remaining time bytes are left as 0
        data[6:8] = (0).to_bytes(2, byteorder='little')

        # Write to device
        return await self._ble_write(BOOST_UUID, data, "boost config")

    async def read_heating_mode(self) -> dict:
        """Read heating mode configuration from device."""
        data = await self._ble_read(HEATING_MODE_UUID, "heating mode")
        if not data:
            return None

        # Get mode number from first byte
        mode_number = data[0]
        mode_name = MODE_MAP.get(mode_number, "Unknown")

        return {
            'mode_number': mode_number,
            'mode_name': mode_name
        }

    async def write_heating_mode(self, mode: int) -> bool:
        """Write heating mode configuration to device."""
        # Validate input mode
        if mode not in MODE_MAP:
            _LOGGER.error(
                "Invalid heating mode %s. Must be: "
                "1 (Floor), 2 (Room), 3 (Combination), "
                "4 (Power), or 5 (Force Control)",
                mode
            )
            return False

        # Pack data - just a single byte
        return await self._ble_write(HEATING_MODE_UUID, bytes([mode]), "heating mode")

    async def read_adaptive_temp_control(self) -> dict:
        """Read adaptive temperature control setting from device."""
        data = await self._ble_read(ADAPTIVE_TEMPERATURE_CONTROL_UUID, "adaptive temperature control")
        if not data:
            return None

        # Parse first byte as boolean
        enabled = bool(data[0])

        return {
            'enabled': enabled
        }

    async def write_adaptive_temp_control(self, enabled: bool) -> bool:
        """Write adaptive temperature control setting to device."""
        # Create single byte data
        data = bytes([1 if enabled else 0])

        return await self._ble_write(ADAPTIVE_TEMPERATURE_CONTROL_UUID, data, "adaptive temperature control")

    async def read_device_name(self) -> Optional[str]:
        """
        Read device name via GATT characteristic.
        
        Returns:
            str - Device name if successful, None if failed or device is unnamed
        """
        # Read the raw bytes
        raw_data = await self._ble_read(DEVICE_NAME_UUID, "device name")
        if raw_data is None:
            return None

        # Skip first byte and strip null bytes
        name_bytes = raw_data[1:].split(b'\x00')[0]

        # If no actual name data, return None
        if not name_bytes:
            return None

        # Decode using UTF-8 to handle Nordic characters
        try:
            return name_bytes.decode('utf-8')
        except UnicodeDecodeError as e:
            _LOGGER.error("Failed to read device name: %s", e)
            return None

    async def read_date_and_time(self) -> dict:
        """Read date and time from device in UTC.

        Returns:
            dict: UTC time components with keys:
                year (int): Full year (e.g. 2024)
                month (int): Month (1-12)
                day (int): Day of month (1-31) 
                hour (int): Hour (0-23)
                minute (int): Minute (0-59)
                second (int): Second (0-59)
            None: If read fails
        """
        # Read raw data from device
        data = await self._ble_read(DATE_AND_TIME_UUID, "date and time from device")
        if data is None:
            return None

        # Ensure input is the correct length
        if len(data) != 7:
            _LOGGER.error("Device timestamp must be 7 bytes long.")
            return None

        # Extract individual bytes
        year = int.from_bytes(data[0:2], byteorder="little")
        month = data[2]
        date = data[3]
        hour = data[4]
        minute = data[5]
        second = data[6]

        return {
            "year": year,
            "month": month,
            "day": date,
            "hour": hour,
            "minute": minute,
            "second": second
        }

    async def write_date_and_time(self, year: int, month: int, day: int, hour: int, minute: int, second: int) -> bool:
        """Write date and time to device.
        
        All time values must be in UTC as the device internally operates in UTC time 
        and handles DST/timezone conversions based on its settings.
        
        Args:
            year: UTC year (0-9999)
            month: UTC month (1-12)
            day: UTC day (1-31)
            hour: UTC hour (0-23)
            minute: UTC minute (0-59)
            second: UTC second (0-59)
            
        Returns:
            bool: True if successful, False if failed
            
        Note:
            Device specification 2.2.1: MCU operates in UTC, data collection is 
            maintained with UTC timestamps. All timestamps must be in UTC regardless 
            of the device's timezone settings.
        """
        # Validate input values
        if not (0 <= year <= 9999):
            _LOGGER.error("Invalid UTC year: %s", year)
            return False
        if not (1 <= month <= 12):
            _LOGGER.error("Invalid UTC month: %s", month)
            return False
        if not (1 <= day <= 31):
            _LOGGER.error("Invalid UTC day: %s", day)
            return False
        if not (0 <= hour <= 23):
            _LOGGER.error("Invalid UTC hour: %s", hour)
            return False
        if not (0 <= minute <= 59):
            _LOGGER.error("Invalid UTC minute: %s", minute)
            return False
        if not (0 <= second <= 59):
            _LOGGER.error("Invalid UTC second: %s", second)
            return False

        _LOGGER.debug(
            "Writing UTC time to %s for %s: %04d-%02d-%02d %02d:%02d:%02d",
            self.device_name or "Unknown Device",
            self.mac_address,
            year, month, day, hour, minute, second
        )

        # Construct byte array according to device spec 2.2.2:
        # BYTE[0-1]: year as uint16_t
        # BYTE[2]: month 1-12
        # BYTE[3]: date 1-31
        # BYTE[4]: hour 0-23
        # BYTE[5]: minute 0-59
        # BYTE[6]: second 0-59
        year_bytes = year.to_bytes(2, byteorder="little")
        data = bytearray([
            year_bytes[0],    # First byte of year
            year_bytes[1],    # Second byte of year
            month,            # Month
            day,              # Day
            hour,             # Hour
            minute,           # Minute
            second            # Second
        ])

        # Write to device
        return await self._ble_write(DATE_AND_TIME_UUID, data, "UTC time to device")

    async def read_daylight_saving(self) -> dict:
        """Read daylight saving configuration from device.
        
        Returns:
            dict: Configuration with keys:
                enabled (bool): DST enabled/disabled
                winter_to_summer_offset (int): Offset in minutes for winter->summer transition
                summer_to_winter_offset (int): Offset in minutes for summer->winter transition
                timezone_offset (int): Base timezone offset in minutes from UTC
            None: If read fails
        """
        # Read raw data from device
        data = await self._ble_read(DAYLIGHT_SAVING_UUID, "daylight saving config")
        if not data:
            return None

        if len(data) < 8:
            _LOGGER.error("Invalid daylight saving data length: %d", len(data))
            return None

        # Parse data
        enabled = bool(data[0])
        # bytes 2-3: winter->summer offset (signed int16)
        winter_to_summer = int.from_bytes(data[2:4], byteorder='little', signed=True)
        # bytes 4-5: summer->winter offset (signed int16)
        summer_to_winter = int.from_bytes(data[4:6], byteorder='little', signed=True)
        # bytes 6-7: timezone offset in minutes (signed int16)
        timezone_offset = int.from_bytes(data[6:8], byteorder='little', signed=True)

        return {
            'enabled': enabled,
            'winter_to_summer_offset': winter_to_summer,
            'summer_to_winter_offset': summer_to_winter,
            'timezone_offset': timezone_offset
        }

    async def write_daylight_saving(
        self,
        enabled: bool,
        winter_to_summer: int,
        summer_to_winter: int,
        timezone_offset: int
    ) -> bool:
        """Write daylight saving configuration to device.
        
        According to protocol specification (chapter 2.2.3), device needs proper timezone
        and DST settings to handle local time display correctly.
        
        Args:
            enabled: Enable/disable daylight saving
            winter_to_summer: Offset in minutes for winter to summer transition (default 60 = 1h)
            summer_to_winter: Offset in minutes for summer to winter transition (default 60 = 1h)
            timezone_offset: Base timezone offset in minutes (default 120 = UTC+2 for Finland)
            
        Note: 
            For Finland (EET/EEST):
            - timezone_offset should be 120 (UTC+2)
            - DST changes are 1h (60 minutes)
            - Device adds the DST offset automatically when enabled
        """
        data = bytearray(8)
        data[0] = 1 if enabled else 0  # Enable/disable flag
        data[1] = 0  # Reserved byte

        # Winter->summer offset (1h = 60 minutes)
        data[2:4] = winter_to_summer.to_bytes(2, byteorder='little', signed=True)

        # Summer->winter offset (1h = 60 minutes)
        data[4:6] = summer_to_winter.to_bytes(2, byteorder='little', signed=True)

        # Timezone offset (UTC+2 = 120 minutes for Finland)
        data[6:8] = timezone_offset.to_bytes(2, byteorder='little', signed=True)

        if not await self._ble_write(DAYLIGHT_SAVING_UUID, data, "daylight saving config"):
            return False

        _LOGGER.debug(
            "Wrote DST config to %s for %s: enabled=%s, timezone=%d min",
            self.device_name or "Unknown Device",
            self.mac_address,
            enabled, timezone_offset
        )
        return True

    async def read_floor_limits(self) -> Optional[dict]:
        """Read floor temperature limits from device.
             
        Returns:
            dict with keys:
                low_value: Min floor temp in °C (range 5-42)
                high_value: Max floor temp in °C (range 13-50)
            None if read fails
        """
        data = await self._ble_read(FLOOR_LIMITS_UUID, "floor limits")
        if not data or len(data) != 4:
            return None

        return {
            'low_value': int.from_bytes(data[0:2], byteorder='little') / 100,
            'high_value': int.from_bytes(data[2:4], byteorder='little') / 100
        }

    async def write_floor_limits(self, low_value: float, high_value: float) -> bool:
        """Write floor temperature limits to device.

        Args:
            low_value: Min floor temp in °C (5-42)
            high_value: Max floor temp in °C (13-50)

        Returns:
            True if write successful, False otherwise

        Note:
            - Min must be at least 8°C lower than max
            - Used only in combination mode (mode 3)
            - Min absolute value: 5°C
            - Max absolute value: 50°C
        """
        # Input validation
        if not (5 <= low_value <= 42):
            _LOGGER.error("Min floor temp must be between 5-42°C")
            return False

        if not (13 <= high_value <= 50):
            _LOGGER.error("Max floor temp must be between 13-50°C")
            return False

        if high_value - low_value < 8:
            _LOGGER.error("Min must be at least 8°C lower than max")
            return False

        data = bytearray(4)
        low_raw = int(round(low_value * 100))
        high_raw = int(round(high_value * 100))
        data[0:2] = low_raw.to_bytes(2, byteorder='little')
        data[2:4] = high_raw.to_bytes(2, byteorder='little')

        if not await self._ble_write(FLOOR_LIMITS_UUID, data, "floor limits"):
            return False

        _LOGGER.debug(
            "Floor limits written successfully: min=%.1f °C, max=%.1f °C",
            low_value,
            high_value
        )
        return True

    async def read_floor_sensor_config(self) -> Optional[dict]:
        """Read floor sensor configuration from device.

        Returns:
            dict with keys:
                sensor_type (int): Floor sensor type number
                sensor_missing_limit (int): ADC limit for missing sensor
                sensor_broken_limit (int): ADC limit for broken sensor
                resistance_25c (int): Sensor resistance at 25 °C in ohms
                offset (float): Sensor offset in °C
            None if read fails
        """
        data = await self._ble_read(FLOOR_SENSOR_TYPE_UUID, "floor sensor config")
        if not data:
            return None

        if len(data) < 13:
            _LOGGER.error("Invalid floor sensor config data length: %d", len(data))
            return None

        return {
            'sensor_type': data[0],
            'sensor_missing_limit': int.from_bytes(data[1:3], byteorder='little'),
            'sensor_broken_limit': int.from_bytes(data[7:9], byteorder='little'),
            'resistance_25c': int.from_bytes(data[9:11], byteorder='little'),
            'offset': int.from_bytes(data[11:13], byteorder='little', signed=True) / 10
        }

    async def write_floor_sensor_config(self, params: dict) -> bool:
        """Write floor sensor configuration to device.

        Args:
            params: Floor sensor parameters, one of the FLOOR_SENSOR_CONFIG entries

        Returns:
            True if write successful, False otherwise
        """
        data = bytearray(13)
        data[0] = params["sensor_type"]
        data[1:3] = params["sensor_missing_limit"].to_bytes(2, byteorder='little')
        data[3:5] = params["sensor_b_value"].to_bytes(2, byteorder='little')
        data[5:7] = params["pull_up_resistor"].to_bytes(2, byteorder='little')
        data[7:9] = params["sensor_broken_limit"].to_bytes(2, byteorder='little')
        data[9:11] = params["resistance_25c"].to_bytes(2, byteorder='little')
        data[11:13] = params["offset"].to_bytes(2, byteorder='little', signed=True)

        return await self._ble_write(FLOOR_SENSOR_TYPE_UUID, data, "floor sensor config")

    async def read_room_sensor_calibration(self) -> dict:
        """Read room sensor calibration value."""
        data = await self._ble_read(CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID, "room sensor calibration")
        if not data:
            return None

        raw_value = int.from_bytes(data[0:2], byteorder='little', signed=True)
        calibration_value = round(raw_value / 10, 1)

        return {
            'calibration_value': calibration_value
        }

    async def write_room_sensor_calibration(self, value: float) -> bool:
        """Write room sensor calibration value."""
        if not (-5.0 <= value <= 5.0):
            _LOGGER.error("Calibration value must be between -5.0 and +5.0 °C: %s", value)
            return False

        raw_value = int(value * 10)
        data = raw_value.to_bytes(2, byteorder='little', signed=True)

        return await self._ble_write(CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID, data, "room sensor calibration")

    async def read_software_revision(self) -> Optional[str]:
        """Read software revision string."""
        data = await self._ble_read(SOFTWARE_REVISION_UUID, "software revision")
        if data is None:
            return None

        # Parse format: app;ble;bootloader
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError as e:
            _LOGGER.error("Failed to read software revision: %s", e)
            return None

    async def read_hardware_revision(self) -> Optional[str]:
        """Read hardware revision."""
        data = await self._ble_read(HARDWARE_REVISION_UUID, "hardware revision")
        if data is None:
            return None

        hw_version = int.from_bytes(data[0:4], byteorder='little')
        return str(hw_version)

    async def read_heating_power(self) -> dict:
        """Read custom heating power configuration from device.
        
        Returns:
            dict with keys:
                heating_power (int): Heating power in Watts (range 0-9999)
        """

        # Read raw data from device
        data = await self._ble_read(HEATING_POWER_UUID, "custom heating power value")
        if not data:
            return None

        heating_power = int.from_bytes(data[0:2], byteorder='little')

        return {
            'heating_power': heating_power
        }

    async def write_heating_power(self, value: int) -> bool:
        """Write custom heating power configuration to device.
        
        Args:
            value (int): Heating power in Watts (range 0-9999)
            
        Returns:
            bool: True if successful, False otherwise
        """

        if not (0 <= value <= 9999):
            _LOGGER.error("Heating power value must be between 0 and 9999")
            return False

        data = value.to_bytes(2, byteorder='little')

        return await self._ble_write(HEATING_POWER_UUID, data, "custom heating power value")

    async def read_floor_area(self) -> dict:
        """Read custom floor area configuration from device.
        
        Returns:
            dict with keys:
                floor_area (int): Floor area in square meters (m²)
        """
            
        # Read raw data from device
        data = await self._ble_read(FLOOR_AREA_UUID, "custom floor area value")
        if not data:
            return None

        floor_area = int.from_bytes(data[0:2], byteorder='little')

        return {
            'floor_area': floor_area
        }

    async def write_floor_area(self, value: int) -> bool:
        """Write custom floor area configuration to device.
        
        Args:
            value (int): Floor area in square meters (m²)
            
        Returns:
            bool: True if successful, False otherwise
            
        Note:
            Maximum value is 65535 due to uint16_t limitation
        """

        if not (0 <= value <= 65535):
            _LOGGER.error("Floor area value must be between 0 and 65535 for uint16_t")
            return False

        data = value.to_bytes(2, byteorder='little')

        return await self._ble_write(FLOOR_AREA_UUID, data, "custom floor area value")

    async def read_energy_unit(self) -> dict:
        """Read energy unit configuration from device.
        
        Returns:
            dict with keys:
                currency_code (int): Currency code number
                currency_name (str): Currency name (e.g. "EUR")
                currency_symbol (str): Currency symbol (e.g. "€") 
                price (float): Price per kWh
                
        Example return value:
            {
                'currency_code': 1,
                'currency_name': 'EUR',
                'currency_symbol': '€',
                'price': 12.34
            }
        """

        # Read raw data from device
        data = await self._ble_read(ENERGY_UNIT_UUID, "energy unit configuration")
        if not data:
            return None

        if len(data) < 4:
            _LOGGER.error("Invalid energy unit data length: %d", len(data))
            return None

        # Parse currency (first byte)
        currency = data[0]

        # Parse price (bytes 2-3 as unsigned int16, scaled by 100)
        price_raw = int.from_bytes(data[2:4], byteorder='little')
        price = price_raw / 100.0

        return {
            'currency_code': currency,
            'currency_name': CURRENCY_MAP.get(currency, "Unknown"),
            'currency_symbol': CURRENCY_SYMBOLS.get(currency, ""),
            'price': price
        }

    async def write_energy_unit(self, currency: int, price: float) -> bool:
        """Write energy unit configuration to device."""

        if not (0 <= price <= 655.35):
            _LOGGER.error("Price must be between 0 and 655.35: %s", price)
            return False

        # Prepare data packet
        data = bytearray(4)
        data[0] = currency  # Currency code
        data[1] = 0  # Unused byte

        # Convert price to integer scaled by 100
        price_raw = int(round(price * 100))
        data[2:4] = price_raw.to_bytes(2, byteorder='little')

        # Write to device
        if not await self._ble_write(ENERGY_UNIT_UUID, data, "energy unit configuration"):
            return False

        _LOGGER.debug(
            "Wrote energy unit config for %s (%s) - Currency: %s (%d), Price: %.2f",
            self.device_name, self.mac_address,
            CURRENCY_MAP.get(currency, "Unknown"), currency, price
        )
        return True

    async def read_power_consumption(self) -> dict:
        """Read real time power consumption data.
        
        Returns:
            dict: Dictionary containing:
                - 'timestamp': datetime object of the header timestamp
                - 'measurements': List of dicts with:
                    - 'timestamp': datetime of the measurement
                    - 'ratio': Power consumption ratio (0-100%)
        """
        try:
            data = await self._ble_read_split(REAL_TIME_INDICATION_POWER_CONSUMPTION_UUID, "power consumption")
            
            if not data:
                _LOGGER.debug("No data received from device")
                return None
            
            if len(data) < 4:
                _LOGGER.error("Data too short, expected at least 4 bytes for header")
                return None

            # Restore trailing zeros removed by the split read
            data = data.ljust(4 + 24 * 2, b'\x00')

            # Parse header timestamp
            hour = data[0]  # uint8 hour
            day = data[1]   # uint8 day
            month = data[2] # uint8 month
            year = data[3]  # uint8 year (0-255)
            header_time = datetime(2000 + year, month, day, hour, tzinfo=dt_util.UTC)

            measurements = []

            # Process measurement pairs (delta hour and ratio)
            for i in range(24):  # 24 hours of data
                offset = 4 + i * 2  # Start after header, 2 bytes per measurement
                delta_hours = data[offset]
                ratio = data[offset + 1]
                
                # Skip invalid values (0xff)
                if ratio == 0xff:
                    continue
                    
                measurements.append({
                    'timestamp': header_time - timedelta(hours=delta_hours),
                    'ratio': ratio
                })
            
            return {
                'timestamp': header_time,
                'measurements': measurements
            }

        except Exception as e:
            _LOGGER.error("Error reading power consumption: %s", e)
            return None

    async def read_monitoring_data(self) -> Optional[dict]:
        """Read monitoring data from device which contains power and temperature history.
        
        Returns:
            dict containing:
                - daily_power: List of last 7 days power consumption data
                - monthly_power: List of last 12 months power consumption data
                - temperature_history: List of hourly temperature readings for past week
            None if read fails
        """
        try:
            data = await self._ble_read_split(MONITORING_DATA_UUID, "monitoring data")
            if not data:
                _LOGGER.debug("No monitoring data received from device")
                return None
            
            result = {
                'daily_power': [],
                'monthly_power': [],
                'temperature_history': []
            }

            # Current position in data array
            pos = 0

            # Parse daily power data (7 days)
            # Daily data starts from beginning of the data buffer (pos = 0)
            # Header: day(1) + month(1) + year(1) = 3 bytes
            # Data per day: delta_day(1) + ratio(1) = 2 bytes
            if len(data) >= pos + 3:
                day = data[pos]
                month = data[pos + 1]
                year = data[pos + 2]
                pos += 3

                # Process 7 days of power data
                for _ in range(7):
                    if len(data) >= pos + 2:
                        delta_days = data[pos]
                        ratio_raw = data[pos + 1]
                        
                        timestamp = datetime(2000 + year, month, day, tzinfo=dt_util.UTC) - timedelta(days=delta_days)
                        
                        # Convert raw value to ratio, using None for unset values (0xff)
                        ratio = None if ratio_raw == 0xff else ratio_raw

                        # Store the values in result
                        result['daily_power'].append({
                            'time': timestamp.isoformat(),
                            'ratio': ratio
                        })
                        pos += 2

            # Parse last 12 month power data
            # Offset calculation: daily data uses 19 bytes, so monthly starts at 19
            if len(data) >= 19:  # Need at least daily data section length before monthly
                pos = 19  # Skip daily data section (3 bytes header + 7 * 2 bytes data = 19)
               
                # Header: month(1) + year(1) = 2 bytes
                # Data per month: delta_month(1) + ratio(1) = 2 bytes
                if len(data) >= pos + 2:
                    month = data[pos]
                    year = data[pos + 1]
                    pos += 2

                    # Process 12 months of power data
                    for _ in range(12):
                        if len(data) >= pos + 2:
                            delta_months = data[pos]
                            ratio_raw = data[pos + 1]

                            # Calculate timestamp using relativedelta for accurate month subtraction
                            timestamp = datetime(2000 + year, month, 1, tzinfo=dt_util.UTC) - relativedelta(months=delta_months)
                           
                            # Convert raw value to ratio, using None for unset values (0xff)
                            ratio = None if ratio_raw == 0xff else ratio_raw

                            # Store the values in result
                            result['monthly_power'].append({
                                'time': timestamp.isoformat(),
                                'ratio': ratio
                            })
                            pos += 2

            # Parse temperature history (24 hours * 7 days)
            if len(data) >= 47:  # 19 (daily) + 28 (monthly) bytes minimum before temperature data
                pos = 47  # Skip daily (19) and monthly (28) data sections
               
                # Header: hour(1) + day(1) + month(1) + year(1) = 4 bytes
                if len(data) >= pos + 4:
                    hour = data[pos]
                    day = data[pos + 1]
                    month = data[pos + 2]
                    year = data[pos + 3]
                    pos += 4

                    # Process 168 hours (24*7) of temperature data
                    # Data per hour: delta_hour(1) + floor_temp(2) + room_temp(2) = 5 bytes
                    for _ in range(168):
                        if len(data) >= pos + 5:
                            delta_hours = data[pos]
                           
                            # Get raw temperature values from bytes
                            floor_temp_raw = int.from_bytes(data[pos+1:pos+3], byteorder='little', signed=True)
                            room_temp_raw = int.from_bytes(data[pos+3:pos+5], byteorder='little', signed=True)

                            # Calculate timestamp for this measurement
                            timestamp = datetime(2000 + year, month, min(max(1, day), 28), hour, tzinfo=dt_util.UTC) - timedelta(hours=delta_hours)

                            # Convert raw values to temperatures, using None for unset values (0x7fff)
                            floor_temp = None if floor_temp_raw == 0x7fff else floor_temp_raw / 10
                            room_temp = None if room_temp_raw == 0x7fff else room_temp_raw / 10
                           
                            # Store the values in result
                            result['temperature_history'].append({
                                'time': timestamp.isoformat(),
                                'floor_temp': floor_temp,
                                'room_temp': room_temp,
                            })
                            pos += 5

            return result

        except Exception as e:
            _LOGGER.error("Error reading monitoring data: %s", e)
            return None

    async def read_vacation_time(self) -> Optional[dict]:
        """Read vacation time configuration from device."""
        data = await self._ble_read(VACATION_TIME_UUID, "vacation time")
        if data is None:
            return None

        if len(data) < 15:
            _LOGGER.error("Invalid vacation time data length")
            return None

        try:
            # Parse wall clock time from device
            from_year = 2000 + data[0]
            from_month = data[1]
            from_day = data[2]
            from_hour = data[3]
            from_minute = data[4]

            # Create wall clock time as naive datetime
            time_from_naive = datetime(from_year, from_month, from_day, from_hour, from_minute)
            # Assume it's local time and convert to UTC for Home Assistant
            time_from = dt_util.as_utc(dt_util.as_local(time_from_naive))

            # Parse time to wall clock time
            to_year = 2000 + data[5]
            to_month = data[6]
            to_day = data[7]
            to_hour = data[8]
            to_minute = data[9]

            # Create wall clock time as naive datetime
            time_to_naive = datetime(to_year, to_month, to_day, to_hour, to_minute)
            # Assume it's local time and convert to UTC for Home Assistant
            time_to = dt_util.as_utc(dt_util.as_local(time_to_naive))
        except ValueError as e:
            _LOGGER.error("Error reading vacation time: %s", e)
            return None

        # Parse temperature offset
        offset_temp_raw = int.from_bytes(data[10:12], byteorder='little', signed=True)
        offset_temperature = offset_temp_raw / 100

        # Parse remaining fields
        # Convert percentage offset byte to signed int (range -128 to 127)
        offset_percentage = int.from_bytes([data[12]], byteorder='little', signed=True)
        enabled = bool(data[13])
        active = bool(data[14])

        return {
            'time_from': time_from,
            'time_to': time_to,
            'offset_temperature': offset_temperature,
            'offset_percentage': offset_percentage,
            'enabled': enabled,
            'active': active,
            'raw_data': data.hex()  # Include raw data for logging
        }

    async def write_vacation_time(
        self,
        time_from: datetime,
        time_to: datetime,
        offset_temperature: float,
        offset_percentage: int,
        enabled: bool
    ) -> bool:
        """Write vacation time configuration to device.

        Args:
            time_from (datetime): Start time of vacation (UTC)
            time_to (datetime): End time of vacation (UTC)
            offset_temperature (float): Temperature offset in degrees (-20 to +20)
            offset_percentage (int): Percentage offset (-100% to 100%)
            enabled (bool): Enable/disable vacation mode
        """
        # Validate input ranges
        if not (-20 <= offset_temperature <= 20):
            _LOGGER.error("Temperature offset must be between -20 and +20: %s", offset_temperature)
            return False

        if not (-100 <= offset_percentage <= 100):
            _LOGGER.error("Percentage offset must be between -100 and 100: %s", offset_percentage)
            return False

        # Convert UTC times to local (wall clock) times
        local_from = dt_util.as_local(time_from)
        local_to = dt_util.as_local(time_to)

        # Format for device (remove timezone info)
        from_year = local_from.year - 2000
        if not (0 <= from_year <= 255):
            _LOGGER.error("Start year must be between 2000-2255, got %s", local_from.year)
            return False

        to_year = local_to.year - 2000
        if not (0 <= to_year <= 255):
            _LOGGER.error("End year must be between 2000-2255, got %s", local_to.year)
            return False

        # Read current settings to preserve active state
        current_settings = await self.read_vacation_time()
        current_active = False
        if current_settings and 'active' in current_settings:
            current_active = current_settings['active']

        # Create data packet
        data = bytearray(15)

        # Time from (local wall clock)
        data[0] = from_year
        data[1] = local_from.month
        data[2] = local_from.day
        data[3] = local_from.hour
        data[4] = local_from.minute

        # Time to (local wall clock)
        data[5] = to_year
        data[6] = local_to.month
        data[7] = local_to.day
        data[8] = local_to.hour
        data[9] = local_to.minute

        # Temperature offset
        temp_raw = int(round(offset_temperature * 100))
        data[10:12] = temp_raw.to_bytes(2, byteorder='little', signed=True)

        # Percentage and enabled
        # Convert percentage offset to signed int8
        data[12] = offset_percentage.to_bytes(1, byteorder='little', signed=True)[0]
        data[13] = 1 if enabled else 0  # User-set enabled state - byte 13
        data[14] = 1 if current_active else 0  # Preserve current active state - byte 14 (read only)

        return await self._ble_write(VACATION_TIME_UUID, data, "vacation time")

    async def read_calendar_mode(self) -> Optional[dict]:
        """Read calendar mode setting from device.
        
        Returns:
            dict with key 'enabled' (bool) or None if failed
        """
        # Read single byte from device
        data = await self._ble_read(CALENDAR_MODE_UUID, "calendar mode")
        if not data:
            return None

        enabled = bool(data[0])

        return {'enabled': enabled}

    async def write_calendar_mode(self, enabled: bool) -> bool:
        """Write calendar mode setting to device.
        
        Args:
            enabled: True to enable calendar mode, False to disable
            
        Returns:
            True if successful, False otherwise
        """
        # Create single byte data
        data = bytes([1 if enabled else 0])

        # Write to device
        if not await self._ble_write(CALENDAR_MODE_UUID, data, "calendar mode"):
            return False

        _LOGGER.debug("Action [Calendar Mode %s] for [%s]: success",
                     "Enable" if enabled else "Disable", self.mac_address)
        return True

    async def read_calendar_day(self, day: int) -> Optional[dict]:
        """Read calendar day programs from device.
        
        Args:
            day: Day number (1=Monday, 7=Sunday)
            
        Returns:
            dict with 'day' and 'programs' list, or None if failed
        """
        if not (1 <= day <= 7):
            _LOGGER.error("Invalid day number: %s (must be 1-7)", day)
            return None

        # Write day number to control characteristic
        if not await self._ble_write(CALENDAR_CONTROL_UUID, bytes([day]), "calendar control"):
            return None

        # Add small delay to let device process the request
        await asyncio.sleep(0.2)

        # Read split data from calendar day characteristic
        data = await self._ble_read_split(CALENDAR_DAY_UUID, "calendar day")
        if not data:
            _LOGGER.error("No calendar day data received")
            return None

        # Parse day number
        day_number = data[0]

        # Valid program data: (length - 1) must be divisible by 8
        if (len(data) - 1) % 8 != 0:
            _LOGGER.error("Invalid calendar day data length: %d (not 1 + multiple of 8)", len(data))
            return None

        # Parse each program (an empty day has no program bytes)
        programs = []
        for i in range((len(data) - 1) // 8):
            offset = 1 + i * 8  # Start after day byte, 8 bytes per program

            temp_offset_raw = int.from_bytes(data[offset + 4:offset + 6], byteorder='little', signed=True)

            programs.append({
                'start_hour': data[offset],
                'start_minute': data[offset + 1],
                'end_hour': data[offset + 2],
                'end_minute': data[offset + 3],
                'temp_offset': temp_offset_raw / 100.0,  # Convert from device format (200 = 2.0°C)
                'power_offset': int.from_bytes([data[offset + 6]], byteorder='little', signed=True),
                'enabled': bool(data[offset + 7])
            })

        return {
            'day': day_number,
            'programs': programs
        }

    async def write_calendar_day(self, day: int, programs: list) -> bool:
        """Write calendar day programs to device.
        
        Args:
            day: Day number (1=Monday, 7=Sunday)
            programs: List of up to 6 program dicts with keys:
                     start_hour, start_minute, end_hour, end_minute,
                     temp_offset, power_offset, enabled
                     
        Returns:
            True if successful, False otherwise
        """
        if not (1 <= day <= 7):
            _LOGGER.error("Invalid day number: %s (must be 1-7)", day)
            return False

        if len(programs) > 6:
            _LOGGER.error("Too many programs: %s (max 6)", len(programs))
            return False

        # Create 49-byte data packet; unused programs stay all zeros (disabled)
        data = bytearray(49)
        data[0] = day

        try:
            for i, program in enumerate(programs):
                offset = 1 + i * 8

                # Validate program data
                for field in ['start_hour', 'start_minute', 'end_hour', 'end_minute', 'temp_offset', 'power_offset', 'enabled']:
                    if field not in program:
                        _LOGGER.error("Missing field '%s' in program %d", field, i)
                        return False

                data[offset] = program['start_hour']
                data[offset + 1] = program['start_minute']
                data[offset + 2] = program['end_hour']
                data[offset + 3] = program['end_minute']

                # Convert temperature offset to device format (20.5°C = 2050)
                temp_raw = int(round(program['temp_offset'] * 100))
                data[offset + 4:offset + 6] = temp_raw.to_bytes(2, byteorder='little', signed=True)

                # Power offset as signed int8
                data[offset + 6] = program['power_offset'].to_bytes(1, byteorder='little', signed=True)[0]
                data[offset + 7] = 1 if program['enabled'] else 0
        except Exception as e:
            _LOGGER.error("Invalid calendar program data: %s", e)
            return False

        # Tell device which day we're writing to
        if not await self._ble_write(CALENDAR_CONTROL_UUID, bytes([day]), "calendar control"):
            return False

        # Write using split protocol
        if not await self._ble_write_split(CALENDAR_DAY_UUID, bytes(data), "calendar day"):
            return False

        # Add small delay to let device process the request
        await asyncio.sleep(0.2)

        # Save to flash (write 0 to control characteristic)
        return await self._ble_write(CALENDAR_CONTROL_UUID, bytes([0]), "calendar control")

    async def read_force_control(self) -> Optional[dict]:
        """Read force control / external control configuration from device.

        Returns:
            dict with keys:
                enabled (bool): External control enabled/disabled
                mode (int): External control mode number
                mode_name (str): Human-readable mode name
                temperature (float): Absolute temperature for mode 5 (5-35°C)
                temperature_offset (float): Temperature offset for mode 6 (-20 to +20°C)
                data_length (int): Length of data received from device
            None if read fails

        Note:
            Mode values:
            - 1 = OFF (disabled)
            - 5 = Temperature (absolute target, uses byte[8-9])
            - 6 = Temperature change (offset from normal, uses byte[12-13])
        """
        data = await self._ble_read(FORCE_CONTROL_UUID, "force control")
        if data is None:
            return None

        device_name = self.device_name or "Unknown Device"

        if len(data) >= 19:
            # Extended 19-byte format
            mode = data[17]

            # Mode 5 "Temperature": absolute temperature in byte[8-9]
            temp_raw = int.from_bytes(data[8:10], byteorder='little')
            temperature = temp_raw / 10.0

            # Mode 6 "Temperature change": offset in byte[12-13] (signed)
            offset_raw = int.from_bytes(data[12:14], byteorder='little', signed=True)
            temperature_offset = offset_raw / 10.0

            mode_names = EXTERNAL_CONTROL_MODES

            _LOGGER.debug(
                "Read Force Control %s for %s: mode=%s, temp=%.1f°C, offset=%+.1f°C",
                device_name, self.mac_address,
                mode_names.get(mode, "Unknown"),
                temperature, temperature_offset
            )

            return {
                'enabled': mode in (5, 6),
                'mode': mode,
                'mode_name': EXTERNAL_CONTROL_MODES.get(mode, "Unknown"),
                'temperature': temperature,
                'temperature_offset': temperature_offset,
                'data_length': len(data)
            }

        elif len(data) == 1:
            # Original 1-byte format (potentiometer value only 0-100%)
            _LOGGER.debug(
                "Read Force Control %s for %s: legacy 1-byte format, value=%d%%",
                device_name, self.mac_address, data[0]
            )

            return {
                'enabled': False,
                'mode': 1,
                'mode_name': "Off",
                'temperature': 20.0,
                'temperature_offset': 0.0,
                'data_length': len(data)
            }

        _LOGGER.error(
            "Read Force Control %s for %s: unexpected data length %d",
            device_name, self.mac_address, len(data)
        )
        return None

    async def write_force_control(self, mode: int, temperature: float, temperature_offset: float) -> bool:
        """Write force control / external control configuration to device.

        Args:
            enabled: Enable/disable external control
            mode: External control mode (5=Temperature, 6=Temperature change)
            temperature: Absolute temperature for mode 5 (5.0 to 50.0°C)
            temperature_offset: Temperature offset for mode 6 (-20.0 to +20.0°C)

        Returns:
            True if successful, False otherwise
        """
        device_name = self.device_name or "Unknown Device"

        # Read current values to preserve unchanged settings
        current = await self._ble_read(FORCE_CONTROL_UUID, "force control")
        if not current:
            _LOGGER.error(
                "Write Force Control %s for %s: could not read current settings",
                device_name, self.mac_address
            )
            return False

        # Check for legacy 1-byte format (old firmware)
        if len(current) < 19:
            _LOGGER.debug(
                "Write Force Control %s for %s: device uses legacy 1-byte format, external control not supported",
                device_name, self.mac_address
            )
            return False

        # Start with current data
        data = bytearray(current)

        # Update mode 5 temperature (byte[8-9])
        temp_value = int(max(5.0, min(35.0, temperature)) * 10)
        data[8:10] = temp_value.to_bytes(2, byteorder='little')

        # Update mode 6 offset (byte[12-13], signed)
        offset_value = int(max(-20.0, min(20.0, temperature_offset)) * 10)
        data[12:14] = offset_value.to_bytes(2, byteorder='little', signed=True)

        # Set mode
        if mode in EXTERNAL_CONTROL_MODES:
            data[17] = mode

        if not await self._ble_write(FORCE_CONTROL_UUID, data, "force control"):
            return False

        mode_names = {2: "Off", 5: "Temperature", 6: "Temperature change"}

        _LOGGER.debug(
            "Wrote Force Control %s for %s: mode=%s, temp=%.1f°C, offset=%+.1f°C",
            device_name, self.mac_address,
            mode_names.get(data[17], "Unknown"),
            temperature, temperature_offset
        )

        return True
