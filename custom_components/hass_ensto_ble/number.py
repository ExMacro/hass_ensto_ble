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

from .base_entity import EnstoCoordinatorEntity
from .const import CURRENCY_SYMBOLS
from .config_flow import CONF_CURRENCY, DEFAULT_CURRENCY
from .coordinator import (
    BOOST,
    ENERGY_UNIT,
    FLOOR_AREA,
    FLOOR_LIMITS,
    FORCE_CONTROL,
    HEATING_MODE,
    HEATING_POWER,
    ROOM_CALIBRATION,
    VACATION,
)

from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

# Heating modes that change which numbers are available
COMBINATION_MODE = 3
POWER_MODE = 4

async def async_setup_entry(
    hass: HomeAssistant, # Home Assistant instance
    entry: EnstoConfigEntry, # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback, # Callback to register new entities
) -> None:
    """Set up numbers from a config entry."""
    manager = entry.runtime_data
    coordinator = manager.coordinator

    # Get currency from config entry
    currency = entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)

    entities = [
        EnstoBoostDurationNumber(coordinator),
        EnstoBoostOffsetNumber(coordinator),
        EnstoBoostPowerOffsetNumber(coordinator),
        EnstoRoomSensorCalibrationNumber(coordinator),
        EnstoHeatingPowerNumber(coordinator),
        EnstoEnergyUnitPriceNumber(coordinator, currency),
        EnstoVacationTempOffsetNumber(coordinator),
        EnstoVacationPowerOffsetNumber(coordinator),
    ]

    # Add floor limit numbers only for ECO16 models
    model = manager.model_number if manager.model_number else ""
    if "ECO16" in model:
        entities.extend([
            EnstoFloorLimitNumber(coordinator, "low"),
            EnstoFloorLimitNumber(coordinator, "high"),
            EnstoFloorAreaNumber(coordinator),
        ])

    # Add external control numbers only for firmware 1.14+
    if manager.supports_external_control():
        entities.extend([
            EnstoExternalControlTemperatureNumber(coordinator),
            EnstoExternalControlOffsetNumber(coordinator),
        ])

    async_add_entities(entities)

class EnstoCoordinatorNumber(EnstoCoordinatorEntity, NumberEntity):
    """Base class for numbers that show a value read by the coordinator."""

    _attr_mode = "box"

    @property
    def _heating_mode(self) -> int | None:
        """Return the heating mode number, None if not read yet."""
        mode = self.coordinator.data.get(HEATING_MODE)
        return mode['mode_number'] if mode else None

class EnstoBoostDurationNumber(EnstoCoordinatorNumber):
    """Number entity for controlling boost duration."""

    _data_key = BOOST

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Boost duration"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_duration"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 180
        self._attr_native_step = 5
        self._attr_native_unit_of_measurement = "min"

    @property
    def native_value(self) -> float:
        """Return the boost duration."""
        return self._value['setpoint_minutes']

    async def async_set_native_value(self, value: float) -> None:
        """Update the boost duration."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_boost()
            if settings:
                await self._manager.write_boost(
                    enabled=settings['enabled'],
                    offset_degrees=settings['offset_degrees'],
                    offset_percentage=settings['offset_percentage'],
                    duration_minutes=int(value)
                )
        except Exception as e:
            _LOGGER.error("Failed to set boost duration: %s", e)
        await self._async_refresh()

class EnstoBoostOffsetNumber(EnstoCoordinatorNumber):
    """Number entity for controlling boost temperature offset."""

    _data_key = BOOST
    _extra_keys = (HEATING_MODE,)

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_name = "Boost temperature offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_temp_offset"
        self._attr_native_min_value = -20
        self._attr_native_max_value = 20
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is available in all heating modes except Power mode (mode 4).
        """
        return super().available and self._heating_mode != POWER_MODE

    @property
    def native_value(self) -> float:
        """Return the boost temperature offset."""
        return self._value['offset_degrees']

    async def async_set_native_value(self, value: float) -> None:
        """Update the boost temperature offset."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_boost()
            if settings:
                await self._manager.write_boost(
                    enabled=settings['enabled'],
                    offset_degrees=value,
                    offset_percentage=settings['offset_percentage'],
                    duration_minutes=settings['setpoint_minutes']
                )
        except Exception as e:
            _LOGGER.error("Failed to set boost temperature offset: %s", e)
        await self._async_refresh()

class EnstoBoostPowerOffsetNumber(EnstoCoordinatorNumber):
    """Number entity for controlling boost power offset percentage.

    This entity is only available when heating mode is set to Power (mode 4).
    It allows adjusting boost power percentage from -100% to 100%.
    """

    _data_key = BOOST
    _extra_keys = (HEATING_MODE,)

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Boost power offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_boost_power_offset"
        self._attr_native_min_value = -100
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is only available in Power heating mode (mode 4).
        """
        return super().available and self._heating_mode == POWER_MODE

    @property
    def native_value(self) -> float:
        """Return the boost power offset."""
        return self._value['offset_percentage']

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
        except Exception as e:
            _LOGGER.error("Failed to set boost power offset: %s", e)
        await self._async_refresh()

