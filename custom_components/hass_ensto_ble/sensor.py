"""Support for Ensto BLE sensors."""
import logging
from datetime import datetime, timedelta

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
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers import device_registry as dr
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers import entity_registry

from .const import DOMAIN, REAL_TIME_INDICATION_UUID, SCAN_INTERVAL
from .base_entity import EnstoBaseEntity

_LOGGER = logging.getLogger(__name__)

UNIT_MINUTES = "min"

class EnstoBaseSensor(EnstoBaseEntity, SensorEntity):
    """Base class for Ensto sensors."""
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager, sensor_type):
        """Initialize the DateTime sensor for Ensto thermostat."""
        super().__init__(manager)
        self._sensor_type = sensor_type
        self._attr_should_poll = True
        self._last_parsed_data = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to updates."""
        async def _update_immediately(*args):
            """Force immediate update."""
            await self.async_update()
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"ensto_update_{self._manager.mac_address}",
                _update_immediately
            )
        )

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            coordinator = self._manager.get_real_time_coordinator()
            parsed_data = await coordinator.get_real_time_data()

            if parsed_data:
                self._last_parsed_data = parsed_data
                self._attr_native_value = parsed_data[self._data_key]
                
            _LOGGER.debug(
                "Updated %s for %s: %s",
                self._attr_name,
                self._manager.mac_address,
                self._attr_native_value
            )

        except Exception as e:
            _LOGGER.error("Error updating sensor: %s", e)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    manager = hass.data[DOMAIN][entry.entry_id]
    
    # Check floor sensor availability
    data = await manager.read_split_characteristic(REAL_TIME_INDICATION_UUID)
    sensors = []
    
    if data:
        parsed_data = manager.parse_real_time_indication(data)
        
        # Add sensors
        sensors.extend([
            EnstoTemperatureSensor(manager, "room"),
            EnstoTemperatureSensor(manager, "target"),
            EnstoStateSensor(manager, "relay"),
            EnstoStateSensor(manager, "boost"),
            EnstoModeSensor(manager, "active"),
            EnstoModeSensor(manager, "heating"),
            EnstoNumberSensor(manager, "boost_setpoint"),
            EnstoNumberSensor(manager, "boost_remaining"),
            EnstoNumberSensor(manager, "alarm"),
            EnstoDateTimeSensor(manager),
            EnstoPowerConsumptionSensor(manager),
            EnstoNameSensor(manager),
            EnstoCurrentPowerSensor(manager),
            EnstoEnergySensor(manager),
        ])

        # Add floor sensor only if value exists and is non-zero
        if parsed_data.get("floor_temperature", 0) != 0:
            sensors.append(EnstoTemperatureSensor(manager, "floor"))
    
    async_add_entities(sensors, True)

class EnstoTemperatureSensor(EnstoBaseSensor):
    """Temperature sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the temperature sensor."""

        super().__init__(manager, sensor_type)
        
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

class EnstoStateSensor(EnstoBaseSensor):
    """State sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
        if sensor_type == "relay":
            self._attr_name = "Relay state"
            self._data_key = "relay_active"
        else:
            self._attr_name = "Boost state"
            self._data_key = "boost_enabled"

        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}_state"

class EnstoModeSensor(EnstoBaseSensor):
    """Mode sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
        if sensor_type == "active":
            self._attr_name = "Active mode"
            self._data_key = "active_mode"
        else:
            self._attr_name = "Heating mode"
            self._data_key = "heating_mode"

        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_{sensor_type}_mode"

class EnstoNumberSensor(EnstoBaseSensor):
    """Number sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
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
            try:
                if self._last_parsed_data is None:
                    return None
                    
                active_alarms = self._last_parsed_data.get(self._active_alarms_key, [])
                alarm_code = self._last_parsed_data.get(self._data_key, 0)

                if not active_alarms:
                    return "No active errors"
                return f"Error {alarm_code}: {', '.join(active_alarms)}"
            except Exception as e:
                _LOGGER.error("Error formatting alarm status: %s", e)
                return None

        return self._attr_native_value  # Default behavior for other number sensors

