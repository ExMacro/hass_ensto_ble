import asyncio
import time
import logging
from .const import REAL_TIME_INDICATION_UUID

LOGGER = logging.getLogger(__name__)

# A device that has just powered up can report invalid values (wrong target, floor,
# relay and mode) for about 1.5 s after connecting
CONNECT_SETTLE_SECONDS = 3

class EnstoRealTimeCoordinator:
    def __init__(self, manager):
        self._manager = manager
        self._last_data = None
        self._last_update = None
        self._update_lock = asyncio.Lock()
        
    async def get_real_time_data(self, max_age_seconds=25):
        """Returns cached data if less than 25 seconds old, otherwise reads new."""
        async with self._update_lock:
            now = time.time()
            device_name = getattr(self._manager, 'device_name', 'Unknown Device')
            
            if (self._last_data and self._last_update and
                now - self._last_update < max_age_seconds):
                LOGGER.debug("Loaded from cache for %s (%s) - age: %.1fs",
                           device_name, self._manager.mac_address, now - self._last_update)
                return self._last_data
                        
            # Read new data
            LOGGER.debug("Reading new data for %s (%s)",
                        device_name, self._manager.mac_address)
            # The coordinator owns reconnecting; BLE helpers only check the connection
            await self._manager.ensure_connection()

            connected_at = self._manager.connected_at
            if connected_at is not None:
                wait = CONNECT_SETTLE_SECONDS - (time.monotonic() - connected_at)
                if wait > 0:
                    LOGGER.debug("Waiting %.1f s for %s (%s) to settle after connecting",
                                 wait, device_name, self._manager.mac_address)
                    await asyncio.sleep(wait)

            raw_data = await self._manager._ble_read_split(REAL_TIME_INDICATION_UUID, "real-time indication")
            if raw_data:
                self._last_data = self._manager.parse_real_time_indication(raw_data)
                self._last_update = now
                return self._last_data
            return None
