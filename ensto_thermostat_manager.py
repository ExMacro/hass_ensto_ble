"""Support for Ensto BLE devices."""
import logging
import asyncio
from typing import Optional
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection, BleakClientWithServiceCache
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from .storage_manager import EnstoStorageManager
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from calendar import monthrange
from homeassistant.util import dt as dt_util

from .const import (
    MANUFACTURER_ID,
    ERROR_CODES_BYTE0,
    ERROR_CODES_BYTE1,
    ACTIVE_MODES,
    MODE_MAP,
    CURRENCY_MAP,
    CURRENCY_SYMBOLS,
    MANUFACTURER_NAME_UUID,
    DEVICE_NAME_UUID,
    MODEL_NUMBER_UUID,
    SOFTWARE_REVISION_UUID,
    MANUFACTURING_DATE_UUID,
    HARDWARE_REVISION_UUID,
    DATE_AND_TIME_UUID,
    DAYLIGHT_SAVING_UUID,
    HEATING_MODE_UUID,
    BOOST_UUID,
    POWER_CONTROL_CYCLE_UUID,
    FLOOR_LIMITS_UUID,
    CHILD_LOCK_UUID,
    ADAPTIVE_TEMPERATURE_CONTROL_UUID,
    FLOOR_SENSOR_TYPE_UUID,
    HEATING_POWER_UUID,
    FLOOR_AREA_UUID,
    CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID,
    LED_BRIGHTNESS_UUID,
    ENERGY_UNIT_UUID,
    ALARM_CODE_UUID,
    CALENDAR_CONTROL_UUID,
    CALENDAR_DAY_UUID,
    VACATION_TIME_UUID,
    CALENDAR_MODE_UUID,
    FACTORY_RESET_ID_UUID,
    MONITORING_DATA_UUID,
    REAL_TIME_INDICATION_UUID,
    REAL_TIME_INDICATION_POWER_CONSUMPTION_UUID,
    FORCE_CONTROL_UUID,
)

