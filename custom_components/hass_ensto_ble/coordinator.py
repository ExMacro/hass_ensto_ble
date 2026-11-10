"""Data update coordinator for Ensto BLE thermostats."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import REAL_TIME_INDICATION_UUID, SCAN_INTERVAL

if TYPE_CHECKING:
    from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# A device that has just powered up can report invalid values (wrong target, floor,
# relay and mode) for about 1.5 s after connecting
CONNECT_SETTLE_SECONDS = 3


class EnstoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Read the thermostat once per update for all entities."""

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

    async def _async_update_data(self) -> dict[str, Any]:
        """Connect if needed and read the real-time indication."""
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

        parsed = manager.parse_real_time_indication(raw_data)
        if not parsed:
            raise UpdateFailed("Could not parse real-time data")

        return parsed