class EnstoFloorLimitNumber(EnstoCoordinatorNumber):
    """Control floor temperature limits.

    This entity controls the minimum and maximum floor temperature limits
    for combination heating mode. The limits are only available when
    heating mode is set to combination (mode 3).
    """

    _data_key = FLOOR_LIMITS
    _extra_keys = (HEATING_MODE,)

    def __init__(self, coordinator, limit_type):
        """Initialize the number control."""
        super().__init__(coordinator)
        self._limit_type = limit_type
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_native_step = 0.5
        self._attr_entity_registry_enabled_default = True

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
        return super().available and self._heating_mode == COMBINATION_MODE

    @property
    def native_value(self) -> float:
        """Return the floor temperature limit."""
        return self._value['low_value' if self._limit_type == "low" else 'high_value']

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        try:
            # Read fresh limits, the coordinator data can be up to 30 s old
            limits = await self._manager.read_floor_limits()
            if limits:
                if self._limit_type == "low":
                    await self._manager.write_floor_limits(value, limits['high_value'])
                else:
                    await self._manager.write_floor_limits(limits['low_value'], value)
        except Exception as e:
            _LOGGER.error("Failed to set floor temperature limit: %s", e)
        await self._async_refresh()

class EnstoRoomSensorCalibrationNumber(EnstoCoordinatorNumber):
    """Number entity for room sensor calibration."""

    _data_key = ROOM_CALIBRATION

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Room sensor calibration"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_room_sensor_calibration"
        self._attr_native_min_value = -5.0
        self._attr_native_max_value = 5.0
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def native_value(self) -> float:
        """Return the room sensor calibration value."""
        return self._value['calibration_value']

    async def async_set_native_value(self, value: float) -> None:
        """Update room sensor calibration value."""
        try:
            await self._manager.write_room_sensor_calibration(value)
        except Exception as e:
            _LOGGER.error("Failed to set room sensor calibration: %s", e)
        await self._async_refresh()

class EnstoHeatingPowerNumber(EnstoCoordinatorNumber):
    """Number entity for controlling heating power."""

    _data_key = HEATING_POWER

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Heating power"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_heating_power"

        # Set value constraints for heating power
        self._attr_native_min_value = 0
        self._attr_native_max_value = 9999
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "W"  # Watts
        self._attr_device_class = NumberDeviceClass.POWER

    @property
    def native_value(self) -> float:
        """Return the heating power."""
        return self._value['heating_power']

    async def async_set_native_value(self, value: float) -> None:
        """Update the heating power value."""
        try:
            # Convert float to integer as heating power is an integer
            await self._manager.write_heating_power(int(value))
        except Exception as e:
            _LOGGER.error("Failed to set custom heating power: %s", e)
        await self._async_refresh()

class EnstoFloorAreaNumber(EnstoCoordinatorNumber):
    """Number entity for controlling floor area."""

    _data_key = FLOOR_AREA

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Floor area"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_floor_area"

        # Set value constraints for floor area
        self._attr_native_min_value = 0
        self._attr_native_max_value = 65535  # Maximum uint16_t value
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "m²"  # Square meters
        self._attr_device_class = NumberDeviceClass.AREA

    @property
    def native_value(self) -> float:
        """Return the floor area."""
        return self._value['floor_area']

    async def async_set_native_value(self, value: float) -> None:
        """Update the floor area value."""
        try:
            # Convert float to integer as floor area is an integer
            await self._manager.write_floor_area(int(value))
        except Exception as e:
            _LOGGER.error("Failed to set custom floor area: %s", e)
        await self._async_refresh()

