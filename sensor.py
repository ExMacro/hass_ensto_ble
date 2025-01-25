"""Support for Ensto BLE sensors."""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, SIGNAL_ENSTO_UPDATE, REAL_TIME_INDICATION_UUID, SCAN_INTERVAL

from .base_entity import EnstoBaseEntity

_LOGGER = logging.getLogger(__name__)

UNIT_MINUTES = "min"

class EnstoBaseSensor(EnstoBaseEntity, SensorEntity):
    """Base class for Ensto sensors."""
    _attr_scan_interval = SCAN_INTERVAL

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
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
                SIGNAL_ENSTO_UPDATE.format(self._manager.mac_address),
                _update_immediately
            )
        )

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        try:
            data = await self._manager.read_split_characteristic(REAL_TIME_INDICATION_UUID)
            if data:
                parsed_data = self._manager.parse_real_time_indication(data)
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
        ])

        # Add floor sensor only if value exists and is non-zero
        if parsed_data.get("floor_temperature", 0) != 0:
            sensors.append(EnstoTemperatureSensor(manager, "floor"))
    
    async_add_entities(sensors, True)

class EnstoTemperatureSensor(EnstoBaseSensor):
    """Temperature sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        
        if sensor_type == "room":
            self._attr_name = "Ensto Room Temperature"
            self._data_key = "room_temperature"
        elif sensor_type == "floor":
            self._attr_name = "Ensto Floor Temperature"
            self._data_key = "floor_temperature"
        else:  # target
            self._attr_name = "Ensto Target Temperature"
            self._data_key = "target_temperature"
            
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_{sensor_type}_temp"

class EnstoStateSensor(EnstoBaseSensor):
    """State sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
        if sensor_type == "relay":
            self._attr_name = "Ensto Relay State"
            self._data_key = "relay_active"
        else:  # boost
            self._attr_name = "Ensto Boost State"
            self._data_key = "boost_enabled"
            
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_{sensor_type}_state"

class EnstoModeSensor(EnstoBaseSensor):
    """Mode sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
        if sensor_type == "active":
            self._attr_name = "Ensto Active Mode"
            self._data_key = "active_mode"
        else:  # heating
            self._attr_name = "Ensto Heating Mode"
            self._data_key = "heating_mode"
            
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_{sensor_type}_mode"

class EnstoNumberSensor(EnstoBaseSensor):
    """Number sensor for Ensto thermostat."""

    def __init__(self, manager, sensor_type):
        """Initialize the sensor."""
        super().__init__(manager, sensor_type)
        
        if "boost" in sensor_type:
            self._attr_native_unit_of_measurement = UNIT_MINUTES
            if sensor_type == "boost_setpoint":
                self._attr_name = "Ensto Boost Setpoint"
                self._data_key = "boost_setpoint_minutes"
            else:  # boost_remaining
                self._attr_name = "Ensto Boost Remaining"
                self._data_key = "boost_remaining_minutes"
        else:  # alarm
            self._attr_name = "Ensto Alarm Status"
            self._data_key = "alarm_code"
            self._active_alarms_key = "active_alarms"
            
        self._attr_unique_id = f"ensto_{self._manager.mac_address}_{sensor_type}"

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
                    return f"No active errors"
                return f"Error {alarm_code}: {', '.join(active_alarms)}"
            except Exception as e:
                _LOGGER.error("Error formatting alarm status: %s", e)
                return None

        return self._attr_native_value  # Default behavior for other number sensors
