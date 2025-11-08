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
    CURRENCY_MAP,
)

from .config_flow import CONF_CURRENCY, DEFAULT_CURRENCY
from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

# List of supported platforms for this integration
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.SELECT, Platform.NUMBER, Platform.DATETIME]

# Set services
SERVICE_SET_TIME = "set_device_time"
SERVICE_GET_CALENDAR_DAY = "get_calendar_day"
SERVICE_SET_CALENDAR_DAY = "set_calendar_day"

GET_DAY_SCHEMA = vol.Schema({
    vol.Required("day"): vol.Range(min=1, max=7)
})

SET_DAY_SCHEMA = vol.Schema({
    vol.Required("day"): vol.Range(min=1, max=7),
    vol.Required("programs"): vol.All(vol.Length(max=6), [
        vol.Schema({
            vol.Required("start_hour"): vol.Range(min=0, max=23),
            vol.Required("start_minute"): vol.Range(min=0, max=59),
            vol.Required("end_hour"): vol.Range(min=0, max=23),
            vol.Required("end_minute"): vol.Range(min=0, max=59),
            vol.Required("temp_offset"): vol.Range(min=-20, max=20),
            vol.Required("power_offset"): vol.Range(min=-100, max=100),
            vol.Required("enabled"): bool
        })
    ])
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

        # Initialize device currency from config flow
        try:
            config_currency = entry.data.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            success = await manager.write_energy_unit(config_currency, 0.0)
            
            if not success:
                _LOGGER.warning("Failed to set device currency")
                
        except Exception as e:
            _LOGGER.warning("Failed to initialize device currency: %s", e)

        async def set_device_time(call: ServiceCall) -> None:
            """Set device time to match Home Assistant time."""

            # Get current UTC time from Home Assistant
            utc_now = dt_util.utcnow()
            
            # Extract the target entity from service call data
            target_entity = call.data.get("entity_id")
                
            if not target_entity:
                _LOGGER.error("No target entity specified")
                return

            # Handle both single entity and multiple entities if given by user
            if isinstance(target_entity, list):
                entity_ids = target_entity
            else:
                entity_ids = [target_entity]

            # Debug timezone info once (applies to all devices)
            _LOGGER.debug("Action [Set Device Time]: setting UTC time %s", utc_now.strftime('%Y-%m-%d %H:%M:%S'))

            # Process each entity
            for entity_id in entity_ids:
                # Get the entity registry entry for the target
                entity_registry = er.async_get(hass)
                entity_entry = entity_registry.async_get(entity_id)
                
                # Get config entry id from entity entry
                config_entry_id = entity_entry.config_entry_id
                
                # Get the correct thermostat manager instance for this device
                manager = hass.data[DOMAIN][config_entry_id]
                
                # Read current DST settings from the device
                current_dst_settings = await manager.read_daylight_saving()
                dst_enabled = current_dst_settings.get('enabled', False) if current_dst_settings else False

                # Calculate timezone offset based on DST setting (same logic as DST switch)
                ha_tz = dt_util.DEFAULT_TIME_ZONE
                
                if dst_enabled:
                    # DST enabled: use base timezone offset (standard time)
                    january_utc = utc_now.replace(month=1, day=15)
                    january_local = january_utc.astimezone(ha_tz)
                    tz_offset = int(january_local.utcoffset().total_seconds() / 60)

                    _LOGGER.debug("Action [Set Device Time] for [%s]: DST enabled, using base offset %d min", 
                                manager.mac_address, tz_offset)
                else:
                    # DST disabled: use current offset (includes DST if active)
                    local_now = utc_now.astimezone(ha_tz)
                    tz_offset = int(local_now.utcoffset().total_seconds() / 60)
                    _LOGGER.debug("Action [Set Device Time] for [%s]: DST disabled, using current offset %d min", 
                                manager.mac_address, tz_offset)

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
                    
                    _LOGGER.debug("Action [Set Device Time] for [%s]: successfully set time with DST=%s, offset=%d min", 
                                manager.mac_address, dst_enabled, tz_offset)
                                        
                    # Notify only datetime sensor to update
                    async_dispatcher_send(hass, SIGNAL_DATETIME_UPDATE.format(manager.mac_address))
                else:
                    _LOGGER.error("Action [Set Device Time] for [%s]: failed to set time", manager.mac_address)

        async def get_calendar_day(call: ServiceCall) -> None:
                    """Get calendar day programs service."""
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
                    
                    # Read calendar day
                    day = call.data["day"]
                    result = await manager.read_calendar_day(day)
                    
                    if result:
                        enabled_programs = [p for p in result['programs'] if p['enabled']]
                        programs_str = ", ".join([f"{p['start_hour']:02d}:{p['start_minute']:02d}-{p['end_hour']:02d}:{p['end_minute']:02d} {p['temp_offset']:+.1f}°C" for p in enabled_programs])
                        _LOGGER.debug("Updated %s Calendar Day %d for %s: %d programs loaded [%s]",
                                      manager.device_name or "Unknown Device", day, manager.mac_address,
                                      len(enabled_programs), programs_str)
                    else:
                        _LOGGER.error("Action [Get Calendar Day %d] for [%s]: failed to read", day, manager.mac_address)

        async def set_calendar_day(call: ServiceCall) -> None:
            """Set calendar day programs service."""
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
            
            # Write calendar day
            day = call.data["day"]
            programs = call.data["programs"]
            success = await manager.write_calendar_day(day, programs)
            
            if success:
                enabled_programs = [p for p in programs if p['enabled']]
                programs_str = ", ".join([f"{p['start_hour']:02d}:{p['start_minute']:02d}-{p['end_hour']:02d}:{p['end_minute']:02d} {p['temp_offset']:+.1f}°C" for p in enabled_programs])
                _LOGGER.debug("Updated %s Calendar Day %d for %s: %d programs saved [%s]",
                              manager.device_name or "Unknown Device", day, manager.mac_address,
                              len(enabled_programs), programs_str)
            else:
                _LOGGER.error("Action [Set Calendar Day %d] for [%s]: failed to write", day, manager.mac_address)

        # Only register services if they don't already exist
        if not hass.services.has_service(DOMAIN, SERVICE_SET_TIME):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SET_TIME,
                set_device_time,
            )

        if not hass.services.has_service(DOMAIN, SERVICE_GET_CALENDAR_DAY):
            hass.services.async_register(
                DOMAIN,
                SERVICE_GET_CALENDAR_DAY,
                get_calendar_day,
            )

        if not hass.services.has_service(DOMAIN, SERVICE_SET_CALENDAR_DAY):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SET_CALENDAR_DAY,
                set_calendar_day,
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
        # Remove the device data from storage file
        await manager.storage_manager.async_remove_device_data(manager.mac_address)
        await manager.cleanup()
    
    # Only remove services if this is the last config entry for the domain
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SET_TIME)
        hass.services.async_remove(DOMAIN, SERVICE_GET_CALENDAR_DAY)
        hass.services.async_remove(DOMAIN, SERVICE_SET_CALENDAR_DAY)

    return unload_ok
