"""The Ensto BLE integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from .const import (
    DOMAIN,
)

from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# List of supported platforms for this integration
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER]

# Set device name service
SERVICE_SET_NAME = "set_device_name"
SERVICE_SET_TIME = "set_device_time"
SERVICE_SET_NAME_SCHEMA = vol.Schema({
    vol.Required("name"): str,
})

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ensto BLE from a config entry."""
    try:
        # Initialize the thermostat manager
        manager = EnstoThermostatManager(hass, entry.data["mac_address"])
        
        # Setup scanner and verify connection
        manager.setup()
        if not await manager.connect_and_verify():
            raise ConfigEntryNotReady("Failed to verify device connection")
        
        # Store the manager instance
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = manager

        # Update config entry title with current info
        title = f"{manager.model_number or 'Unknown Model'} {manager.device_name or entry.data['mac_address']}"
        hass.config_entries.async_update_entry(entry, title=title)

        async def set_device_name(call: ServiceCall) -> None:
            """Set device name service."""
            new_name = call.data["name"]
            if await manager.write_device_name(new_name):
                manager.device_name = new_name
                # Update config entry title
                title = f"{manager.model_number or 'Unknown Model'} {new_name}"
                hass.config_entries.async_update_entry(entry, title=title)
                # Force update device info
                async_dispatcher_send(hass, f"{DOMAIN}_update")

        async def set_device_time(call: ServiceCall) -> None:
            """Set device time to match Home Assistant time."""
            current_time = datetime.now()
            if await manager.write_date_and_time(
                current_time.year,
                current_time.month,
                current_time.day,
                current_time.hour,
                current_time.minute,
                current_time.second
            ):
                # Force update device info
                async_dispatcher_send(hass, f"{DOMAIN}_update")

        # Register services
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_NAME,
            set_device_name,
            schema=SERVICE_SET_NAME_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TIME,
            set_device_time,
        )

        # Set up the platforms
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        
        return True
        
    except Exception as ex:
        _LOGGER.error("Error setting up Ensto BLE: %s", str(ex))
        raise ConfigEntryNotReady from ex

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        manager = hass.data[DOMAIN].pop(entry.entry_id)
        # Remove the  storage file
        await manager.storage_manager.async_remove_storage()
        await manager.cleanup()
    
    # Remove the services
    hass.services.async_remove(DOMAIN, SERVICE_SET_NAME)
    hass.services.async_remove(DOMAIN, SERVICE_SET_TIME)

    return unload_ok
