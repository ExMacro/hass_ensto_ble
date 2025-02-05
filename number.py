"""Support for Ensto BLE number controls."""
import logging

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
       EnstoFloorLimitNumber(manager, "low"),
       EnstoFloorLimitNumber(manager, "high"),
       EnstoRoomSensorCalibrationNumber(manager),
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

class EnstoFloorLimitNumber(EnstoBaseEntity, NumberEntity):
    """Control floor temperature limits.

    This entity controls the minimum and maximum floor temperature limits
    for combination heating mode. The limits are only available when
    heating mode is set to combination (mode 3).
    """
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager, limit_type):
        """Initialize the number control."""
        super().__init__(manager)
        self._limit_type = limit_type
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_step = 0.5
        self._attr_mode = "box"
        self._attr_native_value = None
        self._attr_entity_registry_enabled_default = True
        self._current_mode = None
        
        # Set limits based on type
        if limit_type == "low":
            self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Floor Temperature Min"
            self._attr_unique_id = f"ensto_{self._manager.mac_address}_floor_temp_min"
            self._attr_native_min_value = 5  # Minimum allowed
            self._attr_native_max_value = 42  # Must be 8 degrees less than absolute max 50
        else:
            self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Floor Temperature Max"
            self._attr_unique_id = f"ensto_{self._manager.mac_address}_floor_temp_max"
            self._attr_native_min_value = 13  # Must be 8 degrees more than absolute min 5
            self._attr_native_max_value = 50  # Maximum allowed

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        The entity is only available in combination heating mode (mode 3).
        """
        return self._current_mode == 3  # Only show Floor Min / Max in "Combination" heating mode

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        try:
            limits = await self._manager.read_floor_limits()
            if limits:
                if self._limit_type == "low":
                    await self._manager.write_floor_limits(value, limits['high_value'])
                else:
                    await self._manager.write_floor_limits(limits['low_value'], value)
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set floor temperature limit: %s", e)

    async def async_update(self) -> None:
            try:
                mode_result = await self._manager.read_heating_mode()
                if mode_result:
                    self._current_mode = mode_result['mode_number']
                    
                limits = await self._manager.read_floor_limits()
                if limits:
                    self._attr_native_value = limits['low_value' if self._limit_type == "low" else 'high_value']
            except Exception as e:
                _LOGGER.error("Error updating: %s", e)

class EnstoRoomSensorCalibrationNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for room sensor calibration."""

    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = f"{self._manager.device_name or self._manager.mac_address} Room Sensor Calibration"
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_room_sensor_calibration"
        self._attr_native_min_value = -5.0
        self._attr_native_max_value = 5.0
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_mode = "box"
        self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Update room sensor calibration value."""
        try:
            success = await self._manager.write_room_sensor_calibration(value)
            if success:
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set room sensor calibration: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            result = await self._manager.read_room_sensor_calibration()
            if result:
                self._attr_native_value = result['calibration_value']
        except Exception as e:
            _LOGGER.error("Error updating room sensor calibration: %s", e)
