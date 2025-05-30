"""Storage management for Ensto BLE devices."""
from homeassistant.helpers.storage import Store
from homeassistant.core import HomeAssistant
import logging

_LOGGER = logging.getLogger(__name__)

# Storage version and key configuration. Version is incremented for breaking changes,
# minor version for non-breaking changes in storage structure
STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 1
STORAGE_KEY = "ensto_ble_devices"

class EnstoStorageManager:
    """Class to manage Ensto device data storage."""
    
    def __init__(self, hass: HomeAssistant):
        """Initialize storage manager."""
        self.store = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY,
            minor_version=STORAGE_MINOR_VERSION
        )
        
    async def async_save_device_data(self, mac_address: str, factory_reset_id: int) -> None:
        """Save device data to storage."""
        current_data = await self.store.async_load() or {}
        
        current_data[mac_address] = {
            "factory_reset_id": factory_reset_id
        }
        
        await self.store.async_save(current_data)
        _LOGGER.debug("Saved device data for %s", mac_address)
        
    async def async_load_device_data(self, mac_address: str) -> dict:
        """Load device data from storage."""
        data = await self.store.async_load()
        if data and mac_address in data:
            return data[mac_address]
        return None

    async def async_remove_device_data(self, mac_address: str) -> None:
        """Remove specific device data from storage."""
        try:
            current_data = await self.store.async_load() or {}
            
            if mac_address in current_data:
                del current_data[mac_address]
                
                # If there are still other devices, save the updated data
                if current_data:
                    await self.store.async_save(current_data)
                    _LOGGER.debug("Removed device data for %s, other devices remain", mac_address)
                else:
                    # If no devices left, remove the entire storage file
                    await self.store.async_remove()
                    _LOGGER.debug("Removed storage file %s as no devices remain", STORAGE_KEY)
            else:
                _LOGGER.debug("Device %s not found in storage", mac_address)
                
        except Exception as e:
            _LOGGER.error("Error removing device data for %s: %s", mac_address, str(e))
