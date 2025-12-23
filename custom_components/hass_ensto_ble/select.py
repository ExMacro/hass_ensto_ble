"""Support for Ensto BLE selects."""
import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry

from .base_entity import EnstoBaseEntity
from .const import (
    DOMAIN, SCAN_INTERVAL, FLOOR_SENSOR_TYPE_UUID,
    FLOOR_SENSOR_CONFIG, MODE_MAP, SUPPORTED_MODES_ECO16, SUPPORTED_MODES_ELTE6,
    EXTERNAL_CONTROL_MODES,
)

_LOGGER = logging.getLogger(__name__)

# Reverse mapping for easy lookup
FLOOR_SENSOR_TYPES = {v['sensor_type']: k for k, v in FLOOR_SENSOR_CONFIG.items()}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up selects from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    
    # Always add heating mode select
    selects = [EnstoHeatingModeSelect(manager)]
    
    # Add floor sensor select only for ECO16 models
    model = manager.model_number if manager.model_number else ""
    if "ECO16" in model:
        selects.append(EnstoFloorSensorSelect(manager))
    
    selects.append(EnstoExternalControlModeSelect(manager))
    
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
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the select."""
        super().__init__(manager)  # Call parent class __init__
        self._attr_name = "Heating mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_heating_mode_select"
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
            # Check device model
            model = self._manager.model_number if self._manager.model_number else ""
            # For ELTE6, exclude "Floor" and "Combination" modes
            if "ELTE6" in model:
                allowed_numbers = SUPPORTED_MODES_ELTE6
            else:
                allowed_numbers = SUPPORTED_MODES_ECO16

            self._available_modes = [MODE_MAP[num] for num in sorted(allowed_numbers)]
        return self._available_modes

    async def async_select_option(self, option: str) -> None:
        """
        Change heating mode on the device.
        Args:
            option: One of "Floor", "Room", "Combination", "Power", "Force Control"
        """
        # Find mode number by name
        mode_number = next(num for num, name in MODE_MAP.items() if name == option)
        await self._manager.write_heating_mode(mode_number)
        self._current_mode = option

    async def async_update(self) -> None:
        """Update heating mode."""
        try:
            result = await self._manager.read_heating_mode()
            if result:
                mode_number = result['mode_number']
                if mode_number in MODE_MAP:
                    self._current_mode = MODE_MAP[mode_number]
        except Exception as e:
            _LOGGER.error("Error updating heating mode: %s", e)

class EnstoFloorSensorSelect(EnstoBaseEntity, SelectEntity):
    """Representation of Ensto Floor Sensor Type select."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the select."""
        super().__init__(manager)
        self._attr_name = "Floor sensor type"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_sensor_select"
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
                sensor_broken_limit = int.from_bytes(result[7:9], byteorder='little')
                resistance_25c = int.from_bytes(result[9:11], byteorder='little')
                offset = int.from_bytes(result[11:13], byteorder='little', signed=True) / 10  # Convert to actual decimal value

                # Log all values in debug
                _LOGGER.debug(
                    "Updated %s Floor Sensor for %s: type=%s, resistance=%s, offset=%.1f°C, adc_limits=%d-%d",
                    self._manager.device_name or self._manager.mac_address,
                    self._manager.mac_address,
                    FLOOR_SENSOR_TYPES.get(sensor_type, 'Unknown'),
                    f"{resistance_25c//1000} kΩ" if resistance_25c >= 1000 else f"{resistance_25c}",
                    offset,
                    sensor_broken_limit,
                    sensor_missing_limit
                )

                # Convert sensor type number to string representation
                for name, config in FLOOR_SENSOR_CONFIG.items():
                    if config['sensor_type'] == sensor_type:
                        self._current_type = name
                        break
                
        except Exception as e:
            _LOGGER.error("Error updating floor sensor type: %s", e)

class EnstoExternalControlModeSelect(EnstoBaseEntity, SelectEntity):
    """Select entity for external control mode.

    Allows selecting between:
    - Off: External control disabled (mode 2)
    - Temperature: Set absolute target temperature (mode 5)
    - Temperature change: Set offset from normal target (mode 6)
    """

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the select."""
        super().__init__(manager)
        self._attr_name = "External control mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_external_control_mode"
        self._attr_icon = "mdi:thermostat"
        self._attr_options = list(EXTERNAL_CONTROL_MODES.values())
        self._attr_current_option = None

    @property
    def current_option(self) -> Optional[str]:
        """Return current mode."""
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        """Change external control mode."""
        try:
            current = await self._manager.read_force_control()
            if current:
                # Find mode number by name
                mode = next(
                    num for num, name in EXTERNAL_CONTROL_MODES.items() 
                    if name == option
                )
                await self._manager.write_force_control(
                    mode=mode,
                    temperature=current['temperature'],
                    temperature_offset=current['temperature_offset']
                )
                self._attr_current_option = option
        except Exception as e:
            _LOGGER.error("Failed to set external control mode: %s", e)

    async def async_update(self) -> None:
        """Update external control mode."""
        try:
            result = await self._manager.read_force_control()
            if result:
                self._attr_current_option = result.get('mode_name', 'Off')
        except Exception as e:
            _LOGGER.error("Error updating external control mode: %s", e)