_LOGGER = logging.getLogger(__name__)

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

    def setup(self) -> None:
        """Set up the scanner when needed."""
        self.scanner = bluetooth.async_get_scanner(self.hass)

    async def initialize(self) -> None:
        """Initialize the connection."""
        await self.connect()

    async def cleanup(self) -> None:
        """Clean up the connection."""
        if self.client and self.client.is_connected:
            await self.client.disconnect()

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

                    _LOGGER.debug("Connecting to device %s", self.mac_address)
                    self.client = BleakClient(device)
                    await self.client.connect(timeout=10.0)
                    _LOGGER.debug("Connected to device %s", self.mac_address)

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
                fields = adv.manufacturer_data[MANUFACTURER_ID].decode('ascii').split(';')
                if len(fields) >= 2 and fields[1] == "1":
                    _LOGGER.info(f"Device {discovery_info.name} address {discovery_info.address} is in pairing mode")
                    pairing_devices[addr] = (discovery_info, adv)
            except Exception as e:
                _LOGGER.error(f"Error parsing manufacturer data: %s", e)
                
        return pairing_devices

    async def read_factory_reset_id(self) -> Optional[int]:
        """Read Factory Reset ID from the BLE device."""
        try:
            data = await self.client.read_gatt_char(FACTORY_RESET_ID_UUID)
            factory_reset_id = int.from_bytes(data[:4], byteorder="little")
            return factory_reset_id
        except Exception as e:
            raise Exception("Failed to read factory reset ID: %s", e)

    async def write_factory_reset_id(self, factory_reset_id: int) -> None:
        """Write the Factory Reset ID to the BLE device."""
        try:
            id_bytes = factory_reset_id.to_bytes(4, byteorder="little")
            await self.client.write_gatt_char(FACTORY_RESET_ID_UUID, id_bytes)
        except Exception as e:
            raise Exception("Failed to write factory reset ID: %s", e)

    async def read_split_characteristic(self, characteristic_uuid: str) -> bytes:
        """
        Read BLE characteristic data that uses split format.
        
        Args:
            characteristic_uuid: UUID of the characteristic to read
            
        Returns:
            bytes: Combined data from all split packets
            
        Raises:
            BleakError: If there's an error reading the characteristic
        """
        await self.ensure_connection()
        
        combined_data = bytearray()
        more_data = True
        
        try:
            while more_data:
                # Read next packet
                packet = await self.client.read_gatt_char(characteristic_uuid)
                
                if not packet or len(packet) < 1:
                    break
                    
                header = packet[0]
                data = packet[1:]
                
                # Add data portion to combined data
                combined_data.extend(data)
                
                # Check if this was the last packet (0x40 bit set in header)
                if header & 0x40:
                    more_data = False
                    
            # Remove padding bytes (zeros from the end)
            return bytes(combined_data).rstrip(b'\x00')
            
        except BleakError as e:
            _LOGGER.error("Error reading characteristic: %s", e)
            # Connection might be dead, clear it
            self.client = None
            raise

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
        try:
            if not self.client or not self.client.is_connected:
                return None
                
            # Read the raw bytes
            model_number_raw = await self.client.read_gatt_char(MODEL_NUMBER_UUID)

            # Decode using UTF-8
            model_number = model_number_raw.decode('utf-8')
            return model_number
            
        except Exception as e:
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
            try:
                if not self.client or not self.client.is_connected:
                    _LOGGER.error("Device not connected.")
                    return None

                # Read raw data from device
                data = await self.client.read_gatt_char(BOOST_UUID)

                # Parse data
                enabled = bool(data[0])  # First byte is enable flag
                
                # Parse temperature offset (bytes 1-2 as signed int16)
                # Convert from raw value (2150 = 21.5 degrees)
                offset_raw = int.from_bytes(data[1:3], byteorder='little', signed=True)
                offset_degrees = offset_raw / 100.0
                
                # Parse percentage offset (byte 3)
                offset_percentage = data[3]
                
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

            except Exception as e:
                _LOGGER.error("Failed to read boost config: %s", e)
                return None

    async def write_boost(self, enabled: bool, offset_degrees: float, offset_percentage: int, duration_minutes: int) -> bool:
        """Write boost configuration to device."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # Validate input values
            if not (0 <= offset_degrees <= 50):
                raise ValueError("Temperature offset must be between 0 and 50 degrees")
            if not (0 <= offset_percentage <= 100):
                raise ValueError("Percentage offset must be between 0 and 100")
            if not (0 <= duration_minutes <= 65535):  # max value for uint16
                raise ValueError("Duration must be between 0 and 65535 minutes")

            # Convert temperature to raw value (multiply by 100)
            # e.g., 21.5 degrees becomes 2150
            offset_raw = int(offset_degrees * 100)

            # Create data packet (8 bytes)
            data = bytearray(8)
            data[0] = 1 if enabled else 0  # Enable/disable flag
            
            # Temperature offset as signed int16
            data[1:3] = offset_raw.to_bytes(2, byteorder='little', signed=True)
            
            # Percentage offset
            data[3] = offset_percentage
            
            # Duration setpoint as unsigned int16
            data[4:6] = duration_minutes.to_bytes(2, byteorder='little')
            
            # Remaining time bytes are left as 0
            data[6:8] = (0).to_bytes(2, byteorder='little')
            
            # Write to device
            await self.client.write_gatt_char(BOOST_UUID, data, response=True)
            return True

        except Exception as e:
            _LOGGER.error("Failed to write boost config: %s", e)
            return False

    async def read_heating_mode(self) -> dict:
        """Read heating mode configuration from device."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(HEATING_MODE_UUID)

            # Get mode number from first byte
            mode_number = data[0]
            mode_name = MODE_MAP.get(mode_number, "Unknown")

            return {
                'mode_number': mode_number,
                'mode_name': mode_name
            }

        except Exception as e:
            _LOGGER.error("Failed to read heating mode: %s", e)
            return None

    async def write_heating_mode(self, mode: int) -> bool:
        """Write heating mode configuration to device."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # Validate input mode
            if mode not in MODE_MAP:
                raise ValueError(
                    "Invalid mode. Must be: "
                    "1 (Floor), 2 (Room), 3 (Combination), "
                    "4 (Power), or 5 (Force Control)"
                )

            # Pack data - just a single byte
            data = bytes([mode])
            
            # Write to device
            await self.client.write_gatt_char(HEATING_MODE_UUID, data, response=True)
            return True

        except Exception as e:
            _LOGGER.error("Failed to write heating mode: %s", e)
            return False

    async def read_adaptive_temp_control(self) -> dict:
        """Read adaptive temperature control setting from device."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(ADAPTIVE_TEMPERATURE_CONTROL_UUID)

            # Parse first byte as boolean
            enabled = bool(data[0])

            return {
                'enabled': enabled
            }

        except Exception as e:
            _LOGGER.error("Failed to read adaptive temperature control: %s", e)
            return None

    async def write_adaptive_temp_control(self, enabled: bool) -> bool:
        """Write adaptive temperature control setting to device."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # Create single byte data
            data = bytes([1 if enabled else 0])
            
            # Write to device
            await self.client.write_gatt_char(ADAPTIVE_TEMPERATURE_CONTROL_UUID, data, response=True)
            return True

        except Exception as e:
            _LOGGER.error("Failed to write adaptive temperature control: %s", e)
            return False

    async def read_device_name(self) -> Optional[str]:
        """
        Read device name via GATT characteristic.
        
        Returns:
            str - Device name if successful, None if failed or device is unnamed
        """
        try:
            if not self.client or not self.client.is_connected:
                return None
                
            # Read the raw bytes
            raw_data = await self.client.read_gatt_char(DEVICE_NAME_UUID)
            
            # Skip first byte and strip null bytes
            name_bytes = raw_data[1:].split(b'\x00')[0]
            
            # If no actual name data, return None
            if not name_bytes:
                return None
                
            # Decode using UTF-8 to handle Nordic characters
            device_name = name_bytes.decode('utf-8')
            return device_name
            
        except Exception as e:
            _LOGGER.error(f"Failed to read device name: {e}")
            return None

    async def write_device_name(self, new_name: str) -> bool:
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # Read current data
            current_data = await self.client.read_gatt_char(DEVICE_NAME_UUID)

            # Create a 60-byte array and copy the first byte from the current data.
            name_bytes = bytearray([current_data[0]] + [0] * 59)

            # Set the new name encoded in UTF-8 starting from the second byte.
            encoded_name = new_name.encode('utf-8')
            name_bytes[1:len(encoded_name)+1] = encoded_name

            await self.client.write_gatt_char(DEVICE_NAME_UUID, name_bytes, response=True)

            _LOGGER.info(f"Successfully wrote device name: {new_name}")
            return True

        except Exception as e:
            _LOGGER.error(f"Failed to write device name: {str(e)}")
            return False

    async def write_split_characteristic(self, characteristic_uuid: str, data: bytes) -> bool:
        """
        Write BLE characteristic data that needs to be split into multiple packets.
        """
        await self.ensure_connection()
        
        try:
            # Get MTU size and calculate max chunk size
            mtu_size = self.client.mtu_size
            _LOGGER.debug(f"Current MTU size: {mtu_size}")
            max_chunk_size = mtu_size - 3  # Reserve 3 bytes for ATT header
            
            # Calculate chunk size to ensure at least 2 packets
            chunk_size = len(data) // 2 + (len(data) % 2)  # Force split into two chunks
            
            # Calculate how many chunks we need
            total_chunks = 2  # Force minimum of 2 chunks
            
            for current_chunk in range(total_chunks):
                # Calculate start and end positions for this chunk's data
                start_pos = current_chunk * chunk_size
                end_pos = min(start_pos + chunk_size, len(data))
                chunk_data = data[start_pos:end_pos]
                
                # Create header byte:
                if current_chunk == 0:
                    # First packet: header is just sequence number (0)
                    header = 0x00
                else:
                    # Last packet: 0x40 bit set but sequence number stays 0
                    header = 0x40
                
                # Combine header and data
                packet = bytearray([header]) + chunk_data
                
                # Debug log for each packet
                _LOGGER.debug(
                    f"Writing chunk {current_chunk + 1}/{total_chunks}:"
                    f"\nHeader: 0x{header:02x}"
                    f"\nChunk data (bytes): {chunk_data.hex()}"
                    f"\nFull packet (bytes): {packet.hex()}"
                )
                
                # Write the packet
                await self.client.write_gatt_char(characteristic_uuid, packet, response=True)
                
                # Small delay between packets
                await asyncio.sleep(0.1)
            
            return True
            
        except BleakError as e:
            _LOGGER.error("Error writing characteristic: %s", e)
            # Connection might be dead, clear it
            self.client = None
            raise

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
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(DATE_AND_TIME_UUID)

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

        except Exception as e:
            _LOGGER.error("Failed to read date and time from device: %s", e)
            return None

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
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # Validate input values
            if not (0 <= year <= 9999):
                _LOGGER.error(f"Invalid UTC year: {year}")
                return False
            if not (1 <= month <= 12):
                _LOGGER.error(f"Invalid UTC month: {month}")
                return False
            if not (1 <= day <= 31):
                _LOGGER.error(f"Invalid UTC day: {day}")
                return False
            if not (0 <= hour <= 23):
                _LOGGER.error(f"Invalid UTC hour: {hour}")
                return False
            if not (0 <= minute <= 59):
                _LOGGER.error(f"Invalid UTC minute: {minute}")
                return False
            if not (0 <= second <= 59):
                _LOGGER.error(f"Invalid UTC second: {second}")
                return False

            # Log UTC time being written
            _LOGGER.debug(
                "Writing UTC time to device: %04d-%02d-%02d %02d:%02d:%02d",
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
            await self.client.write_gatt_char(DATE_AND_TIME_UUID, data, response=True)
            return True

        except Exception as e:
            _LOGGER.error("Failed to write UTC time to device: %s", e)
            return False

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
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(DAYLIGHT_SAVING_UUID)

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

        except Exception as e:
            _LOGGER.error("Failed to read daylight saving config: %s", e)
            return None

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
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            data = bytearray(8)
            data[0] = 1 if enabled else 0  # Enable/disable flag
            data[1] = 0  # Reserved byte
            
            # Winter->summer offset (1h = 60 minutes)
            data[2:4] = winter_to_summer.to_bytes(2, byteorder='little', signed=True)
            
            # Summer->winter offset (1h = 60 minutes)
            data[4:6] = summer_to_winter.to_bytes(2, byteorder='little', signed=True)
            
            # Timezone offset (UTC+2 = 120 minutes for Finland)
            data[6:8] = timezone_offset.to_bytes(2, byteorder='little', signed=True)

            await self.client.write_gatt_char(DAYLIGHT_SAVING_UUID, data, response=True)
            _LOGGER.debug(
                "Wrote DST config - enabled: %s, winter->summer: %d min, summer->winter: %d min, timezone: %d min",
                enabled, winter_to_summer, summer_to_winter, timezone_offset
            )
            return True

        except Exception as e:
            _LOGGER.error("Failed to write daylight saving config: %s", e)
            return False

    async def read_floor_limits(self) -> Optional[dict]:
        """Read floor temperature limits from device.
             
        Returns:
            dict with keys:
                low_value: Min floor temp in °C (range 5-42)
                high_value: Max floor temp in °C (range 13-50)
            None if read fails
        """
        try:
            data = await self.client.read_gatt_char(FLOOR_LIMITS_UUID)
            if not data or len(data) != 4:
                return None
                   
            return {
                'low_value': int.from_bytes(data[0:2], byteorder='little') / 100,
                'high_value': int.from_bytes(data[2:4], byteorder='little') / 100
            }
        except Exception as e:
            _LOGGER.error("Failed to read floor limits: %s", e)
            return None

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
        try:
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
            low_raw = int(low_value * 100)
            high_raw = int(high_value * 100)
            data[0:2] = low_raw.to_bytes(2, byteorder='little')
            data[2:4] = high_raw.to_bytes(2, byteorder='little')
               
            await self.client.write_gatt_char(FLOOR_LIMITS_UUID, data)
            _LOGGER.debug(
                "Floor limits written successfully: min=%.1f°C, max=%.1f°C",
                low_value,
                high_value
            )
            return True
        except Exception as e:
            _LOGGER.error("Failed to write floor limits: %s", e)
            return False

    async def read_room_sensor_calibration(self) -> dict:
        """Read room sensor calibration value."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None
                
            data = await self.client.read_gatt_char(CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID)
            raw_value = int.from_bytes(data[0:2], byteorder='little', signed=True)
            calibration_value = round(raw_value / 10, 1)
            
            return {
                'calibration_value': calibration_value
            }
                
        except Exception as e:
            _LOGGER.error("Failed to read room sensor calibration: %s", e)
            return None

    async def write_room_sensor_calibration(self, value: float) -> bool:
        """Write room sensor calibration value."""
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False
                
            if not (-5.0 <= value <= 5.0):
                raise ValueError("Calibration value must be between -5.0 and +5.0 °C")
                
            raw_value = int(value * 10)
            data = raw_value.to_bytes(2, byteorder='little', signed=True)
            
            await self.client.write_gatt_char(
                CALIBRATION_VALUE_FOR_ROOM_TEMPERATURE_UUID,
                data,
                response=True
            )
            
            return True
                
        except Exception as e:
            _LOGGER.error("Failed to write room sensor calibration: %s", e)
            return False

    async def read_software_revision(self) -> Optional[str]:
        """Read software revision string."""
        try:
            if not self.client or not self.client.is_connected:
                return None
            data = await self.client.read_gatt_char(SOFTWARE_REVISION_UUID)
            # Parse format: app;ble;bootloader
            return data.decode('utf-8')
        except Exception as e:
            _LOGGER.error("Failed to read software revision: %s", e)
            return None

    async def read_hardware_revision(self) -> Optional[str]:
        """Read hardware revision."""
        try:
            if not self.client or not self.client.is_connected:
                return None
            data = await self.client.read_gatt_char(HARDWARE_REVISION_UUID)
            hw_version = int.from_bytes(data[0:4], byteorder='little')
            return str(hw_version)
        except Exception as e:
            _LOGGER.error("Failed to read hardware revision: %s", e)
            return None

    async def read_heating_power(self) -> dict:
        """Read custom heating power configuration from device.
        
        Returns:
            dict with keys:
                heating_power (int): Heating power in Watts (range 0-9999)
        """

        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(HEATING_POWER_UUID)
            
            heating_power = int.from_bytes(data[0:2], byteorder='little')

            return {
                'heating_power': heating_power
            }
        except Exception as e:
            _LOGGER.error("Failed to read custom heating power value: %s", e)
            return None

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

        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False
                
            data = value.to_bytes(2, byteorder='little')
            
            await self.client.write_gatt_char(HEATING_POWER_UUID, data, response=True)

            return True

        except Exception as e:
            _LOGGER.error("Failed to write custom heating power value: %s", e)
            return False

    async def read_floor_area(self) -> dict:
        """Read custom floor area configuration from device.
        
        Returns:
            dict with keys:
                floor_area (int): Floor area in square meters (m²)
        """
            
        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(FLOOR_AREA_UUID)
            
            floor_area = int.from_bytes(data[0:2], byteorder='little')

            return {
                'floor_area': floor_area
            }
        except Exception as e:
            _LOGGER.error("Failed to read custom floor area value: %s", e)
            return None

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

        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False
                
            data = value.to_bytes(2, byteorder='little')
            
            await self.client.write_gatt_char(FLOOR_AREA_UUID, data, response=True)

            return True

        except Exception as e:
            _LOGGER.error("Failed to write custom floor area value: %s", e)
            return False

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

        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return None

            # Read raw data from device
            data = await self.client.read_gatt_char(ENERGY_UNIT_UUID)
            
            # Parse currency (first byte)
            currency = data[0]
            
            # Parse price (bytes 2-3 as unsigned int16, scaled by 100)
            price_raw = int.from_bytes(data[2:4], byteorder='little')
            price = price_raw / 100.0

            # Default to EUR (1) if currency code is invalid
            if currency not in CURRENCY_MAP:
                _LOGGER.warning(f"Received invalid currency code: {currency}. Defaulting to EUR.")
                currency = 1

            return {
                'currency_code': currency,
                'currency_name': CURRENCY_MAP.get(currency, "Unknown"),
                'currency_symbol': CURRENCY_SYMBOLS.get(currency, ""),
                'price': price
            }
        except Exception as e:
            _LOGGER.error("Failed to read energy unit configuration: %s", e)
            return None

    async def write_energy_unit(self, currency: int, price: float) -> bool:
        """Write energy unit configuration to device."""

        try:
            if not self.client or not self.client.is_connected:
                _LOGGER.error("Device not connected.")
                return False

            # If no currency provided or invalid, default to EUR (1)
            if currency not in CURRENCY_MAP:
                _LOGGER.warning(f"Invalid currency code: {currency}. Defaulting to EUR.")
                currency = 1

            # Validate inputs using CURRENCY_MAP keys
            if currency not in CURRENCY_MAP:
                _LOGGER.error(f"Invalid currency code: {currency}")
                return False
            
            if not (0 <= price <= 655.35):
                _LOGGER.error(f"Price must be between 0 and 655.35: {price}")
                return False

            # Prepare data packet
            data = bytearray(4)
            data[0] = currency  # Currency code
            data[1] = 0  # Unused byte

            # Convert price to integer scaled by 100
            price_raw = int(price * 100)
            data[2:4] = price_raw.to_bytes(2, byteorder='little')

            # Write to device
            await self.client.write_gatt_char(ENERGY_UNIT_UUID, data, response=True)
            
            _LOGGER.debug(
                "Wrote energy unit config - Currency: %s (%d), Price: %.2f",
                CURRENCY_MAP.get(currency, "Unknown"), currency, price
            )
            return True

        except Exception as e:
            _LOGGER.error("Failed to write energy unit configuration: %s", e)
            return False

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
            data = await self.read_split_characteristic(REAL_TIME_INDICATION_POWER_CONSUMPTION_UUID)
            
            if not data:
                _LOGGER.debug("No data received from device")
                return None
            
            if len(data) < 4:
                _LOGGER.error("Data too short, expected at least 4 bytes for header")
                return None

            # Parse header timestamp
            hour = data[0]  # uint8 hour
            day = data[1]   # uint8 day
            month = data[2] # uint8 month
            year = data[3]  # uint8 year (0-255)

            measurements = []

            # Process measurement pairs (delta hour and ratio)
            for i in range(24):  # 25 hours of data
                offset = 4 + i * 2  # Start after header, 2 bytes per measurement
                delta_hours = data[offset]
                ratio = data[offset + 1]
                
                # Skip invalid values (0xff)
                if ratio == 0xff:
                    continue
                    
                # Calculate timestamp for this measurement
                timestamp = datetime(2000 + year, month, day, hour, tzinfo=dt_util.UTC) - timedelta(hours=delta_hours)
                
                measurements.append({
                    'timestamp': timestamp,
                    'ratio': ratio
                })
            
            return {
                'timestamp': timestamp,
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
            data = await self.read_split_characteristic(MONITORING_DATA_UUID)
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
