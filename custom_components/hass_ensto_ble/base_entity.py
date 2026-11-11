"""Base entity for Ensto BLE integration."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import EnstoCoordinator

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


class EnstoCoordinatorEntity(CoordinatorEntity["EnstoCoordinator"], EnstoBaseEntity):
    """Base class for entities that show a value read by the coordinator.

    Subclasses set _data_key. It is passed as the coordinator context, so the
    coordinator reads the characteristic only while the entity is enabled.
    """
    _attr_has_entity_name = True
    _data_key: str

    def __init__(self, coordinator: EnstoCoordinator) -> None:
        """Initialize the entity."""
        CoordinatorEntity.__init__(self, coordinator, context=self._data_key)
        EnstoBaseEntity.__init__(self, coordinator.manager)

    @property
    def _value(self) -> Any:
        """Return the latest value read for this entity."""
        return self.coordinator.data.get(self._data_key)

    @property
    def available(self) -> bool:
        """Return True when the coordinator has data for this entity."""
        return super().available and self._value is not None

    async def _async_refresh(self) -> None:
        """Read the characteristic again after a write, so the state shows the device."""
        await self.coordinator.async_refresh_key(self._data_key)
