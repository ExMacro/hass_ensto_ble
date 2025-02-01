"""Support for Ensto BLE selects."""
import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL, FLOOR_SENSOR_TYPE_UUID, FLOOR_SENSOR_CONFIG

_LOGGER = logging.getLogger(__name__)

# Map display names to device mode numbers
# These values are used to convert between user-friendly display names
# and the actual numeric values used by the device protocol
MODE_MAP = {
    "Floor": 1,        # Floor sensor based heating (ECO16 only)
    "Room": 2,         # Room sensor based heating
    "Combination": 3,  # Combined floor and room (ECO16 only)
    "Power": 4,        # Direct power control
    "Force Control": 5 # Manual control mode (not in Ensto app)
}
# Reverse mapping for easy lookup
MODE_MAP_REVERSE = {v: k for k, v in MODE_MAP.items()}
FLOOR_SENSOR_TYPES = {v['sensor_type']: k for k, v in FLOOR_SENSOR_CONFIG.items()}

async def async_setup_entry(
    hass: HomeAssistant,  # Home Assistant instance
    entry: ConfigEntry,   # Config entry containing device info like MAC
    async_add_entities: AddEntitiesCallback  # Callback to register entities
) -> None:
    """Set up selects from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]

    selects = [
        EnstoHeatingModeSelect(manager),
        EnstoFloorSensorSelect(manager),
    ]
    async_add_entities(selects, True)

class EnstoHeatingModeSelect(EnstoBaseEntity, SelectEntity):
    """Representation of Ensto Heating Mode select.
    
    Allows selection of heating modes:
    - Floor: Floor sensor based heating (ECO16 only)
    - Room: Room sensor based heating
    - Combination: Combined floor and room sensors (ECO16 only)
    - Power: Direct power control
    - Force Control: Manual control mode
    """

    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the select."""
        super().__init__(manager)  # Call parent class __init__
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Heating Mode"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_heating_mode_select"
        self._current_mode = None
        self._available_modes = None

    @property
    def current_option(self) -> Optional[str]:
        """Return current heating mode."""
        return self._current_mode

    @property
    def options(self) -> list[str]:
        """Return list of available heating modes."""
        if self._available_modes is None:
            return list(MODE_MAP.keys())
        return self._available_modes

    async def async_select_option(self, option: str) -> None:
        """
        Change heating mode on the device.
        Args:
            option: One of "Floor", "Room", "Combination", "Power", "Force Control"
        """
        if option in MODE_MAP:
            mode_number = MODE_MAP[option]
            await self._manager.write_heating_mode(mode_number)
            self._current_mode = option

    async def async_update(self) -> None:
        """Update heating mode."""
        try:
            result = await self._manager.read_heating_mode()
            if result:
                mode_number = result['mode_number']
                if mode_number in MODE_MAP_REVERSE:
                    self._current_mode = MODE_MAP_REVERSE[mode_number]
                
                # Update available modes based on device type
                if result['device_type'] == 'ELTE6':
                    self._available_modes = ["Room", "Power", "Force Control"]
                else:  # ECO16 or unknown
                    self._available_modes = list(MODE_MAP.keys())
                    
        except Exception as e:
            _LOGGER.error("Error updating heating mode: %s", e)

class EnstoFloorSensorSelect(EnstoBaseEntity, SelectEntity):
    """Representation of Ensto Floor Sensor Type select."""

    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the select."""
        super().__init__(manager)
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Floor Sensor Type"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_floor_sensor_select"
        self._current_type = None

    @property
    def current_option(self) -> Optional[str]:
        """Return current floor sensor type."""
        return self._current_type

    @property
    def options(self) -> list[str]:
        """Return list of available floor sensor types."""
        return list(FLOOR_SENSOR_CONFIG.keys())

    async def async_select_option(self, option: str) -> None:
       """Change floor sensor type."""
       try:
           if option in FLOOR_SENSOR_CONFIG:
               # Read current configuration first
               current_config = await self._manager.client.read_gatt_char(FLOOR_SENSOR_TYPE_UUID)

               params = FLOOR_SENSOR_CONFIG[option]
               
               # Create new configuration
               new_config = bytearray(13)
               new_config[0] = params["sensor_type"]
               new_config[1:3] = params["sensor_missing_limit"].to_bytes(2, byteorder='little')
               new_config[3:5] = params["sensor_b_value"].to_bytes(2, byteorder='little')
               new_config[5:7] = params["pull_up_resistor"].to_bytes(2, byteorder='little')
               new_config[7:9] = params["sensor_broken_limit"].to_bytes(2, byteorder='little')
               new_config[9:11] = params["resistance_25c"].to_bytes(2, byteorder='little')
               new_config[11:13] = params["offset"].to_bytes(2, byteorder='little', signed=True)
               
               # Write configuration to device
               await self._manager.client.write_gatt_char(
                   FLOOR_SENSOR_TYPE_UUID,
                   new_config,
                   response=True
               )

               # Log successful configuration change
               _LOGGER.debug(
                   "Floor sensor configuration successfully changed."
               )
               
               self._current_type = option
                       
       except Exception as e:
           _LOGGER.error("Error setting floor sensor type: %s", e)

    async def async_update(self) -> None:
        """Update floor sensor type."""
        try:
            result = await self._manager.client.read_gatt_char(FLOOR_SENSOR_TYPE_UUID)
            if result:
                # Parse all values
                sensor_type = result[0]
                sensor_missing_limit = int.from_bytes(result[1:3], byteorder='little')
                sensor_b_value = int.from_bytes(result[3:5], byteorder='little')
                pull_up_resistor = int.from_bytes(result[5:7], byteorder='little')
                sensor_broken_limit = int.from_bytes(result[7:9], byteorder='little')
                resistance_25c = int.from_bytes(result[9:11], byteorder='little')
                offset = int.from_bytes(result[11:13], byteorder='little', signed=True) / 10  # Convert to actual decimal value

                # Log all values in debug
                _LOGGER.debug(
                    "Floor sensor configuration:"
                    f"\n  Sensor Type: {sensor_type} ({FLOOR_SENSOR_TYPES.get(sensor_type, 'Unknown')})"
                    f"\n  Sensor Missing Limit ADC: {sensor_missing_limit}"
                    f"\n  Sensor B Value: {sensor_b_value}"
                    f"\n  Pull-Up Resistor: {pull_up_resistor}"
                    f"\n  Sensor Broken Limit ADC: {sensor_broken_limit}"
                    f"\n  Resistance at 25C: {resistance_25c}"
                    f"\n  Offset: {offset}"
                )

                # Convert sensor type number to string representation
                for name, config in FLOOR_SENSOR_CONFIG.items():
                    if config['sensor_type'] == sensor_type:
                        self._current_type = name
                        break
                
        except Exception as e:
            _LOGGER.error("Error updating floor sensor type: %s", e)
