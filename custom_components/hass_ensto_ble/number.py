"""Support for Ensto BLE number controls."""
import logging

from homeassistant.components.number import (
   NumberEntity,
   NumberDeviceClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry

from .base_entity import EnstoBaseEntity
from .const import DOMAIN, SCAN_INTERVAL, CURRENCY_SYMBOLS
from .config_flow import CONF_CURRENCY, DEFAULT_CURRENCY

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers from config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    
    # Get currency from config entry
    currency = entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
    
    entities = [
        EnstoBoostDurationNumber(manager),
        EnstoBoostOffsetNumber(manager),
        EnstoBoostPowerOffsetNumber(manager),
        EnstoRoomSensorCalibrationNumber(manager),
        EnstoHeatingPowerNumber(manager),
        EnstoEnergyUnitPriceNumber(manager, currency),
        EnstoVacationTempOffsetNumber(manager),
        EnstoVacationPowerOffsetNumber(manager),
    ]

    # Add floor limit numbers only for ECO16 models
    model = manager.model_number if manager.model_number else ""
    if "ECO16" in model:
        entities.extend([
            EnstoFloorLimitNumber(manager, "low"),
            EnstoFloorLimitNumber(manager, "high"),
            EnstoFloorAreaNumber(manager),
        ])

    async_add_entities(entities, True)

class EnstoBoostDurationNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for controlling boost duration."""
   
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        super().__init__(manager)
        self._attr_name = "Boost duration"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_duration"
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
    _attr_has_entity_name = True

    def __init__(self, manager):
        super().__init__(manager)
        self._attr_name = "Boost temperature offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_temp_offset"
        self._attr_native_min_value = -20
        self._attr_native_max_value = 20
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_mode = "box"
        self._attr_native_value = None
        self._current_mode = None

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Entity is available in all heating modes except Power mode (mode 4).
        """
        return self._current_mode != 4

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
            mode_result = await self._manager.read_heating_mode()
            if mode_result:
                self._current_mode = mode_result['mode_number']
            
            settings = await self._manager.read_boost()
            if settings:
                self._attr_native_value = settings['offset_degrees']
        except Exception as e:
            _LOGGER.error("Error updating boost temperature offset: %s", e)

class EnstoBoostPowerOffsetNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for controlling boost power offset percentage.

    This entity is only visible when heating mode is set to Power (mode 4).
    It allows adjusting boost power percentage from -100% to 100%.
    """

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Boost power offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_power_offset"
        self._attr_native_min_value = -100
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = "box"
        self._attr_native_value = None
        self._current_mode = None

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Entity is only available in Power heating mode (mode 4).
        """
        return self._current_mode == 4

    async def async_set_native_value(self, value: float) -> None:
        """Update the boost power offset percentage.
        
        Reads current boost settings and updates only the power
        offset while preserving other settings.
        """
        try:
            settings = await self._manager.read_boost()
            if settings:
                await self._manager.write_boost(
                    enabled=settings['enabled'],
                    offset_degrees=settings['offset_degrees'],
                    offset_percentage=int(value),
                    duration_minutes=settings['setpoint_minutes']
                )
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set boost power offset: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            mode_result = await self._manager.read_heating_mode()
            if mode_result:
                self._current_mode = mode_result['mode_number']
            
            settings = await self._manager.read_boost()
            if settings:
                self._attr_native_value = settings['offset_percentage']
        except Exception as e:
            _LOGGER.error("Error updating boost power offset: %s", e)

class EnstoFloorLimitNumber(EnstoBaseEntity, NumberEntity):
    """Control floor temperature limits.

    This entity controls the minimum and maximum floor temperature limits
    for combination heating mode. The limits are only available when
    heating mode is set to combination (mode 3).
    """
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

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
            self._attr_name = "Floor temperature min"
            self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_temp_min"
            self._attr_native_min_value = 5  # Minimum allowed
            self._attr_native_max_value = 42  # Must be 8 degrees less than absolute max 50
        else:
            self._attr_name = "Floor temperature max"
            self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_temp_max"
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
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Room sensor calibration"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_room_sensor_calibration"
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

class EnstoHeatingPowerNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for controlling heating power."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Heating power"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_heating_power"
        
        # Set value constraints for heating power
        self._attr_native_min_value = 0
        self._attr_native_max_value = 9999
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "W"  # Watts
        self._attr_mode = "box"
        self._attr_native_value = None
        self._attr_device_class = NumberDeviceClass.POWER

    async def async_set_native_value(self, value: float) -> None:
        """Update the heating power value."""
        try:
            # Convert float to integer as heating power is an integer
            success = await self._manager.write_heating_power(int(value))
            if success:
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set custom heating power: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            result = await self._manager.read_heating_power()
            if result:
                self._attr_native_value = result['heating_power']
        except Exception as e:
            _LOGGER.error("Error updating custom heating power: %s", e)

class EnstoFloorAreaNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for controlling floor area."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Floor area"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_area"
        
        # Set value constraints for floor area
        self._attr_native_min_value = 0
        self._attr_native_max_value = 65535  # Maximum uint16_t value
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "m²"  # Square meters
        self._attr_mode = "box"
        self._attr_native_value = None
        self._attr_device_class = NumberDeviceClass.AREA

    async def async_set_native_value(self, value: float) -> None:
        """Update the floor area value."""
        try:
            # Convert float to integer as floor area is an integer
            success = await self._manager.write_floor_area(int(value))
            if success:
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set custom floor area: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            result = await self._manager.read_floor_area()
            if result:
                self._attr_native_value = result['floor_area']
        except Exception as e:
            _LOGGER.error("Error updating custom floor area: %s", e)

class EnstoEnergyUnitPriceNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for controlling energy unit price."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager, currency: int):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Energy unit price"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_energy_unit_price"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 655.35
        self._attr_native_step = 0.01
        self._attr_mode = "box"
        self._attr_native_value = None
        
        # Use currency from config flow
        self._currency = currency
        self._attr_entity_category = EntityCategory.CONFIG
        
        # Use currency symbol from config flow
        self._attr_native_unit_of_measurement = f"{CURRENCY_SYMBOLS[currency]}/kWh"

    async def async_set_native_value(self, value: float) -> None:
        """Update the energy unit price value."""
        try:
            success = await self._manager.write_energy_unit(self._currency, value)
            if success:
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set energy unit price: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            result = await self._manager.read_energy_unit()
            if result:
                self._attr_native_value = result['price']

        except Exception as e:
            _LOGGER.error("Error updating energy unit price: %s", e)

class EnstoVacationTempOffsetNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for vacation mode temperature offset in celsius."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Vacation temperature offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_temp_offset"
        self._attr_native_min_value = -20.0
        self._attr_native_max_value = 20.0
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_mode = "box"
        self._attr_native_value = None
        self._current_mode = None

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Entity is available in all heating modes except Power mode (mode 4).
        """
        return self._current_mode != 4

    async def async_set_native_value(self, value: float) -> None:
        """Update the vacation temperature offset value.
        
        Reads current vacation settings and updates only the temperature
        offset while preserving other settings.
        """
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                await self._manager.write_vacation_time(
                    time_from=settings['time_from'],
                    time_to=settings['time_to'],
                    offset_temperature=value,
                    offset_percentage=settings['offset_percentage'],
                    enabled=settings['enabled']
                )
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set vacation temperature offset: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            mode_result = await self._manager.read_heating_mode()
            if mode_result:
                self._current_mode = mode_result['mode_number']
            
            result = await self._manager.read_vacation_time()
            if result:
                self._attr_native_value = result['offset_temperature']
        except Exception as e:
            _LOGGER.error("Error updating vacation temperature offset: %s", e)

class EnstoVacationPowerOffsetNumber(EnstoBaseEntity, NumberEntity):
    """Number entity for vacation mode power offset percentage."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the entity."""
        super().__init__(manager)
        self._attr_name = "Vacation power offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_power_offset"
        self._attr_native_min_value = -100
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"
        self._attr_mode = "box"
        self._attr_native_value = None
        self._current_mode = None

    @property
    def available(self) -> bool:
        """Return if entity is available.
        
        Entity is only available in Power heating mode (mode 4).
        """
        return self._current_mode == 4

    async def async_set_native_value(self, value: float) -> None:
        """Update the vacation power offset percentage.
        
        Reads current vacation settings and updates only the power
        offset while preserving other settings.
        """
        try:
            settings = await self._manager.read_vacation_time()
            if settings:
                await self._manager.write_vacation_time(
                    time_from=settings['time_from'],
                    time_to=settings['time_to'],
                    offset_temperature=settings['offset_temperature'],
                    offset_percentage=int(value),
                    enabled=settings['enabled']
                )
                self._attr_native_value = value
        except Exception as e:
            _LOGGER.error("Failed to set vacation power offset: %s", e)

    async def async_update(self) -> None:
        """Fetch new state data for the number."""
        try:
            mode_result = await self._manager.read_heating_mode()
            if mode_result:
                self._current_mode = mode_result['mode_number']
            
            result = await self._manager.read_vacation_time()
            if result:
                self._attr_native_value = result['offset_percentage']
        except Exception as e:
            _LOGGER.error("Error updating vacation power offset: %s", e)
