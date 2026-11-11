"""Support for Ensto BLE selects."""
import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr

from .base_entity import EnstoCoordinatorEntity
from .const import (
    FLOOR_SENSOR_CONFIG, MODE_MAP, SUPPORTED_MODES_ECO16, SUPPORTED_MODES_ELTE6,
    EXTERNAL_CONTROL_MODES,
)
from .coordinator import FLOOR_SENSOR, FORCE_CONTROL, HEATING_MODE

from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

# Reverse mapping for easy lookup
FLOOR_SENSOR_TYPES = {v['sensor_type']: k for k, v in FLOOR_SENSOR_CONFIG.items()}

async def async_setup_entry(
    hass: HomeAssistant, # Home Assistant instance
    entry: EnstoConfigEntry, # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback # Callback to register new entities
) -> None:
    """Set up selects from a config entry."""
    manager = entry.runtime_data
    coordinator = manager.coordinator

    # Always add heating mode select
    selects = [EnstoHeatingModeSelect(coordinator)]

    # Add floor sensor select only for ECO16 models
    model = manager.model_number if manager.model_number else ""
    if "ECO16" in model:
        selects.append(EnstoFloorSensorSelect(coordinator))

    # Add external control mode select only for firmware 1.14+
    if manager.supports_external_control():
        selects.append(EnstoExternalControlModeSelect(coordinator))

    async_add_entities(selects)

class EnstoHeatingModeSelect(EnstoCoordinatorEntity, SelectEntity):
    """Representation of Ensto Heating Mode select.

    Allows selection of heating modes:
    - Floor: Floor sensor based heating (ECO16 only)
    - Room: Room sensor based heating
    - Combination: Combined floor and room sensors (ECO16 only)
    - Power: Direct power control
    - Force Control: Manual control mode
    """

    _data_key = HEATING_MODE

    def __init__(self, coordinator):
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_name = "Heating mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_heating_mode_select"

        # ELTE6 has no floor sensor, so "Floor" and "Combination" are excluded
        model = self._manager.model_number if self._manager.model_number else ""
        if "ELTE6" in model:
            allowed_numbers = SUPPORTED_MODES_ELTE6
        else:
            allowed_numbers = SUPPORTED_MODES_ECO16
        self._attr_options = [MODE_MAP[num] for num in sorted(allowed_numbers)]

    @property
    def current_option(self) -> Optional[str]:
        """Return current heating mode."""
        return MODE_MAP.get(self._value['mode_number'])

    async def async_select_option(self, option: str) -> None:
        """
        Change heating mode on the device.
        Args:
            option: One of "Floor", "Room", "Combination", "Power", "Force Control"
        """
        # Find mode number by name
        mode_number = next(num for num, name in MODE_MAP.items() if name == option)
        await self._manager.write_heating_mode(mode_number)
        await self._async_refresh()

class EnstoFloorSensorSelect(EnstoCoordinatorEntity, SelectEntity):
    """Representation of Ensto Floor Sensor Type select."""

    _data_key = FLOOR_SENSOR

    def __init__(self, coordinator):
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_name = "Floor sensor type"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_sensor_select"
        self._attr_options = list(FLOOR_SENSOR_CONFIG.keys())

    @property
    def current_option(self) -> Optional[str]:
        """Return current floor sensor type."""
        return FLOOR_SENSOR_TYPES.get(self._value['sensor_type'])

    async def async_select_option(self, option: str) -> None:
        """Change floor sensor type."""
        try:
            if option in FLOOR_SENSOR_CONFIG:
                # Write configuration to device
                if await self._manager.write_floor_sensor_config(FLOOR_SENSOR_CONFIG[option]):
                    _LOGGER.debug("Floor sensor configuration successfully changed.")
        except Exception as e:
            _LOGGER.error("Error setting floor sensor type: %s", e)
        await self._async_refresh()

class EnstoExternalControlModeSelect(EnstoCoordinatorEntity, SelectEntity):
    """Select entity for external control mode.

    Allows selecting between:
    - Off: External control disabled (mode 2)
    - Temperature: Set absolute target temperature (mode 5)
    - Temperature change: Set offset from normal target (mode 6)
    """

    _data_key = FORCE_CONTROL

    def __init__(self, coordinator):
        """Initialize the select."""
        super().__init__(coordinator)
        self._attr_name = "External control mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_external_control_mode"
        self._attr_icon = "mdi:thermostat"
        self._attr_options = list(EXTERNAL_CONTROL_MODES.values())

    @property
    def current_option(self) -> Optional[str]:
        """Return current mode."""
        return self._value.get('mode_name', 'Off')

    async def async_select_option(self, option: str) -> None:
        """Change external control mode."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
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
        except Exception as e:
            _LOGGER.error("Failed to set external control mode: %s", e)
        await self._async_refresh()
