"""Support for Ensto BLE sensors."""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfTemperature,
    UnitOfPower,
    UnitOfEnergy,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import SCAN_INTERVAL
from .base_entity import EnstoBaseEntity, EnstoCoordinatorEntity
from .coordinator import (
    DATE_TIME,
    HEATING_POWER,
    MONITORING,
    POWER_CONSUMPTION,
    REAL_TIME,
    EnstoCoordinator,
    device_utc,
)

from . import EnstoConfigEntry

_LOGGER = logging.getLogger(__name__)

UNIT_MINUTES = "min"

class EnstoBaseSensor(EnstoBaseEntity, SensorEntity):
    """Base class for Ensto sensors that read their own value."""
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager)
        self._sensor_type = sensor_type
        self._attr_should_poll = True

class EnstoRealTimeSensor(CoordinatorEntity[EnstoCoordinator], EnstoBaseEntity, SensorEntity):
    """Base class for sensors that show a value from the real-time indication."""
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnstoCoordinator, sensor_type):
        """Initialize the sensor."""
        CoordinatorEntity.__init__(self, coordinator)
        EnstoBaseEntity.__init__(self, coordinator.manager)
        self._sensor_type = sensor_type

    @property
    def native_value(self):
        """Return the value from the latest real-time data."""
        return self.coordinator.data[REAL_TIME].get(self._data_key)

async def async_setup_entry(
    hass: HomeAssistant, # Home Assistant instance
    entry: EnstoConfigEntry, # Config entry containing device info like MAC address
    async_add_entities: AddEntitiesCallback, # Config entry containing device info like MAC address
) -> None:
    """Set up sensors from a config entry."""
    manager = entry.runtime_data
    coordinator = manager.coordinator

    # The coordinator already holds the first data, so these need no update before adding
    coordinator_sensors = [
        EnstoTemperatureSensor(coordinator, "room"),
        EnstoTemperatureSensor(coordinator, "target"),
        EnstoStateSensor(coordinator, "relay"),
        EnstoStateSensor(coordinator, "boost"),
        EnstoModeSensor(coordinator, "active"),
        EnstoModeSensor(coordinator, "heating"),
        EnstoNumberSensor(coordinator, "boost_setpoint"),
        EnstoNumberSensor(coordinator, "boost_remaining"),
        EnstoNumberSensor(coordinator, "alarm"),
        EnstoCurrentPowerSensor(coordinator),
        EnstoDateTimeSensor(coordinator),
        EnstoPowerConsumptionSensor(coordinator),
    ]

    # Add floor sensor only if value exists and is non-zero
    if coordinator.data[REAL_TIME].get("floor_temperature", 0) != 0:
        coordinator_sensors.append(EnstoTemperatureSensor(coordinator, "floor"))

    async_add_entities(coordinator_sensors)

    async_add_entities([
        EnstoNameSensor(manager),
        EnstoEnergySensor(manager),
    ], True)

class EnstoTemperatureSensor(EnstoRealTimeSensor):
    """Temperature sensor for Ensto thermostat."""

    def __init__(self, coordinator, sensor_type):
        """Initialize the temperature sensor."""

        super().__init__(coordinator, sensor_type)
        
        # Set common attributes for all temperature sensors
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
        # Set sensor-specific attributes based on type
        if sensor_type == "room":
            self._attr_name = "Room temperature"
            self._data_key = "room_temperature"
        elif sensor_type == "floor":
            self._attr_name = "Floor temperature"
            self._data_key = "floor_temperature"
        else:
            self._attr_name = "Target temperature"
            self._data_key = "target_temperature"

        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}_temp"

class EnstoStateSensor(EnstoRealTimeSensor):
    """State sensor for Ensto thermostat."""

    def __init__(self, coordinator, sensor_type):
        """Initialize the sensor."""
        super().__init__(coordinator, sensor_type)
        
        if sensor_type == "relay":
            self._attr_name = "Relay state"
            self._data_key = "relay_active"
        else:
            self._attr_name = "Boost state"
            self._data_key = "boost_enabled"

        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}_state"

class EnstoModeSensor(EnstoRealTimeSensor):
    """Mode sensor for Ensto thermostat."""

    def __init__(self, coordinator, sensor_type):
        """Initialize the sensor."""
        super().__init__(coordinator, sensor_type)
        
        if sensor_type == "active":
            self._attr_name = "Active mode"
            self._data_key = "active_mode"
        else:
            self._attr_name = "Heating mode"
            self._data_key = "heating_mode"

        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}_mode"

class EnstoNumberSensor(EnstoRealTimeSensor):
    """Number sensor for Ensto thermostat."""

    def __init__(self, coordinator, sensor_type):
        """Initialize the sensor."""
        super().__init__(coordinator, sensor_type)
        
        if "boost" in sensor_type:
            self._attr_native_unit_of_measurement = UNIT_MINUTES
            if sensor_type == "boost_setpoint":
                self._attr_name = "Boost setpoint"
                self._data_key = "boost_setpoint_minutes"
            else:  # boost_remaining
                self._attr_name = "Boost remaining"
                self._data_key = "boost_remaining_minutes"
        else:  # alarm
            self._attr_name = "Alarm status"
            self._data_key = "alarm_code"
            self._active_alarms_key = "active_alarms"
            
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}"

    @property
    def native_value(self) -> str:
        """
        Returns:
            str: For alarms - 'No active errors' or 'Error X: error description'
            float/int: For other sensors - the numeric value
        """
        if hasattr(self, '_active_alarms_key'):  # Only for alarm sensor
            data = self.coordinator.data[REAL_TIME]
            active_alarms = data.get(self._active_alarms_key, [])
            alarm_code = data.get(self._data_key, 0)

            if not active_alarms:
                return "No active errors"
            return f"Error {alarm_code}: {', '.join(active_alarms)}"

        return super().native_value  # Default behavior for other number sensors

