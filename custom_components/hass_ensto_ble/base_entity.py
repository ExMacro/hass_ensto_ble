"""Base entity for Ensto BLE integration."""
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from .const import DOMAIN

class EnstoBaseEntity(Entity):
    """Base entity class for Ensto BLE."""

    def __init__(self, manager):
        """Initialize the base entity."""
        self._manager = manager

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for Home Assistant device registry.

        Contains:
        - identifiers: MAC address as the device identifier
        - name: device name or default name with MAC
        - manufacturer: fixed value "Ensto"
        - model: model number if available
        - sw_version: software version if available
        - hw_version: hardware version if available
        """
        name = self._manager.device_name or f"Ensto Thermostat {self._manager.mac_address}"

        # Keyword arguments work with both the TypedDict (before 2026.11) and the dataclass
        return DeviceInfo(
            identifiers={(DOMAIN, self._manager.mac_address)},
            name=name,
            manufacturer="Ensto",
            model=self._manager.model_number or "model name not available",
            sw_version=getattr(self._manager, "sw_version", None),
            hw_version=getattr(self._manager, "hw_version", None),
        )