class EnstoEnergyUnitPriceNumber(EnstoCoordinatorNumber):
    """Number entity for controlling energy unit price."""

    _data_key = ENERGY_UNIT

    def __init__(self, coordinator, currency: int):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Energy unit price"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_energy_unit_price"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 655.35
        self._attr_native_step = 0.01

        # Use currency from config flow
        self._currency = currency
        self._attr_entity_category = EntityCategory.CONFIG

        # Use currency symbol from config flow
        self._attr_native_unit_of_measurement = f"{CURRENCY_SYMBOLS[currency]}/kWh"

    @property
    def native_value(self) -> float:
        """Return the energy unit price."""
        return self._value['price']

    async def async_set_native_value(self, value: float) -> None:
        """Update the energy unit price value."""
        try:
            await self._manager.write_energy_unit(self._currency, value)
        except Exception as e:
            _LOGGER.error("Failed to set energy unit price: %s", e)
        await self._async_refresh()

class EnstoVacationTempOffsetNumber(EnstoCoordinatorNumber):
    """Number entity for vacation mode temperature offset in celsius."""

    _data_key = VACATION
    _extra_keys = (HEATING_MODE,)

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Vacation temperature offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_temp_offset"
        self._attr_native_min_value = -20.0
        self._attr_native_max_value = 20.0
        self._attr_native_step = 0.5
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is available in all heating modes except Power mode (mode 4).
        """
        return super().available and self._heating_mode != POWER_MODE

    @property
    def native_value(self) -> float:
        """Return the vacation temperature offset."""
        return self._value['offset_temperature']

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
        except Exception as e:
            _LOGGER.error("Failed to set vacation temperature offset: %s", e)
        await self._async_refresh()

class EnstoVacationPowerOffsetNumber(EnstoCoordinatorNumber):
    """Number entity for vacation mode power offset percentage."""

    _data_key = VACATION
    _extra_keys = (HEATING_MODE,)

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "Vacation power offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_vacation_power_offset"
        self._attr_native_min_value = -100
        self._attr_native_max_value = 100
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "%"

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is only available in Power heating mode (mode 4).
        """
        return super().available and self._heating_mode == POWER_MODE

    @property
    def native_value(self) -> float:
        """Return the vacation power offset."""
        return self._value['offset_percentage']

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
        except Exception as e:
            _LOGGER.error("Failed to set vacation power offset: %s", e)
        await self._async_refresh()

class EnstoExternalControlTemperatureNumber(EnstoCoordinatorNumber):
    """Number entity for external control absolute temperature (mode 5).

    Sets the target temperature when external control mode is "Temperature".
    """

    _data_key = FORCE_CONTROL

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "External control temperature"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_external_control_temperature"
        self._attr_native_min_value = 5.0
        self._attr_native_max_value = 35.0
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_icon = "mdi:thermometer"

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is only available when external control mode is Temperature (mode 5).
        """
        return super().available and self._value.get('mode', 2) == 5

    @property
    def native_value(self) -> float:
        """Return the external control temperature."""
        return self._value.get('temperature', 20.0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the external control temperature."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_force_control()
            if settings:
                await self._manager.write_force_control(
                    mode=settings['mode'],
                    temperature=value,
                    temperature_offset=settings['temperature_offset']
                )
        except Exception as e:
            _LOGGER.error("Failed to set external control temperature: %s", e)
        await self._async_refresh()

class EnstoExternalControlOffsetNumber(EnstoCoordinatorNumber):
    """Number entity for external control temperature offset (mode 6).

    Sets the temperature offset when external control mode is "Temperature change".
    """

    _data_key = FORCE_CONTROL

    def __init__(self, coordinator):
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_name = "External control offset"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_external_control_offset"
        self._attr_native_min_value = -20.0
        self._attr_native_max_value = 20.0
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = NumberDeviceClass.TEMPERATURE
        self._attr_icon = "mdi:thermometer-plus"

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Entity is only available when external control mode is Temperature change (mode 6).
        """
        return super().available and self._value.get('mode', 2) == 6

    @property
    def native_value(self) -> float:
        """Return the external control temperature offset."""
        return self._value.get('temperature_offset', 0.0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the external control temperature offset."""
        try:
            # Read fresh settings, the coordinator data can be up to 30 s old
            settings = await self._manager.read_force_control()
            if settings:
                await self._manager.write_force_control(
                    mode=settings['mode'],
                    temperature=settings['temperature'],
                    temperature_offset=value
                )
        except Exception as e:
            _LOGGER.error("Failed to set external control offset: %s", e)
        await self._async_refresh()
