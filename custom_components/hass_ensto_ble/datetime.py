"""Support for Ensto BLE datetime entities."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from asyncio import sleep

from .base_entity import EnstoCoordinatorEntity
from .coordinator import VACATION
from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

# One write at a time, so read-modify-write actions don't overwrite each other
PARALLEL_UPDATES = 1

async def async_setup_entry(
    hass: HomeAssistant, # Home Assistant instance
    entry: EnstoConfigEntry, # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback, # Callback to register new entities
) -> None:
    """Set up Ensto datetime entities from a config entry."""
    coordinator = entry.runtime_data.coordinator

    # Create and add vacation start/end datetime entities
    async_add_entities([
        EnstoVacationDateTimeEntity(coordinator, 'start'),
        EnstoVacationDateTimeEntity(coordinator, 'end'),
    ])

class EnstoVacationDateTimeEntity(EnstoCoordinatorEntity, DateTimeEntity):
    """DateTime entity for Ensto vacation mode start and end times."""

    _attr_entity_category = EntityCategory.CONFIG  # Show in configuration section in UI and make editable
    _data_key = VACATION

    def __init__(self, coordinator, date_type):
        """Initialize the DateTime entity."""
        super().__init__(coordinator)
        self._date_type = date_type

        # Set up entity attributes
        self._attr_name = f"Vacation {date_type}"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_{date_type}_datetime"
        self._attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self) -> datetime:
        """Return the vacation start or end time."""
        return self._value['time_from' if self._date_type == 'start' else 'time_to']

    async def async_set_value(self, value: datetime) -> None:
        """Update the datetime value and write to device.

        The value is in UTC; the user enters it as local time in the UI.
        """
        self._check_connected()
        current = await self._read_current(self._manager.read_vacation_time)

        time_from = value if self._date_type == 'start' else current['time_from']
        time_to = value if self._date_type == 'end' else current['time_to']

        # A new start after the end moves the end a week after the start
        if self._date_type == 'start' and time_from >= time_to:
            _LOGGER.warning(
                "Vacation end date (%s) is not after new start (%s); "
                "automatically advancing end to start + 7 days",
                time_to, time_from,
            )
            time_to = time_from + timedelta(days=7)

        self._check_vacation_dates(time_from, time_to)

        # Give the device 500 ms to process the change before it is read back
        await self._write(self._write_and_wait(
            time_from=time_from,
            time_to=time_to,
            offset_temperature=current['offset_temperature'],
            offset_percentage=current['offset_percentage'],
            enabled=current.get('enabled', False)
        ))

    async def _write_and_wait(self, **settings) -> bool:
        """Write the vacation settings and wait for the device to process them."""
        if not await self._manager.write_vacation_time(**settings):
            return False
        await sleep(0.5)
        return True