class EnstoDateTimeSensor(EnstoCoordinatorEntity, SensorEntity):
    """DateTime sensor for Ensto thermostat.

    The coordinator reads the device clock (UTC) and synchronizes it with
    Home Assistant when it has drifted.
    """

    _data_key = DATE_TIME

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Date and time"
        # Create a unique ID for the sensor using MAC address
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_datetime"

    @property
    def native_value(self) -> str | None:
        """Return the device clock in local time, None if it is invalid."""
        clock = device_utc(self._value)
        if clock is None:
            return None
        # Shown in local time, also in the history
        return dt_util.as_local(clock).strftime("%-d.%-m.%Y %-H:%M")

class EnstoPowerConsumptionSensor(EnstoCoordinatorEntity, SensorEntity):
    """Sensor for monitoring power consumption.

    The state is the latest hourly power usage. The last 24 hours come with
    every read; the longer history comes from the monitoring data, which the
    coordinator reads once an hour.
    """

    _data_key = POWER_CONSUMPTION
    _extra_keys = (MONITORING,)

    def __init__(self, coordinator):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_name = "Power usage"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_power_usage"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int:
        """Return the latest power usage; the first measurement is the newest."""
        return self._value['measurements'][0]['ratio']

    @property
    def extra_state_attributes(self) -> dict:
        """Return the power and temperature history."""
        monitoring = self.coordinator.data.get(MONITORING) or {}
        return {
            "last_24h": [
                {
                    "time": m['timestamp'].isoformat(),
                    "ratio": m['ratio']
                }
                for m in self._value['measurements']
            ],
            "last_7_days": monitoring.get('daily_power', []),
            "last_12_months": monitoring.get('monthly_power', []),
            "temperature_history": monitoring.get('temperature_history', []),
        }

class EnstoNameSensor(EnstoBaseSensor):
    """Name sensor for Ensto thermostat."""

    def __init__(self, manager):
        """Initialize the sensor."""
        super().__init__(manager, "name")
        self._attr_name = "Name"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_name"
        self._attr_device_class = "name"  # Custom device class for targeting in services
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._data_key = "device_name"
        self._attr_native_value = self._manager.device_name

    async def async_update(self) -> None:
        """Fetch current device name."""
        self._attr_native_value = self._manager.device_name

class EnstoCurrentPowerSensor(EnstoCoordinatorEntity, SensorEntity):
    """Current power consumption sensor showing real-time heating power usage.

    The heating power setting while the relay is on, 0 W while it is off.
    """

    _data_key = HEATING_POWER

    def __init__(self, coordinator):
        """Initialize the current power sensor."""
        super().__init__(coordinator)

        # Set sensor properties for Home Assistant energy integration
        self._attr_name = "Current power"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_current_power"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def available(self) -> bool:
        """Return if sensor is available when heating power is configured."""
        return super().available and self._value['heating_power'] > 0

    @property
    def native_value(self) -> int:
        """Return the heating power while the relay is on, otherwise 0 W."""
        relay_active = self.coordinator.data[REAL_TIME].get("relay_active", False)
        return self._value['heating_power'] if relay_active else 0

class EnstoEnergySensor(EnstoBaseEntity, SensorEntity, RestoreEntity):
    """Energy consumption sensor (kWh) calculated from Current Power sensor."""
    
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True
    
    def __init__(self, manager):
        """Initialize the energy sensor."""
        super().__init__(manager)

        # Set sensor properties for Home Assistant energy integration
        self._attr_name = "Energy consumption"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_energy_consumption"
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        if self._attr_native_value is None:
            self._attr_native_value = 0.0

        # Initialize internal state tracking
        self._power_entity_id = None
        self._last_time = None

    async def async_added_to_hass(self) -> None:
        """Restore previous state and find linked power sensor."""
        await super().async_added_to_hass()

        # Restore energy value
        old_state = await self.async_get_last_state()
        if old_state and old_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                self._attr_native_value = float(old_state.state)
            except ValueError:
                _LOGGER.warning(
                    "Could not restore energy value for %s: invalid state %s",
                    self._attr_name, 
                    old_state.state
                )

        # Find entity_id of the linked power sensor by unique_id using entity registry
        registry = entity_registry.async_get(self.hass)
        target_unique_id = f"{dr.format_mac(self._manager.mac_address)}_current_power"

        for entry in registry.entities.values():
            if entry.unique_id == target_unique_id:
                self._power_entity_id = entry.entity_id
                _LOGGER.debug(
                    "Linked power sensor found via registry: %s",
                    self._power_entity_id
                )
                break

    async def async_update(self) -> None:
        """Update the current energy consumption value."""
        try:
            now = dt_util.utcnow()

            if not self._power_entity_id:
                return

            state = self.hass.states.get(self._power_entity_id)

            if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    current_power = float(state.state)
                except ValueError:
                    current_power = 0.0

                if self._last_time is not None:
                    time_diff = (now - self._last_time).total_seconds() / 3600.0
                    energy_used = (current_power * time_diff) / 1000.0
                    self._attr_native_value += energy_used
            
            self._last_time = now

        except Exception as e:
            _LOGGER.error("Error updating energy sensor for [%s]: %s", self._manager.mac_address, e)