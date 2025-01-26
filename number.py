"""Support for Ensto BLE number controls."""
import logging
from typing import Optional

from homeassistant.components.number import (
   NumberEntity,
   NumberDeviceClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
   hass: HomeAssistant,
   entry: ConfigEntry,
   async_add_entities: AddEntitiesCallback,
) -> None:
   """Set up numbers from config entry."""
   manager = hass.data[DOMAIN][entry.entry_id]
   
   entities = [
       EnstoBoostDurationNumber(manager),
       EnstoBoostOffsetNumber(manager),
   ]
   async_add_entities(entities, True)

class EnstoBoostDurationNumber(EnstoBaseEntity, NumberEntity):
   """Number entity for controlling boost duration."""
   
   _attr_scan_interval = SCAN_INTERVAL

   def __init__(self, manager):
       super().__init__(manager)
       self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Boost Duration"
       self._attr_unique_id = f"ensto_{self._manager.mac_address}_boost_duration"
       self._attr_native_min_value = 0
       self._attr_native_max_value = 180
       self._attr_native_step = 5
       self._attr_native_unit_of_measurement = "min"
       self._attr_mode = "box"
       self._attr_native_value = None

   async def async_set_native_value(self, value: float) -> None:
       """Update the boost duration."""
       try:
           settings = await self._manager.read_boost()
           if settings:
               await self._manager.write_boost(
                   enabled=settings['enabled'],
                   offset_degrees=settings['offset_degrees'],
                   offset_percentage=settings['offset_percentage'],
                   duration_minutes=int(value)
               )
               self._attr_native_value = value
       except Exception as e:
           _LOGGER.error("Failed to set boost duration: %s", e)

   async def async_update(self) -> None:
       """Fetch new state data for the number."""
       try:
           settings = await self._manager.read_boost()
           if settings:
               self._attr_native_value = settings['setpoint_minutes']
       except Exception as e:
           _LOGGER.error("Error updating boost duration: %s", e)

class EnstoBoostOffsetNumber(EnstoBaseEntity, NumberEntity):
   """Number entity for controlling boost temperature offset."""

   _attr_scan_interval = SCAN_INTERVAL

   def __init__(self, manager):
       super().__init__(manager)
       self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Boost Temperature Offset"
       self._attr_unique_id = f"ensto_{self._manager.mac_address}_boost_temp_offset"
       self._attr_native_min_value = 0
       self._attr_native_max_value = 5
       self._attr_native_step = 0.5
       self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
       self._attr_device_class = NumberDeviceClass.TEMPERATURE
       self._attr_mode = "box"
       self._attr_native_value = None

   async def async_set_native_value(self, value: float) -> None:
       """Update the boost temperature offset."""
       try:
           settings = await self._manager.read_boost()
           if settings:
               await self._manager.write_boost(
                   enabled=settings['enabled'],
                   offset_degrees=value,
                   offset_percentage=settings['offset_percentage'],
                   duration_minutes=settings['setpoint_minutes']
               )
               self._attr_native_value = value
       except Exception as e:
           _LOGGER.error("Failed to set boost temperature offset: %s", e)

   async def async_update(self) -> None:
       """Fetch new state data for the number."""
       try:
           settings = await self._manager.read_boost()
           if settings:
               self._attr_native_value = settings['offset_degrees']
       except Exception as e:
           _LOGGER.error("Error updating boost temperature offset: %s", e)
