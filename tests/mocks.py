"""Shared mocks for Home Assistant and Bleak for testing without HA installed."""
import sys
import types
import importlib.machinery
from unittest.mock import MagicMock, AsyncMock

def mock_module(name: str, is_pkg: bool = False):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, None, is_package=is_pkg)
    if is_pkg:
        mod.__path__ = []
        mod.__package__ = name
    sys.modules[name] = mod
    return mod

# Create module structure
for pkg in ["homeassistant", "homeassistant.components", "homeassistant.helpers", "homeassistant.util", "bleak", "dateutil"]:
    mock_module(pkg, is_pkg=True)

for mod_name in [
    "voluptuous",
    "bleak.exc",
    "bleak_retry_connector",
    "homeassistant.components.bluetooth",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.sensor",
    "homeassistant.components.number",
    "homeassistant.components.switch",
    "homeassistant.components.select",
    "homeassistant.components.datetime",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.data_entry_flow",
    "homeassistant.util.dt",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.restore_state",
    "homeassistant.helpers.dispatcher",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.update_coordinator",
    "dateutil.relativedelta",
]:
    mock_module(mod_name)

sys.modules["bleak.exc"].BleakError = type("BleakError", (Exception,), {})
sys.modules["bleak"].BleakClient = MagicMock()
sys.modules["bleak_retry_connector"].BleakClientWithServiceCache = MagicMock()
sys.modules["bleak_retry_connector"].establish_connection = AsyncMock()

class Entity:
    _attr_should_poll = True
    def __init__(self, *args, **kwargs):
        pass
    @property
    def should_poll(self):
        return getattr(self, "_attr_should_poll", True)
    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)
    def async_on_remove(self, cb):
        pass
    def async_write_ha_state(self):
        pass

from typing import Generic, TypeVar
_T = TypeVar("_T")

class DataUpdateCoordinator(Generic[_T]):
    def __init__(self, hass, logger, name, update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True
        self._listeners = []

    def async_add_listener(self, update_callback):
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    async def async_refresh(self):
        await self._async_refresh()

    async def _async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
            for listener in list(self._listeners):
                listener()
        except Exception:
            self.last_update_success = False

    async def async_config_entry_first_refresh(self):
        await self._async_refresh()

    async def async_request_refresh(self):
        await self._async_refresh()

class UpdateFailed(Exception):
    pass

class CoordinatorEntity(Entity):
    _attr_should_poll = False
    def __init__(self, coordinator, **kwargs):
        super().__init__(**kwargs)
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    def async_on_remove(self, cb):
        pass

    def async_write_ha_state(self):
        pass

sys.modules["homeassistant.helpers.update_coordinator"] = types.ModuleType("homeassistant.helpers.update_coordinator")
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = DataUpdateCoordinator
sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity
sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = UpdateFailed

class Platform:
    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    SWITCH = "switch"
    SELECT = "select"
    NUMBER = "number"
    DATETIME = "datetime"

sys.modules["homeassistant.const"].Platform = Platform
sys.modules["homeassistant.const"].UnitOfTemperature = MagicMock()
sys.modules["homeassistant.const"].UnitOfPower = MagicMock()
sys.modules["homeassistant.const"].UnitOfEnergy = MagicMock()
sys.modules["homeassistant.const"].STATE_UNKNOWN = "unknown"
sys.modules["homeassistant.const"].STATE_UNAVAILABLE = "unavailable"

sys.modules["homeassistant.exceptions"].ConfigEntryNotReady = type("ConfigEntryNotReady", (Exception,), {})
sys.modules["homeassistant.exceptions"].HomeAssistantError = type("HomeAssistantError", (Exception,), {})
sys.modules["homeassistant.exceptions"].ServiceValidationError = type("ServiceValidationError", (Exception,), {})

sys.modules["voluptuous"].Schema = MagicMock()
sys.modules["voluptuous"].Required = MagicMock()
sys.modules["voluptuous"].Range = MagicMock()
sys.modules["voluptuous"].All = MagicMock()
sys.modules["voluptuous"].Length = MagicMock()
sys.modules["voluptuous"].ALLOW_EXTRA = True

sys.modules["homeassistant.config_entries"].ConfigEntry = MagicMock
sys.modules["homeassistant.config_entries"].ConfigEntryState = MagicMock

class ConfigFlow:
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

sys.modules["homeassistant.config_entries"].ConfigFlow = ConfigFlow
sys.modules["homeassistant.data_entry_flow"].FlowResult = MagicMock
sys.modules["homeassistant.core"].HomeAssistant = MagicMock
sys.modules["homeassistant.core"].ServiceCall = MagicMock

class DummyStore:
    def __init__(self, *args, **kwargs):
        pass
    async def async_load(self):
        return None
    async def async_save(self, data):
        pass

sys.modules["homeassistant.helpers.storage"].Store = DummyStore
sys.modules["dateutil.relativedelta"].relativedelta = MagicMock

# Component entity bases
class SensorEntity(Entity):
    _attr_native_value = None

class BinarySensorEntity(Entity):
    pass

class RestoreEntity(Entity):
    pass

class NumberEntity(Entity):
    pass

class SwitchEntity(Entity):
    pass

class SelectEntity(Entity):
    pass

class DateTimeEntity(Entity):
    pass

sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = MagicMock
sys.modules["homeassistant.helpers.device_registry"].format_mac = lambda mac: mac.lower().replace("-", ":")
sys.modules["homeassistant.helpers.device_registry"].CONNECTION_NETWORK_MAC = "mac"
sys.modules["homeassistant.helpers.entity"].Entity = Entity
sys.modules["homeassistant.helpers.entity"].EntityCategory = MagicMock()
sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = MagicMock
sys.modules["homeassistant.helpers.restore_state"].RestoreEntity = RestoreEntity
sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_connect = MagicMock()
sys.modules["homeassistant.helpers.dispatcher"].async_dispatcher_send = MagicMock()
sys.modules["homeassistant.components.binary_sensor"].BinarySensorEntity = BinarySensorEntity
sys.modules["homeassistant.components.binary_sensor"].BinarySensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorEntity = SensorEntity
sys.modules["homeassistant.components.sensor"].SensorDeviceClass = MagicMock()
sys.modules["homeassistant.components.sensor"].SensorStateClass = MagicMock()
sys.modules["homeassistant.components.number"].NumberEntity = NumberEntity
sys.modules["homeassistant.components.number"].NumberDeviceClass = MagicMock()
sys.modules["homeassistant.components.switch"].SwitchEntity = SwitchEntity
sys.modules["homeassistant.components.select"].SelectEntity = SelectEntity
sys.modules["homeassistant.components.datetime"].DateTimeEntity = DateTimeEntity

sys.modules["homeassistant.components.bluetooth"].async_get_scanner = MagicMock()
sys.modules["homeassistant.components.bluetooth"].async_ble_device_from_address = MagicMock()
sys.modules["homeassistant.components.bluetooth"].async_scanner_devices_by_address = MagicMock(return_value=[])
sys.modules["homeassistant.helpers.entity_registry"].async_get = MagicMock()
