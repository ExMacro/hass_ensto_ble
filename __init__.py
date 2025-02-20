"""The Ensto BLE integration."""
from __future__ import annotations

import logging
import voluptuous as vol
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    SIGNAL_DATETIME_UPDATE,
)

from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# List of supported platforms for this integration
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER, Platform.DATETIME]

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
        await manager.ensure_connection()
        
        # Store the manager instance
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = manager

        # Read device information
        manager.sw_version = await manager.read_software_revision()
        manager.hw_version = await manager.read_hardware_revision()

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

            # Extract the target entity from service call data
            target_entity = call.data.get("entity_id")
                
            if not target_entity:
                _LOGGER.error("No target entity specified")
                return

            # We only process first entity if multiple are provided
            if isinstance(target_entity, list):
                entity_id = target_entity[0]
            else:
                entity_id = target_entity

            # Get the entity registry entry for the target
            entity_registry = er.async_get(hass)
            entity_entry = entity_registry.async_get(entity_id)
            
            # Get config entry id from entity entry
            config_entry_id = entity_entry.config_entry_id
            
            # Get the correct thermostat manager instance for this device
            manager = hass.data[DOMAIN][config_entry_id]
            
            # Get current UTC time from Home Assistant
            utc_now = dt_util.utcnow()

            # Get Home Assistant timezone
            ha_tz = dt_util.DEFAULT_TIME_ZONE
            _LOGGER.debug("Home Assistant timezone: %s", ha_tz)

            # Calculate timezone offset in minutes from UTC
            tz_offset = int(ha_tz.utcoffset(utc_now).total_seconds() / 60)
            _LOGGER.debug("Timezone offset in minutes: %d", tz_offset)

            # Read current DST settings from the device
            current_dst_settings = await manager.read_daylight_saving()
            dst_enabled = current_dst_settings.get('enabled', False) if current_dst_settings else False

            # Write UTC time to the device
            if await manager.write_date_and_time(
                utc_now.year,
                utc_now.month,
                utc_now.day,
                utc_now.hour,
                utc_now.minute,
                utc_now.second
            ):
                # Update timezone and DST settings while preserving DST state
                await manager.write_daylight_saving(
                    enabled=dst_enabled,
                    winter_to_summer=60,
                    summer_to_winter=60,
                    timezone_offset=tz_offset
                )
                
                # Notify only datetime sensor to update
                async_dispatcher_send(hass, SIGNAL_DATETIME_UPDATE.format(manager.mac_address))

        # Register services
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_NAME,
            set_device_name,
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
