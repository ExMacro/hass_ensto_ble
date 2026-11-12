"""Data update coordinator for Ensto BLE thermostats."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import REAL_TIME_INDICATION_UUID, SCAN_INTERVAL

if TYPE_CHECKING:
    from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# A device that has just powered up can report invalid values (wrong target, floor,
# relay and mode) for about 1.5 s after connecting
CONNECT_SETTLE_SECONDS = 3

# Synchronize the device clock when it differs from Home Assistant by more than this
CLOCK_SYNC_THRESHOLD = timedelta(minutes=1)

# Coordinator data keys
REAL_TIME = "real_time"
BOOST = "boost"
ADAPTIVE_TEMP = "adaptive_temp"
DAYLIGHT_SAVING = "daylight_saving"
VACATION = "vacation"
CALENDAR_MODE = "calendar_mode"
HEATING_MODE = "heating_mode"
FLOOR_SENSOR = "floor_sensor"
FORCE_CONTROL = "force_control"
FLOOR_LIMITS = "floor_limits"
FLOOR_AREA = "floor_area"
ROOM_CALIBRATION = "room_calibration"
HEATING_POWER = "heating_power"
ENERGY_UNIT = "energy_unit"
DATE_TIME = "date_time"


def device_utc(date_time: dict[str, int]) -> datetime | None:
    """Return the device clock as a UTC datetime, None if the values are invalid.

    The device clock runs in UTC; it handles DST and time zone itself.
    """
    try:
        return datetime(
            date_time['year'], date_time['month'], date_time['day'],
            date_time['hour'], date_time['minute'], date_time['second'],
            tzinfo=dt_util.UTC,
        )
    except ValueError:
        return None


class EnstoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read the thermostat once per update for all entities.

    The real-time indication is always read. Other characteristics are read only
    when an enabled entity uses them: entities pass the data keys they use as
    their coordinator context, so disabled entities cause no reads.
    """

    def __init__(self, hass: HomeAssistant, manager: EnstoThermostatManager) -> None:
        """Initialize the coordinator.

        The config entry is not passed explicitly, so that this also works on
        Home Assistant versions before the config_entry argument was added.
        Create the coordinator inside async_setup_entry, where the entry is known.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"Ensto {manager.mac_address}",
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.manager = manager
        self._readers: dict[str, Callable[[], Awaitable[Any]]] = {
            BOOST: manager.read_boost,
            ADAPTIVE_TEMP: manager.read_adaptive_temp_control,
            DAYLIGHT_SAVING: manager.read_daylight_saving,
            VACATION: manager.read_vacation_time,
            CALENDAR_MODE: manager.read_calendar_mode,
            HEATING_MODE: manager.read_heating_mode,
            ROOM_CALIBRATION: manager.read_room_sensor_calibration,
            HEATING_POWER: manager.read_heating_power,
            ENERGY_UNIT: manager.read_energy_unit,
            DATE_TIME: manager.read_date_and_time,
        }
        # Only these models and firmware versions have the characteristic
        if "ECO16" in (manager.model_number or ""):
            self._readers[FLOOR_SENSOR] = manager.read_floor_sensor_config
            self._readers[FLOOR_LIMITS] = manager.read_floor_limits
            self._readers[FLOOR_AREA] = manager.read_floor_area
        if manager.supports_external_control():
            self._readers[FORCE_CONTROL] = manager.read_force_control

    async def _async_update_data(self) -> dict[str, Any]:
        """Connect if needed and read the data the entities use."""
        manager = self.manager

        try:
            await manager.ensure_connection()
        except Exception as err:
            raise UpdateFailed(f"Could not connect: {err}") from err

        connected_at = manager.connected_at
        if connected_at is not None:
            wait = CONNECT_SETTLE_SECONDS - (time.monotonic() - connected_at)
            if wait > 0:
                _LOGGER.debug(
                    "Waiting %.1f s for %s to settle after connecting",
                    wait, manager.mac_address,
                )
                await asyncio.sleep(wait)

        raw_data = await manager._ble_read_split(
            REAL_TIME_INDICATION_UUID, "real-time indication"
        )
        if not raw_data:
            raise UpdateFailed("Could not read real-time data")

        real_time = manager.parse_real_time_indication(raw_data)
        if not real_time:
            raise UpdateFailed("Could not parse real-time data")

        previous = self.data or {}
        data = {**previous, REAL_TIME: real_time}

        # Entities are added after the first refresh, so read everything once.
        # Each entity's context is a tuple of the data keys it uses.
        if self.data is None:
            keys = set(self._readers)
        else:
            keys = set()
            for context in self.async_contexts():
                keys.update(context)
            keys &= set(self._readers)

        for key in keys:
            value = await self._read(key)
            # Keep the previous value if one characteristic fails
            if value is None:
                continue
            if key == DATE_TIME and device_utc(value) is None:
                # Keep showing the previous clock, like the sensor did before
                _LOGGER.error("Error updating datetime: invalid device clock %s", value)
                continue
            data[key] = value
            if key == DATE_TIME:
                await self._sync_clock(data)

        return data

    async def _sync_clock(self, data: dict[str, Any]) -> None:
        """Set the device clock to Home Assistant time if it has drifted.

        A power cut resets the device clock, so this runs whenever the clock is read.
        """
        ha_utc = dt_util.utcnow()
        drift = abs(ha_utc - device_utc(data[DATE_TIME]))
        if drift <= CLOCK_SYNC_THRESHOLD:
            return

        if await self.manager.sync_date_and_time(drift.total_seconds()):
            # The device clock now has Home Assistant time
            data[DATE_TIME] = {
                'year': ha_utc.year, 'month': ha_utc.month, 'day': ha_utc.day,
                'hour': ha_utc.hour, 'minute': ha_utc.minute, 'second': ha_utc.second,
            }

    async def _read(self, key: str) -> Any:
        """Read one characteristic, None on failure."""
        try:
            return await self._readers[key]()
        except Exception as err:
            _LOGGER.debug("Failed to read %s from %s: %s", key, self.manager.mac_address, err)
            return None

    async def async_refresh_key(self, key: str) -> None:
        """Read one characteristic again, e.g. after an entity wrote it."""
        value = await self._read(key)
        if value is not None and self.data is not None:
            self.data[key] = value
            self.async_update_listeners()
