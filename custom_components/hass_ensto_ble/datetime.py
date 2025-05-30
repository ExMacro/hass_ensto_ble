"""Support for Ensto BLE datetime entities."""
import logging
from datetime import datetime, timedelta

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from asyncio import sleep

from .const import DOMAIN, SIGNAL_DATETIME_UPDATE
from .base_entity import EnstoBaseEntity

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ensto datetime entities from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    
    # Create and add vacation start/end datetime entities
    async_add_entities([
        EnstoVacationDateTimeEntity(manager, 'start'),
        EnstoVacationDateTimeEntity(manager, 'end'),
    ], True)

class EnstoVacationDateTimeEntity(EnstoBaseEntity, DateTimeEntity):
    """DateTime entity for Ensto vacation mode start and end times."""
   
    # Class attributes that apply to all instances
    _attr_has_entity_name = True  # Use the device name as a prefix
    _attr_entity_category = EntityCategory.CONFIG  # Show in configuration section in UI and make editable
    _attr_should_poll = False  # Disable polling - rely on signals instead

    def __init__(self, manager, date_type):
        """Initialize the DateTime entity."""
        super().__init__(manager)
        self._date_type = date_type
        
        # Set up entity attributes
        self._attr_name = f"Vacation {date_type.capitalize()}"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_vacation_{date_type}_datetime"
        self._attr_icon = "mdi:calendar-clock"
        
        # Initialize native value as None
        self._attr_native_value: datetime | None = None

    async def async_added_to_hass(self) -> None:
        """Set up the entity when added to HA."""
        # Initial data fetch when first added
        await self.async_update()
        
        # Subscribe to signal updates
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DATETIME_UPDATE.format(self._manager.mac_address),
                self._async_handle_update
            )
        )

    async def _async_handle_update(self) -> None:
        """Handle dispatched updates."""
        await self.async_update()
        self.async_write_ha_state()

    async def async_set_value(self, value: datetime) -> None:
       """Update the datetime value and write to device."""
       try:
           # Store the original value for possible rollback
           original_value = self._attr_native_value
           
           # Home Assistant handles times internally as UTC, but user sees and inputs local time in the UI.
           # When the value is passed here, it's already in UTC format but represents the local time entered by the user.
               
           # Fetch current settings from the device
           current_settings = await self._manager.read_vacation_time()
           if not current_settings:
               _LOGGER.error("Failed to read current vacation settings")
               return
                   
           # Determine which value to update and validate time order
           time_from = value if self._date_type == 'start' else current_settings['time_from']
           time_to = value if self._date_type == 'end' else current_settings['time_to']
           
           # Validate that start time is before end time
           if time_from >= time_to:
               _LOGGER.error("Invalid vacation time: start time must be before end time")
               self._attr_native_value = original_value
               self.async_write_ha_state()
               return
           
           # Get temperature and power offset values. Convert MAC address with : to using underscore
           temp_offset_entity_id = f'number.ensto_thermostat_{self._manager.mac_address.replace(":", "_").lower()}_vacation_temperature_offset'
           power_offset_entity_id = f'number.ensto_thermostat_{self._manager.mac_address.replace(":", "_").lower()}_vacation_power_offset'
           
           temp_state = self.hass.states.get(temp_offset_entity_id)
           power_state = self.hass.states.get(power_offset_entity_id)
           
           temp_value = float(temp_state.state) if temp_state and temp_state.state not in ['unknown', 'unavailable'] else current_settings['offset_temperature']
           power_value = int(float(power_state.state)) if power_state and power_state.state not in ['unknown', 'unavailable'] else current_settings['offset_percentage']
           
           # Write values to the device
           success = await self._manager.write_vacation_time(
               time_from=time_from,
               time_to=time_to,
               offset_temperature=temp_value,
               offset_percentage=power_value,
               enabled=current_settings.get('enabled', False)
           )

           if success:
               # After writing, read back the values to ensure synchronization
               # Add a small delay to allow device to process the change
               await sleep(0.5)  # Give device 500ms to process the change
               verify_settings = await self._manager.read_vacation_time()
               
               if verify_settings:
                   # Verify that the value is actually what we requested and use device's value
                   verified_value = verify_settings['time_from'] if self._date_type == 'start' else verify_settings['time_to']
                   self._attr_native_value = verified_value
               else:
                   # If verification read fails, revert to original value
                   _LOGGER.error("Failed to verify vacation time update")
                   self._attr_native_value = original_value
           else:
               # If write fails, revert to original value
               _LOGGER.error(f"Failed to update vacation {self._date_type} time")
               self._attr_native_value = original_value

           # Force UI update
           self.async_write_ha_state()
               
       except Exception as e:
           _LOGGER.error(f"Error updating vacation time: {e}")
           # In case of error, try to update with actual value from device
           await self.async_update()
           self.async_write_ha_state()
           raise

    async def async_update(self) -> None:
        """Fetch current datetime value from the device."""
        try:
            # Read current vacation time settings
            current = await self._manager.read_vacation_time()
            if current:
                # Update the native value based on entity type
                if self._date_type == 'start':
                    self._attr_native_value = current['time_from']
                else:
                    self._attr_native_value = current['time_to']
                
        except Exception as e:
            _LOGGER.error(f"Error updating vacation {self._date_type} time: {e}")
