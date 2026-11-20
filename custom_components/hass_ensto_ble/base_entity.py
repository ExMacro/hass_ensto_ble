"""Base entity for Ensto BLE integration."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from .const import DOMAIN
from .exceptions import EnstoBleError, EnstoNotConnectedError, error_cause

if TYPE_CHECKING:
    from .coordinator import EnstoCoordinator


def _local_time(value: datetime) -> str:
    """Return a UTC datetime as local time for error messages, e.g. 2026-11-20 08:05."""
    return dt_util.as_local(value).strftime("%Y-%m-%d %H:%M")

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

    Subclasses set _data_key, and _extra_keys for other data the entity uses
    (e.g. the heating mode for availability). The keys are passed as the
    coordinator context, so the coordinator reads them only while the entity
    is enabled.
    """
    _attr_has_entity_name = True
    _data_key: str
    _extra_keys: tuple[str, ...] = ()

    def __init__(self, coordinator: EnstoCoordinator) -> None:
        """Initialize the entity."""
        CoordinatorEntity.__init__(
            self, coordinator, context=(self._data_key, *self._extra_keys)
        )
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

    # Actions use the helpers below, so all error messages are built in one place

    def _check_connected(self) -> None:
        """Check that the thermostat is connected before an action.

        Raises:
            HomeAssistantError: The thermostat is not connected.
        """
        if not self._manager.is_connected:
            device = self._manager.device_name or self._manager.mac_address
            raise HomeAssistantError(
                f"Could not change {self.name}: {device} is not connected"
            )

    async def _read_current(
        self, read: Callable[[], Awaitable[dict[str, Any] | None]]
    ) -> dict[str, Any]:
        """Read the current settings from the thermostat.

        Actions that change one value of a characteristic read the others first,
        because the coordinator data can be up to 30 s old.

        Args:
            read: Manager read function, e.g. manager.read_boost.

        Returns:
            The settings read from the thermostat.

        Raises:
            HomeAssistantError: The read failed, with the cause in the message.
        """
        device = self._manager.device_name or self._manager.mac_address
        try:
            value = await read()
        except EnstoNotConnectedError as err:
            # The connection dropped after _check_connected()
            raise HomeAssistantError(
                f"Could not change {self.name}: {device} is not connected"
            ) from err
        except EnstoBleError as err:
            raise HomeAssistantError(
                f"Could not read the current {self.name} from {device}: "
                f"{error_cause(err.__cause__ or err)}"
            ) from err
        if value is None:
            # The device returned invalid data
            raise HomeAssistantError(
                f"Could not read the current {self.name} from {device}"
            )
        return value

    async def _write(self, write: Awaitable[None]) -> None:
        """Write to the thermostat, then read the value back.

        Args:
            write: Manager write call, e.g. manager.write_boost(...).

        Raises:
            HomeAssistantError: The write failed, with the cause in the message.
        """
        device = self._manager.device_name or self._manager.mac_address
        try:
            await write
        except EnstoNotConnectedError as err:
            # The connection dropped after _check_connected()
            raise HomeAssistantError(
                f"Could not change {self.name}: {device} is not connected"
            ) from err
        except EnstoBleError as err:
            raise HomeAssistantError(
                f"Could not write {self.name} to {device}: {error_cause(err.__cause__ or err)}"
            ) from err
        await self._async_refresh()

    def _check_vacation_not_ended(self, vacation: dict[str, Any]) -> None:
        """Check that the stored vacation period has not ended.

        The thermostat ignores vacation changes when the period has ended,
        so new dates must be set first.

        Args:
            vacation: Vacation settings from manager.read_vacation_time().

        Raises:
            ServiceValidationError: The vacation period has ended.
        """
        if vacation['time_to'] <= dt_util.utcnow():
            raise ServiceValidationError(
                f"Vacation period ended on {_local_time(vacation['time_to'])}, "
                "set new vacation dates first"
            )

    def _check_vacation_dates(self, time_from: datetime, time_to: datetime) -> None:
        """Check new vacation dates before they are written.

        The thermostat ignores a vacation that ends in the past.

        Args:
            time_from: Vacation start (UTC).
            time_to: Vacation end (UTC).

        Raises:
            ServiceValidationError: The end is in the past or not after the start.
        """
        if time_to <= dt_util.utcnow():
            raise ServiceValidationError(
                f"Vacation end ({_local_time(time_to)}) must be in the future"
            )
        if time_to <= time_from:
            raise ServiceValidationError(
                f"Vacation end ({_local_time(time_to)}) must be after "
                f"vacation start ({_local_time(time_from)})"
            )

    def _check_floor_limits(self, low: float, high: float) -> None:
        """Check that the floor temperature limits are at least 8 °C apart.

        The thermostat ignores limits that are closer to each other.

        Args:
            low: Floor temperature min in °C.
            high: Floor temperature max in °C.

        Raises:
            ServiceValidationError: The limits are less than 8 °C apart.
        """
        if high - low < 8:
            raise ServiceValidationError(
                "Floor temperature min must be at least 8 °C below max "
                f"(min {low:g} °C, max {high:g} °C)"
            )
