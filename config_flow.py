"""Config flow for Ensto BLE integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN
from .ensto_thermostat_manager import EnstoThermostatManager

_LOGGER = logging.getLogger(__name__)

class EnstoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ensto BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices = {}
        self._mac_address = None
        self._manager = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step.
        
        If user_input is None, scans for devices in pairing mode and shows device selection form.
        If user_input contains MAC address, attempts to connect and verify the device.
        """
        if user_input is not None:
            self._mac_address = user_input["Please select an Ensto BLE device in pairing mode"]
            
            # Initialize manager and get device info
            self._manager = EnstoThermostatManager(self.hass, self._mac_address)
            self._manager.setup()
            
            # Try to connect and authenticate the device
            if not await self._manager.connect_and_verify():
                return self.async_abort(
                    reason="Connection and authentication with the device failed. Please try again."
                )
            
            # Create config entry with device info
            model = self._manager.model_number or "Unknown Model"
            name = self._manager.device_name or self._mac_address
            title = f"{model} {name}"
            
            return self.async_create_entry(
                title=title,
                data={
                    "mac_address": self._mac_address,
                }
            )

        # Initialize manager for device scanning
        manager = EnstoThermostatManager(self.hass, "")  # Empty MAC for scanning mode
        manager.setup()
        
        # Scan for devices that are in pairing mode
        pairing_devices = manager.find_devices_in_pairing_mode()

        if not pairing_devices:
            return self.async_abort(
                reason="No Ensto BLE devices in pairing mode. Hold BLE reset button for >0.5 seconds. Blue LED will blink."
            )

        # Create a mapping of MAC addresses to device names for the selection form
        self._discovered_devices = {
            addr: f"{device.name} ({addr})"
            for addr, (device, _) in pairing_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("Please select an Ensto BLE device in pairing mode"): vol.In(self._discovered_devices)
                }
            ),
            description_placeholders={
                "devices_found": "\n".join(
                    f"- {name}" for name in self._discovered_devices.values()
                )
            }
        )