class EnstoDateTimeSensor(EnstoBaseSensor):
    """DateTime sensor for Ensto thermostat."""

    def __init__(self, manager):
        """Initialize the sensor."""
        super().__init__(manager, "datetime")
        self._attr_name = "Date and time"
        # Create a unique ID for the sensor using MAC address
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_datetime"
        self._attr_native_value = None
        # Track if alert is currently shown
        self._alert_shown = False

    async def async_added_to_hass(self) -> None:
            """Subscribe to updates."""
            async def _update_immediately(*args):
                """Force immediate update."""
                await self.async_update()
                self.async_write_ha_state()

            # Subscribe to general updates
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"ensto_update_{self._manager.mac_address}",
                    _update_immediately
                )
            )

            # Subscribe to datetime specific updates
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    f"ensto_datetime_update_{self._manager.mac_address}",
                    _update_immediately
                )
            )

    async def async_update(self) -> None:
        """Fetch new state data for the sensor.
        
        The device internally operates in UTC time and handles DST/timezone conversions
        based on its own settings. We read UTC time from device and compare it with
        HA's UTC time to detect mismatches.
        """
        try:
            # Get current date and time from the device (in UTC)
            data = await self._manager.read_date_and_time()
            if data:
                # Create datetime object from device data (in UTC)
                device_utc = datetime(
                    data['year'], data['month'], data['day'],
                    data['hour'], data['minute'], data['second'],
                    tzinfo=dt_util.UTC  # Mark explicitly as UTC
                )
                
                # Convert UTC time from device to local time for display
                # This affects both UI and history - timestamps are stored in local time
                device_local = dt_util.as_local(device_utc)
                self._attr_native_value = device_local.strftime("%-d.%-m.%Y %-H:%M")

                # Get HA time in UTC for proper comparison
                ha_utc = dt_util.utcnow()
                time_diff = abs(ha_utc - device_utc)
                
                # Show notification if time difference is more than 1 minute
                if time_diff > timedelta(minutes=1):
                    if not self._alert_shown:
                        # Get device name for notification
                        device_name = self._manager.device_name or "Unknown Device"
                        
                        await self.hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "title": f"Time Mismatch Detected - {device_name}",
                                "message": (
                                    f"Device {device_name} ({self._manager.mac_address}) time "
                                    f"(UTC: {device_utc.strftime('%-d.%-m.%Y %-H:%M:%S')}) "
                                    f"differs from Home Assistant time "
                                    f"(UTC: {ha_utc.strftime('%-d.%-m.%Y %-H:%M:%S')}). "
                                    "Use the Set device time service in Developer tools to synchronize."
                                ),
                                "notification_id": f"ensto_time_{self._manager.mac_address}"
                            }
                        )
                        self._alert_shown = True
                else:
                    # Reset alert flag if times are in sync
                    self._alert_shown = False
                        
        except Exception as e:
            _LOGGER.error("Error updating datetime: %s", e)

class EnstoPowerConsumptionSensor(EnstoBaseEntity, SensorEntity):
    """Sensor for monitoring power consumption."""

    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the sensor."""
        super().__init__(manager)
        self._attr_name = "Power usage"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_power_usage"
        self._attr_native_unit_of_measurement = "%"
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_value = None
        self._attr_extra_state_attributes = {
            "last_24h": [],
            "last_7_days": [],
            "last_12_months": [],
            "temperature_history": []
        }

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            # Get real-time power consumption
            result = await self._manager.read_power_consumption()
            if result and result['measurements']:
                # Set latest value as the main state
                current = result['measurements'][0]  # First measurement is newest
                self._attr_native_value = current['ratio']
                
                # Update last 24h history
                self._attr_extra_state_attributes["last_24h"] = [
                    {
                        "time": m['timestamp'].isoformat(),
                        "ratio": m['ratio']
                    }
                    for m in result['measurements']
                ]

            # Get historical monitoring data
            monitoring_data = await self._manager.read_monitoring_data()
            if monitoring_data:
                self._attr_extra_state_attributes["last_7_days"] = monitoring_data['daily_power']
                self._attr_extra_state_attributes["last_12_months"] = monitoring_data['monthly_power']
                self._attr_extra_state_attributes["temperature_history"] = monitoring_data['temperature_history']

        except Exception as e:
            _LOGGER.error("Error updating power consumption sensor: %s", e)

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

class EnstoCurrentPowerSensor(EnstoBaseEntity, SensorEntity):
    """Current power consumption sensor showing real-time heating power usage."""
    
    _attr_scan_interval = SCAN_INTERVAL
    _attr_has_entity_name = True

    def __init__(self, manager):
        """Initialize the current power sensor."""
        super().__init__(manager)
        
        # Set sensor properties for Home Assistant energy integration
        self._attr_name = "Current power"
        self._attr_unique_id = f"{dr.format_mac(self._manager.mac_address)}_current_power"
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        
        # Initialize internal state tracking
        self._heating_power = None

    @property
    def available(self) -> bool:
        """Return if sensor is available when heating power is configured."""
        return self._heating_power is not None and self._heating_power > 0

    async def async_update(self) -> None:
        """Update the current power consumption value."""
        # Read heating power setting
        heating_power_result = await self._manager.read_heating_power()
        if heating_power_result:
            self._heating_power = heating_power_result['heating_power']
        
        # Calculate power if heating power is configured
        if self._heating_power and self._heating_power > 0:
            data = await self._manager.read_split_characteristic(REAL_TIME_INDICATION_UUID)
            if data:
                parsed_data = self._manager.parse_real_time_indication(data)
                relay_active = parsed_data.get("relay_active", False)
                self._attr_native_value = self._heating_power if relay_active else 0
            else:
                self._attr_native_value = None
        else:
            self._attr_native_value = None

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