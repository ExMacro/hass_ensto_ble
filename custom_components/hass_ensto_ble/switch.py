"""Support for Ensto BLE switches."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from datetime import datetime
from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL

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
        EnstoCalendarModeSwitch(manager),
        EnstoExternalControlSwitch(manager),
    ]
    async_add_entities(switches, True)

class EnstoBoostSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Boost switch.
    
    Controls temporary temperature boost functionality with configurable
    duration and temperature offset."""
    
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)   # Call parent class __init__
        self._attr_name = "Boost mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_switch"
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
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)  # Call parent class __init__
        self._attr_name = "Adaptive temperature control"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_adaptive_temp_switch"
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
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = "Daylight saving"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_daylight_saving_switch"
        self._is_on = False
        self._additional_info = None

    @property
    def is_on(self) -> bool:
        """Return true if daylight saving is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn daylight saving on."""
        
        # DST ON: Send base timezone (standard time), let device handle DST
        ha_tz = dt_util.DEFAULT_TIME_ZONE
        
        # Get base timezone using January date (ensures standard time)
        # Create January datetime in UTC and convert to local timezone
        january_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt_util.UTC)
        january_local = january_utc.astimezone(ha_tz)
        tz_offset = int(january_local.utcoffset().total_seconds() / 60)
        
        _LOGGER.debug("Action [Daylight Saving Enable] for [%s]: base timezone offset %d minutes", self._manager.mac_address, tz_offset)

        await self._manager.write_daylight_saving(
            enabled=True,
            winter_to_summer=60,  # Standard 1h DST change
            summer_to_winter=60,  # Standard 1h DST change
            timezone_offset=tz_offset
        )
        self._is_on = True
        
        _LOGGER.debug("Action [Daylight Saving Enable] for [%s]: successfully enabled", self._manager.mac_address)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn daylight saving off."""
        
        # DST OFF: Send current timezone (with DST already included)
        ha_tz = dt_util.DEFAULT_TIME_ZONE
        utc_now = dt_util.utcnow()
        
        # Convert current UTC time to local timezone to get current offset
        local_now = utc_now.astimezone(ha_tz)
        tz_offset = int(local_now.utcoffset().total_seconds() / 60)
        
        _LOGGER.debug("Action [Daylight Saving Disable] for [%s]: current timezone offset %d minutes", self._manager.mac_address, tz_offset)

        await self._manager.write_daylight_saving(
            enabled=False,
            winter_to_summer=60,  # Not used when DST disabled but keep consistent
            summer_to_winter=60,  # Not used when DST disabled but keep consistent
            timezone_offset=tz_offset
        )
        self._is_on = False
        
        _LOGGER.debug("Action [Daylight Saving Disable] for [%s]: successfully disabled", self._manager.mac_address)

    async def async_update(self) -> None:
        """Update daylight saving state."""
        try:
            result = await self._manager.read_daylight_saving()
            if result:
                self._is_on = result['enabled']
                self._additional_info = result
                _LOGGER.debug(
                    "Read DST settings %s for %s: enabled=%s, winter_to_summer=%s min, summer_to_winter=%s min, timezone_offset=%s min",
                    self._manager.device_name or "Unknown",
                    self._manager.mac_address,
                    result.get('enabled', False),
                    result.get('winter_to_summer_offset', 0),
                    result.get('summer_to_winter_offset', 0),
                    result.get('timezone_offset', 0)
                )
        except Exception as e:
            _LOGGER.error("Error updating daylight saving state: %s", e)

class EnstoVacationModeSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Vacation Mode switch."""
    
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = "Vacation mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_mode_switch"
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
                    f"ensto_datetime_update_{self._manager.mac_address}"
                )

        except Exception as e:
            _LOGGER.error("Failed to enable vacation mode: %s", e)

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
                    f"ensto_datetime_update_{self._manager.mac_address}"
                )

        except Exception as e:
            _LOGGER.error("Failed to disable vacation mode: %s", e)

    async def async_update(self) -> None:
        """Update vacation mode state."""
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                # Format debug message consistently with other components
                local_from = dt_util.as_local(settings['time_from'])
                local_to = dt_util.as_local(settings['time_to'])
                _LOGGER.debug(
                    "Updated %s Vacation Mode for %s: enabled=%s, from=%s, to=%s, active=%s",
                    self._manager.device_name or self._manager.mac_address,
                    self._manager.mac_address,
                    settings.get('enabled', False),
                    local_from.strftime('%Y-%m-%d %H:%M:%S'),
                    local_to.strftime('%Y-%m-%d %H:%M:%S'),
                    settings.get('active', False)
                )

                self._is_on = settings.get('enabled', False)
        except Exception as e:
            _LOGGER.error("Error updating vacation mode state: %s", e)

class EnstoCalendarModeSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto Calendar Mode switch."""
    
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = "Calendar mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_calendar_mode_switch"
        self._attr_icon = "mdi:calendar-clock"
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Return true if calendar mode is active."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn calendar mode on."""
        try:
            success = await self._manager.write_calendar_mode(True)
            if success:
                self._is_on = True
        except Exception as e:
            _LOGGER.error("Failed to enable calendar mode: %s", e)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn calendar mode off."""
        try:
            success = await self._manager.write_calendar_mode(False)
            if success:
                self._is_on = False
        except Exception as e:
            _LOGGER.error("Failed to disable calendar mode: %s", e)

    async def async_update(self) -> None:
        """Update calendar mode state."""
        try:
            result = await self._manager.read_calendar_mode()
            if result:
                self._is_on = result['enabled']
        except Exception as e:
            _LOGGER.error("Error updating calendar mode state: %s", e)

class EnstoExternalControlSwitch(EnstoBaseEntity, SwitchEntity):
    """Representation of Ensto External Control switch."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the switch."""
        super().__init__(manager)
        self._attr_name = "External control"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_external_control_switch"
        self._attr_icon = "mdi:remote"
        self._is_on = False
        self._current_settings = None

    @property
    def is_on(self) -> bool:
        """Return true if external control is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Turn external control on."""
        try:
            self._current_settings = await self._manager.read_force_control()
            if self._current_settings:
                await self._manager.write_force_control(
                    enabled=True,
                    mode=self._current_settings.get('mode', 6),
                    temperature=self._current_settings.get('temperature', 20.0),
                    temperature_offset=self._current_settings.get('temperature_offset', 5.0)
                )
                self._is_on = True
        except Exception as e:
            _LOGGER.error("Failed to enable external control: %s", e)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn external control off."""
        try:
            self._current_settings = await self._manager.read_force_control()
            if self._current_settings:
                await self._manager.write_force_control(
                    enabled=False,
                    mode=self._current_settings.get('mode', 6),
                    temperature=self._current_settings.get('temperature', 20.0),
                    temperature_offset=self._current_settings.get('temperature_offset', 5.0)
                )
                self._is_on = False
        except Exception as e:
            _LOGGER.error("Failed to disable external control: %s", e)

    async def async_update(self) -> None:
        """Update external control state."""
        try:
            self._current_settings = await self._manager.read_force_control()
            if self._current_settings:
                self._is_on = self._current_settings.get('enabled', False)
        except Exception as e:
            _LOGGER.error("Error updating external control state: %s", e)
