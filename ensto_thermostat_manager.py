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
from datetime import datetime
from homeassistant.util import dt as dt_util

from .const import (
    MANUFACTURER_ID,
    ERROR_CODES_BYTE0,
    ERROR_CODES_BYTE1,
    ACTIVE_MODES,
    MODE_MAP,
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
        self._is_connecting = False
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
            async with self._connect_lock:
                if self._is_connecting:
                    return

                self._is_connecting = True
                try:
                    if self.client and self.client.is_connected:
                        return

                    _LOGGER.debug("Finding device %s", self.mac_address)
                    device = bluetooth.async_ble_device_from_address(self.hass, self.mac_address)
                    if not device:
                        raise Exception(f"Device {self.mac_address} not found")

                    _LOGGER.debug("Connecting to device %s", self.mac_address)
                    self.client = await establish_connection(
                        client_class=BleakClientWithServiceCache,
                        device=device,
                        name=self.mac_address,
                        timeout=10.0
                    )
                    _LOGGER.debug("Connected to device %s", self.mac_address)

                except Exception as e:
                    _LOGGER.error("Failed to connect: %s", str(e))
                    self.client = None
                    raise
                finally:
                    self._is_connecting = False

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
            await self.ensure_connection()
            data = await self.client.read_gatt_char(FACTORY_RESET_ID_UUID)
            factory_reset_id = int.from_bytes(data[:4], byteorder="little")
            return factory_reset_id
        except Exception as e:
            _LOGGER.error("Failed to read factory reset ID: %s", e)
            return None

    async def write_factory_reset_id(self, factory_reset_id: int) -> None:
        """Write the Factory Reset ID to the BLE device."""
        try:
            await self.ensure_connection()
            id_bytes = factory_reset_id.to_bytes(4, byteorder="little")
            await self.client.write_gatt_char(FACTORY_RESET_ID_UUID, id_bytes)
        except Exception as e:
            _LOGGER.error("Failed to write factory reset ID: %s", e)

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

    async def setup_bluetooth_pairing(self) -> bool:
        """Execute bluetooth pairing."""
        try:
            async def run_bluetoothctl():
                process = await asyncio.create_subprocess_exec(
                    'bluetoothctl',
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE
                )

                commands = [
                    f"remove {self.mac_address}",  # Remove old pairing if exists
                    "scan on",                     # Start scanning
                    "sleep 2",                     # Wait a moment
                    f"pair {self.mac_address}",    # Pair
                    "sleep 2",                     # Wait for pairing
                    f"trust {self.mac_address}",   # Trust device
                    f"connect {self.mac_address}", # Connect
                    "scan off",                    # Stop scanning
                    "quit"
                ]

                for cmd in commands:
                    _LOGGER.debug("Executing bluetooth command: %s", cmd)
                    if cmd.startswith("sleep"):
                        await asyncio.sleep(int(cmd.split()[1]))
                    else:
                        if process.stdin:
                            process.stdin.write(f"{cmd}\n".encode())
                            await process.stdin.drain()

                stdout, stderr = await process.communicate()
                _LOGGER.debug("Bluetooth pairing output: %s", stdout.decode())
                return b"Failed" not in stdout if stdout else False

            return await run_bluetoothctl()

        except Exception as e:
            _LOGGER.error("Pairing error: %s", e)
            return False

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

    async def connect_and_verify(self) -> bool:
        """Connect and verify the device.
        Attempts to pair if no Factory Reset ID is found in storage."""
        try:
            # Find device from scanner first
            ble_device = bluetooth.async_ble_device_from_address(self.hass, self.mac_address)
            if not ble_device:
                _LOGGER.error("Could not find BLE device")
                return False

            # Check storage first
            stored_id = await self.read_device_info()
            
            if stored_id is None:
                # No stored ID, need to pair and get factory_reset_id
                _LOGGER.info("No stored Factory Reset ID found, attempting pairing...")
                pairing_success = await self.setup_bluetooth_pairing()
                
                if not pairing_success:
                    _LOGGER.error("Bluetooth pairing failed")
                    return False
                    
                # Get Factory Reset ID from device after pairing
                try:
                    device_id = await self.read_factory_reset_id()
                    if device_id:
                        _LOGGER.info("Got Factory Reset ID from device after pairing")
                        await self.write_device_info(self.mac_address, device_id)
                        stored_id = device_id
                    else:
                        _LOGGER.error("Could not get Factory Reset ID from device")
                        return False
                except Exception as e:
                    _LOGGER.error("Error reading Factory Reset ID from device: %s", e)
                    return False

            await self.ensure_connection()
            
            # Write Factory Reset ID to device
            id_bytes = stored_id.to_bytes(4, byteorder="little")
            await self.client.write_gatt_char(FACTORY_RESET_ID_UUID, id_bytes)
            
            # Read and store model number and device name after successful connection
            self.model_number = await self.read_model_number()
            self.device_name = await self.read_device_name()
            
            _LOGGER.info("Successfully verified Factory Reset ID and read model number")
            return True
                
        except Exception as e:
            _LOGGER.error("Failed to verify Factory Reset ID: %s", e)
            return False

    async def check_if_paired(self) -> bool:
        """Check if device is already paired using bluetoothctl."""
        try:
            process = await asyncio.create_subprocess_exec(
                'bluetoothctl',
                'info',
                self.mac_address,
                stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            output = stdout.decode()
            
            # Device is paired if "Paired: yes" appears in the output
            return "Paired: yes" in output
            
        except Exception as e:
            _LOGGER.error("Error checking pairing status: %s", e)
            return False

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
