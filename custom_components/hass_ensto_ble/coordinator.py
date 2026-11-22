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
from .exceptions import EnstoBleError

if TYPE_CHECKING:
    from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# A device that has just powered up can report invalid values (wrong target, floor,
# relay and mode) for about 1.5 s after connecting
CONNECT_SETTLE_SECONDS = 3

# Synchronize the device clock when it differs from Home Assistant by more than this
CLOCK_SYNC_THRESHOLD = timedelta(minutes=1)

# The device updates its history once an hour; read it this long after the full hour
HISTORY_READ_DELAY = timedelta(minutes=5)

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
POWER_CONSUMPTION = "power_consumption"
MONITORING = "monitoring"


def _utc_offsets() -> tuple[int, int]:
    """Return Home Assistant's UTC offsets in January and July, in minutes."""
    year = dt_util.utcnow().year
    return tuple(
        int(datetime(year, month, 15, 12, tzinfo=dt_util.UTC)
            .astimezone(dt_util.DEFAULT_TIME_ZONE).utcoffset().total_seconds() // 60)
        for month in (1, 7)
    )


def standard_utc_offset() -> int:
    """Return Home Assistant's standard time UTC offset in minutes, e.g. 120 for Finland.

    The thermostat stores this offset and adds the summer hour itself when
    automatic daylight saving is on, the same way the Ensto app sets it up.
    """
    return min(_utc_offsets())


def has_daylight_saving() -> bool:
    """Return True if Home Assistant's time zone has summer time."""
    january, july = _utc_offsets()
    return january != july


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
        # One operation at a time: an update reading the device, or an action
        # writing and reading back. Otherwise an update that read a value before
        # a write would put the old value back when it finishes.
        self.lock = asyncio.Lock()
        # Connection on which the time zone was last checked, see _check_time_zone()
        self._time_zone_checked_at: float | None = None
        # True after warning that automatic daylight saving is off
        self._dst_off_warned = False
        # Hour of the last successful monitoring data read, None until the first read
        self._history_hour: datetime | None = None
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
            POWER_CONSUMPTION: manager.read_power_consumption,
            MONITORING: manager.read_monitoring_data,
        }
        # Only these models and firmware versions have the characteristic
        model = manager.model_number or ""
        if "ECO16" in model or "ECO10" in model:
            self._readers[FLOOR_SENSOR] = manager.read_floor_sensor_config
            self._readers[FLOOR_AREA] = manager.read_floor_area
        # Floor limits are used only in the combination mode, which ECO10 does not have
        if "ECO16" in model:
            self._readers[FLOOR_LIMITS] = manager.read_floor_limits
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

        # Connecting stays outside the lock, so actions don't wait for a long
        # connection attempt. Home Assistant stores the returned data before an
        # action waiting for the lock can run, so the action reads back into it.
        async with self.lock:
            return await self._read_data()

    async def _read_data(self) -> dict[str, Any]:
        """Read the real-time data and the characteristics the entities use.

        Returns:
            The new coordinator data.

        Raises:
            UpdateFailed: The real-time data could not be read.
        """
        manager = self.manager

        try:
            raw_data = await manager._ble_read_split(
                REAL_TIME_INDICATION_UUID, "real-time indication"
            )
        except EnstoBleError as err:
            raise UpdateFailed(str(err)) from err
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

        # Monitoring data is large, so read it only once an hour
        history_hour = (dt_util.now() - HISTORY_READ_DELAY).replace(minute=0, second=0, microsecond=0)
        if history_hour == self._history_hour:
            keys.discard(MONITORING)

        read_failed = False
        for key in keys:
            try:
                value = await self._read(key)
            except EnstoBleError as err:
                # A failed read drops the connection, so the remaining reads would
                # fail too. Keep the previous values; the next update reconnects.
                _LOGGER.debug(
                    "Stopping update of %s: %s", manager.mac_address, err
                )
                read_failed = True
                break
            # Keep the previous value if the device returned invalid data
            if value is None:
                continue
            if key == DATE_TIME and device_utc(value) is None:
                # Keep showing the previous clock, like the sensor did before
                _LOGGER.error("Error updating datetime: invalid device clock %s", value)
                continue
            if key == POWER_CONSUMPTION and not value['measurements']:
                # Keep the previous power usage when the device returns no measurements
                continue
            data[key] = value
            if key == DATE_TIME:
                await self._sync_clock(data)
            elif key == MONITORING:
                self._history_hour = history_hour

        if not read_failed and manager.connected_at != self._time_zone_checked_at:
            await self._check_time_zone(data)

        return data

    async def _check_time_zone(self, data: dict[str, Any]) -> None:
        """Keep the thermostat's time zone offset at Home Assistant's standard offset.

        The thermostat runs schedules and stores history in its own local time:
        UTC + the stored offset, plus one hour in summer when automatic daylight
        saving is on. The integration reads and writes those times as Home
        Assistant local time, so the offset must match. Versions up to v0.5.7
        could leave the summer offset (180 min for Finland) with automatic
        daylight saving off, which puts the thermostat an hour ahead in winter.

        Checked once per connection: only a write changes the offset, and the
        Ensto app can write only while Home Assistant is disconnected.

        Args:
            data: Coordinator data being built; the daylight saving settings
                are stored in it.
        """
        manager = self.manager
        device = manager.device_name or "Unknown Device"
        try:
            config = await manager.read_daylight_saving()
        except EnstoBleError as err:
            _LOGGER.debug("Could not check time zone of %s: %s", manager.mac_address, err)
            return
        if config is None:
            return

        expected = standard_utc_offset()
        if config['timezone_offset'] != expected:
            try:
                await manager.write_daylight_saving(
                    enabled=config['enabled'],
                    winter_to_summer=0,  # Ensto app writes 0, device does not store it
                    summer_to_winter=0,
                    timezone_offset=expected,
                )
            except EnstoBleError as err:
                _LOGGER.debug("Could not correct time zone of %s: %s", manager.mac_address, err)
                return
            _LOGGER.info(
                "Corrected time zone offset on %s (%s) from %d to %d min",
                device, manager.mac_address, config['timezone_offset'], expected,
            )
            config = {
                **config,
                'winter_to_summer_offset': 0,
                'summer_to_winter_offset': 0,
                'timezone_offset': expected,
            }
        data[DAYLIGHT_SAVING] = config
        self._time_zone_checked_at = manager.connected_at

        # Automatic daylight saving is the user's choice, as in the Ensto app
        if not config['enabled'] and has_daylight_saving():
            if not self._dst_off_warned:
                _LOGGER.warning(
                    "Automatic daylight saving is off on %s (%s): in summer its "
                    "schedules and history are 1 h off from Home Assistant time",
                    device, manager.mac_address,
                )
                self._dst_off_warned = True
        else:
            self._dst_off_warned = False

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
        """Read one characteristic.

        Args:
            key: Data key of the characteristic, e.g. BOOST.

        Returns:
            The value, or None if the device returned invalid data.

        Raises:
            EnstoBleError: The read failed.
        """
        try:
            return await self._readers[key]()
        except EnstoBleError:
            raise
        except Exception as err:
            _LOGGER.debug("Failed to read %s from %s: %s", key, self.manager.mac_address, err)
            return None

    async def async_refresh_key(self, key: str) -> None:
        """Read one characteristic again, e.g. after an entity wrote it.

        A failed read keeps the previous value; the next update reads it again.
        """
        try:
            value = await self._read(key)
        except EnstoBleError as err:
            _LOGGER.debug("Failed to read %s again from %s: %s", key, self.manager.mac_address, err)
            return
        if value is not None and self.data is not None:
            self.data[key] = value
            self.async_update_listeners()
