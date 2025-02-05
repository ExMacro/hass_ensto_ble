"""Base entity for Ensto BLE integration."""
from homeassistant.helpers.entity import Entity
from .const import DOMAIN

class EnstoBaseEntity(Entity):
    """Base entity class for Ensto BLE."""

    def __init__(self, manager):
        """Initialize the base entity."""
        self._manager = manager

    @property
    def device_info(self):
        """Return device info for Home Assistant device registry.

        Returns a dictionary containing:
        - unique_id: MAC address as the device identifier
        - name: device name or default name with MAC
        - manufacturer: fixed value "Ensto"
        - model: model number if available
        - sw_version: software version if available
        - hw_version: hardware version if available
        """
        name = self._manager.device_name or f"Ensto Thermostat {self._manager.mac_address}"
        
        # Basic info that's always included
        info = {
            "identifiers": {(DOMAIN, self._manager.mac_address)},
            "name": name,
            "manufacturer": "Ensto",
            "model": self._manager.model_number or "model name not available",
        }
        
        # Add version info if available
        if hasattr(self._manager, "sw_version"):
            info["sw_version"] = self._manager.sw_version
        if hasattr(self._manager, "hw_version"):
            info["hw_version"] = self._manager.hw_version
            
        return info
