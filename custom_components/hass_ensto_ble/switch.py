"""Support for Ensto BLE switches."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL, SIGNAL_DATETIME_UPDATE

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,  # Home Assistant instance
    entry: ConfigEntry,   # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback  # Callback to register new entities
) -> None:
    """Set up switches from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]

    switches = [
        EnstoBoostSwitch(manager),
        EnstoAdaptiveTempSwitch(manager),
        EnstoDaylightSavingSwitch(manager),
        EnstoVacationModeSwitch(manager),
    ]
    async_add_entities(switches, True)

class EnstoBoostSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Boost switch.
    
    Controls temporary temperature boost functionality with configurable
    duration and temperature offset."""
    
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)   # Call parent class __init__
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Boost Mode"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_boost_switch"
        self._is_on = False
        self._boost_settings = None

    @property
    def is_on(self) -> bool:
        """Return true if boost mode is active, raising temperature temporarily."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
       """Turn the boost on."""
       try:
           self._boost_settings = await self._manager.read_boost()
           if self._boost_settings:
               await self._manager.write_boost(
                   enabled=True,
                   offset_degrees=self._boost_settings['offset_degrees'],
                   offset_percentage=self._boost_settings['offset_percentage'],
                   duration_minutes=self._boost_settings['setpoint_minutes']
               )
               self._is_on = True
       except Exception as e:
           _LOGGER.error("Failed to enable boost mode: %s", e)

    async def async_turn_off(self, **kwargs) -> None:
       """Turn the boost off."""
       try:
           self._boost_settings = await self._manager.read_boost()
           if self._boost_settings:
               await self._manager.write_boost(
                   enabled=False,
                   offset_degrees=self._boost_settings['offset_degrees'],
                   offset_percentage=self._boost_settings['offset_percentage'],
                   duration_minutes=self._boost_settings['setpoint_minutes']
               )
               self._is_on = False
       except Exception as e:
           _LOGGER.error("Failed to disable boost mode: %s", e)

    async def async_update(self) -> None:
        """Update boost state."""
        try:
            self._boost_settings = await self._manager.read_boost()
            if self._boost_settings:
                self._is_on = self._boost_settings['enabled']
                # Check for remaining minutes
                if self._boost_settings['remaining_minutes'] == 0:
                    self._is_on = False
        except Exception as e:
            _LOGGER.error("Error updating boost state: %s", e)

class EnstoAdaptiveTempSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Adaptive Temperature Control switch."""
    
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)  # Call parent class __init__
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Adaptive Temperature Control"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_adaptive_temp_switch"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return true if adaptive temperature control is active (auto-adjusts based on conditions)."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn adaptive temperature control on."""
        await self._manager.write_adaptive_temp_control(True)
        self._is_on = True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn adaptive temperature control off."""
        await self._manager.write_adaptive_temp_control(False)
        self._is_on = False

    async def async_update(self) -> None:
        """Update adaptive temperature control state."""
        try:
            result = await self._manager.read_adaptive_temp_control()
            if result:
                self._is_on = result['enabled']
        except Exception as e:
            _LOGGER.error("Error updating adaptive temperature control state: %s", e)

class EnstoDaylightSavingSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Daylight Saving switch."""
    
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Daylight Saving"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_daylight_saving_switch"
        self._is_on = False
        self._additional_info = None

    @property
    def is_on(self) -> bool:
        """Return true if daylight saving is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn daylight saving on."""
        # Get timezone info from HA
        ha_tz = dt_util.DEFAULT_TIME_ZONE
        tz_offset = int(ha_tz.utcoffset(dt_util.utcnow()).total_seconds() / 60)

        await self._manager.write_daylight_saving(
            enabled=True,
            winter_to_summer=60,  # Standard 1h DST change
            summer_to_winter=60,  # Standard 1h DST change
            timezone_offset=tz_offset
        )
        self._is_on = True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn daylight saving off."""
        # Get timezone info from HA
        ha_tz = dt_util.DEFAULT_TIME_ZONE
        tz_offset = int(ha_tz.utcoffset(dt_util.utcnow()).total_seconds() / 60)

        await self._manager.write_daylight_saving(
            enabled=False,
            winter_to_summer=60,  # Standard 1h DST change
            summer_to_winter=60,  # Standard 1h DST change
            timezone_offset=tz_offset
        )
        self._is_on = False

    async def async_update(self) -> None:
        """Update daylight saving state."""
        try:
            result = await self._manager.read_daylight_saving()
            if result:
                self._is_on = result['enabled']
                self._additional_info = result
        except Exception as e:
            _LOGGER.error("Error updating daylight saving state: %s", e)

class EnstoVacationModeSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Vacation Mode switch."""
    
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Vacation Mode"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_vacation_mode_switch"
        self._attr_icon = "mdi:palm-tree"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return true if vacation mode is active."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn vacation mode on."""
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                await self._manager.write_vacation_time(
                    time_from=settings['time_from'],
                    time_to=settings['time_to'],
                    offset_temperature=settings['offset_temperature'],
                    offset_percentage=settings['offset_percentage'],
                    enabled=True
                )
                self._is_on = True
                
                # Notify datetime entities to update
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_DATETIME_UPDATE.format(self._manager.mac_address)
                )
                
        except Exception as e:
            _LOGGER.error(f"Failed to enable vacation mode: {e}")

    async def async_turn_off(self, **kwargs) -> None:
        """Turn vacation mode off."""
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                await self._manager.write_vacation_time(
                    time_from=settings['time_from'],
                    time_to=settings['time_to'],
                    offset_temperature=settings['offset_temperature'],
                    offset_percentage=settings['offset_percentage'],
                    enabled=False
                )
                self._is_on = False
                
                # Notify datetime entities to update
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_DATETIME_UPDATE.format(self._manager.mac_address)
                )
                
        except Exception as e:
            _LOGGER.error(f"Failed to disable vacation mode: {e}")

    async def async_update(self) -> None:
        """Update vacation mode state."""
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                # Add debug logging here
                local_from = dt_util.as_local(settings['time_from'])
                local_to = dt_util.as_local(settings['time_to'])
                _LOGGER.debug(
                    "Vacation mode settings: raw=%s, from=%s, to=%s, active=%s",
                    settings.get('raw_data', ''),
                    local_from.strftime('%Y-%m-%d %H:%M:%S'),
                    local_to.strftime('%Y-%m-%d %H:%M:%S'),
                    settings.get('active', False)
                )
                
                self._is_on = settings.get('enabled', False)
        except Exception as e:
            _LOGGER.error(f"Error updating vacation mode state: {e}")
