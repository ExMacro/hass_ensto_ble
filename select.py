"""Support for Ensto BLE selects."""
import logging
from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Map display names to device mode numbers
# These values are used to convert between user-friendly display names
# and the actual numeric values used by the device protocol
MODE_MAP = {
    "Floor": 1,        # Floor sensor based heating (ECO16 only)
    "Room": 2,         # Room sensor based heating
    "Combination": 3,  # Combined floor and room (ECO16 only)
    "Power": 4,        # Direct power control
    "Force Control": 5 # Manual control mode
}
# Reverse mapping for easy lookup
MODE_MAP_REVERSE = {v: k for k, v in MODE_MAP.items()}

async def async_setup_entry(
    hass: HomeAssistant,  # Home Assistant instance
    entry: ConfigEntry,   # Config entry containing device info like MAC
    async_add_entities: AddEntitiesCallback  # Callback to register entities
) -> None:
    """Set up selects from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]

    selects = [
        EnstoHeatingModeSelect(manager),
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
