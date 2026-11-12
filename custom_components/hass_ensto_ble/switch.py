"""Support for Ensto BLE switches."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from datetime import datetime
from .base_entity import EnstoCoordinatorEntity
from .coordinator import (
    ADAPTIVE_TEMP,
    BOOST,
    CALENDAR_MODE,
    DAYLIGHT_SAVING,
    VACATION,
)

from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

# One write at a time, so read-modify-write actions don't overwrite each other
PARALLEL_UPDATES = 1

async def async_setup_entry(
    hass: HomeAssistant,  # Home Assistant instance
    entry: EnstoConfigEntry,   # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback  # Callback to register new entities
) -> None:
    """Set up switches from a config entry."""
    coordinator = entry.runtime_data.coordinator

    async_add_entities([
        EnstoBoostSwitch(coordinator),
        EnstoAdaptiveTempSwitch(coordinator),
        EnstoDaylightSavingSwitch(coordinator),
        EnstoVacationModeSwitch(coordinator),
        EnstoCalendarModeSwitch(coordinator),
    ])

class EnstoCoordinatorSwitch(EnstoCoordinatorEntity, SwitchEntity):
    """Base class for switches that show a value read by the coordinator."""

class EnstoBoostSwitch(EnstoCoordinatorSwitch):
    """Representation of Ensto Boost switch.

    Controls temporary temperature boost functionality with configurable
    duration and temperature offset."""

    _data_key = BOOST

    def __init__(self, coordinator):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_name = "Boost mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_switch"

    @property
    def is_on(self) -> bool:
        """Return true if boost mode is active, raising temperature temporarily."""
        boost = self._value
        return boost['enabled'] and boost['remaining_minutes'] != 0

    async def _async_set_boost(self, enabled: bool) -> None:
        """Enable or disable boost, keeping the other boost settings."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_boost()
            if settings:
                await self._manager.write_boost(
                    enabled=enabled,
                    offset_degrees=settings['offset_degrees'],
                    offset_percentage=settings['offset_percentage'],
                    duration_minutes=settings['setpoint_minutes']
                )
        except Exception as e:
            _LOGGER.error("Failed to %s boost mode: %s", "enable" if enabled else "disable", e)
        await self._async_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the boost on."""
        await self._async_set_boost(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the boost off."""
        await self._async_set_boost(False)

class EnstoAdaptiveTempSwitch(EnstoCoordinatorSwitch):
    """Representation of Ensto Adaptive Temperature Control switch."""

    _data_key = ADAPTIVE_TEMP

    def __init__(self, coordinator):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_name = "Adaptive temperature control"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_adaptive_temp_switch"

    @property
    def is_on(self) -> bool:
        """Return true if adaptive temperature control is active (auto-adjusts based on conditions)."""
        return self._value['enabled']

    async def async_turn_on(self, **kwargs) -> None:
        """Turn adaptive temperature control on."""
        await self._manager.write_adaptive_temp_control(True)
        await self._async_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn adaptive temperature control off."""
        await self._manager.write_adaptive_temp_control(False)
        await self._async_refresh()

class EnstoDaylightSavingSwitch(EnstoCoordinatorSwitch):
    """Representation of Ensto Daylight Saving switch."""

    _data_key = DAYLIGHT_SAVING

    def __init__(self, coordinator):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_name = "Daylight saving"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_daylight_saving_switch"

    @property
    def is_on(self) -> bool:
        """Return true if daylight saving is enabled."""
        return self._value['enabled']

    async def _async_set_daylight_saving(self, enabled: bool) -> None:
        """Enable or disable daylight saving."""
        # Send base timezone (standard time) like the Ensto app does, the device
        # adds the DST offset itself. The device stores the offset as int8, so
        # the summer offset (180) would not fit.
        # Get base timezone using January date (ensures standard time)
        ha_tz = dt_util.DEFAULT_TIME_ZONE
        january_utc = datetime(2025, 1, 15, 12, 0, 0, tzinfo=dt_util.UTC)
        january_local = january_utc.astimezone(ha_tz)
        tz_offset = int(january_local.utcoffset().total_seconds() / 60)

        action = "Enable" if enabled else "Disable"
        _LOGGER.debug("Action [Daylight Saving %s] for [%s]: base timezone offset %d minutes",
                      action, self._manager.mac_address, tz_offset)

        if await self._manager.write_daylight_saving(
            enabled=enabled,
            winter_to_summer=0,  # Ensto app writes 0, device does not store it
            summer_to_winter=0,
            timezone_offset=tz_offset
        ):
            _LOGGER.debug("Action [Daylight Saving %s] for [%s]: success",
                          action, self._manager.mac_address)
        await self._async_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn daylight saving on."""
        await self._async_set_daylight_saving(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn daylight saving off."""
        await self._async_set_daylight_saving(False)

class EnstoVacationModeSwitch(EnstoCoordinatorSwitch):
    """Representation of Ensto Vacation Mode switch."""

    _data_key = VACATION

    def __init__(self, coordinator):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_name = "Vacation mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_mode_switch"
        self._attr_icon = "mdi:palm-tree"

    @property
    def is_on(self) -> bool:
        """Return true if vacation mode is active."""
        return self._value.get('enabled', False)

    async def _async_set_vacation(self, enabled: bool) -> None:
        """Enable or disable vacation mode, keeping the vacation settings."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_vacation_time()
            if settings:
                await self._manager.write_vacation_time(
                    time_from=settings['time_from'],
                    time_to=settings['time_to'],
                    offset_temperature=settings['offset_temperature'],
                    offset_percentage=settings['offset_percentage'],
                    enabled=enabled
                )
        except Exception as e:
            _LOGGER.error("Failed to %s vacation mode: %s", "enable" if enabled else "disable", e)
        await self._async_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn vacation mode on."""
        await self._async_set_vacation(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn vacation mode off."""
        await self._async_set_vacation(False)

class EnstoCalendarModeSwitch(EnstoCoordinatorSwitch):
    """Representation of Ensto Calendar Mode switch."""

    _data_key = CALENDAR_MODE

    def __init__(self, coordinator):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_name = "Calendar mode"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_calendar_mode_switch"
        self._attr_icon = "mdi:calendar-clock"

    @property
    def is_on(self) -> bool:
        """Return true if calendar mode is active."""
        return self._value['enabled']

    async def _async_set_calendar_mode(self, enabled: bool) -> None:
        """Enable or disable calendar mode."""
        try:
            await self._manager.write_calendar_mode(enabled)
        except Exception as e:
            _LOGGER.error("Failed to %s calendar mode: %s", "enable" if enabled else "disable", e)
        await self._async_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn calendar mode on."""
        await self._async_set_calendar_mode(True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn calendar mode off."""
        await self._async_set_calendar_mode(False)
