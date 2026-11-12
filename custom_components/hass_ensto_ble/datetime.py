"""Support for Ensto BLE datetime entities."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import device_registry as dr
from asyncio import sleep

from .base_entity import EnstoCoordinatorEntity
from .coordinator import VACATION
from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

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
        """Update the datetime value and write to device."""
        try:
            # Home Assistant handles times internally as UTC, but user sees and inputs local time in the UI.
            # When the value is passed here, it's already in UTC format but represents the local time entered by the user.

            # Read fresh settings, the coordinator data can be up to 30 s old
            current_settings = await self._manager.read_vacation_time()
            if not current_settings:
                _LOGGER.error("Failed to read current vacation settings")
                return

            # Determine which value to update
            time_from = value if self._date_type == 'start' else current_settings['time_from']
            time_to = value if self._date_type == 'end' else current_settings['time_to']

            # Validate that start time is before end time
            if time_from >= time_to:
                if self._date_type == 'start':
                    _LOGGER.warning(
                        "Vacation end date (%s) is not after new start (%s); "
                        "automatically advancing end to start + 7 days",
                        time_to, time_from,
                    )
                    time_to = time_from + timedelta(days=7)
                else:
                    # Shown to the user; the frontend then shows the device value again
                    raise ServiceValidationError("Vacation end must be after vacation start")

            # Write values to the device
            success = await self._manager.write_vacation_time(
                time_from=time_from,
                time_to=time_to,
                offset_temperature=current_settings['offset_temperature'],
                offset_percentage=current_settings['offset_percentage'],
                enabled=current_settings.get('enabled', False)
            )

            if success:
                # Give the device 500 ms to process the change before reading it back
                await sleep(0.5)
            else:
                _LOGGER.error("Failed to update vacation %s time", self._date_type)

        except ServiceValidationError:
            raise
        except Exception as e:
            _LOGGER.error("Error updating vacation time: %s", e)
            await self._async_refresh()
            raise

        # Read back, so both vacation datetimes show the device values
        await self._async_refresh()
