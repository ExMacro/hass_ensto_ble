"""Unit tests for errors raised by the GATT read primitives and their handling."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.hass_ensto_ble.base_entity import EnstoCoordinatorEntity
from custom_components.hass_ensto_ble.coordinator import (
    BOOST,
    REAL_TIME,
    VACATION,
    EnstoCoordinator,
)
from custom_components.hass_ensto_ble.ensto_thermostat_manager import (
    EnstoThermostatManager,
)
from custom_components.hass_ensto_ble.exceptions import (
    EnstoBleError,
    EnstoNotConnectedError,
)


@pytest.fixture
def manager_with_mock_client(hass: HomeAssistant) -> tuple[EnstoThermostatManager, MagicMock]:
    """Return an EnstoThermostatManager wired to a mocked connected BleakClient."""
    manager = EnstoThermostatManager(hass, "AA:BB:CC:DD:EE:FF")
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.read_gatt_char = AsyncMock()
    manager.client = mock_client
    manager._authenticated = True
    return manager, mock_client


@pytest.fixture
def coordinator(hass: HomeAssistant) -> EnstoCoordinator:
    """Return a coordinator with a mocked manager that reads real-time data."""
    manager = MagicMock()
    manager.mac_address = "AA:BB:CC:DD:EE:FF"
    manager.model_number = "ECO16BT"
    manager.supports_external_control.return_value = False
    manager.ensure_connection = AsyncMock()
    manager.connected_at = None
    manager._ble_read_split = AsyncMock(return_value=b"realtime")
    manager.parse_real_time_indication.return_value = {"target_temperature": 21.0}
    for name in (
        "read_boost", "read_adaptive_temp_control", "read_daylight_saving",
        "read_vacation_time", "read_calendar_mode", "read_heating_mode",
        "read_room_sensor_calibration", "read_heating_power", "read_energy_unit",
        "read_date_and_time", "read_power_consumption", "read_monitoring_data",
        "read_floor_sensor_config", "read_floor_limits", "read_floor_area",
    ):
        setattr(manager, name, AsyncMock(side_effect=EnstoBleError(f"Could not read {name}: TimeoutError")))
    return EnstoCoordinator(hass, manager)


async def test_read_not_connected(hass: HomeAssistant) -> None:
    """Test that a read without a connection raises EnstoNotConnectedError."""
    manager = EnstoThermostatManager(hass, "AA:BB:CC:DD:EE:FF")

    with pytest.raises(EnstoNotConnectedError, match="Could not read test: not connected"):
        await manager._ble_read_unlocked("dummy-uuid", "test")


async def test_read_bleak_error(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a BleakError raises EnstoBleError with the cause and drops the client."""
    manager, mock_client = manager_with_mock_client
    mock_client.read_gatt_char.side_effect = BleakError("Device disconnected")

    with pytest.raises(EnstoBleError, match="Could not read test: Device disconnected"):
        await manager._ble_read("dummy-uuid", "test")

    assert manager.client is None
    assert manager._stale_client is mock_client
    assert not manager._gatt_lock.locked()


async def test_split_read_passes_error_on(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a split read raises when a packet read fails."""
    manager, mock_client = manager_with_mock_client
    mock_client.read_gatt_char.side_effect = [b"\x00abc", TimeoutError()]

    with pytest.raises(EnstoBleError, match="Could not read split test: TimeoutError$"):
        await manager._ble_read_split("dummy-uuid", "split test")


async def test_read_function_passes_error_on(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a read_* function with a catch-all still raises a BLE error."""
    manager, mock_client = manager_with_mock_client
    mock_client.read_gatt_char.side_effect = TimeoutError()

    with pytest.raises(EnstoBleError):
        await manager.read_power_consumption()


async def test_coordinator_real_time_failure_is_update_failed(
    coordinator: EnstoCoordinator,
) -> None:
    """Test that a failed real-time read becomes UpdateFailed with the cause."""
    coordinator.manager._ble_read_split.side_effect = EnstoBleError(
        "Could not read real-time indication: TimeoutError"
    )

    with pytest.raises(UpdateFailed, match="Could not read real-time indication: TimeoutError"):
        await coordinator._async_update_data()


async def test_coordinator_stops_at_first_failed_read(
    coordinator: EnstoCoordinator,
) -> None:
    """Test that the update stops at the first failed read, as the connection is dropped."""
    data = await coordinator._async_update_data()

    reads = sum(
        getattr(coordinator.manager, name).await_count
        for name in dir(coordinator.manager)
        if name.startswith("read_") and isinstance(getattr(coordinator.manager, name), AsyncMock)
    )
    assert reads == 1
    assert data == {REAL_TIME: {"target_temperature": 21.0}}


async def test_coordinator_keeps_previous_values(
    coordinator: EnstoCoordinator,
) -> None:
    """Test that a failed read keeps the values from the previous update."""
    coordinator.data = {REAL_TIME: {}, BOOST: {"enabled": True}, VACATION: {"enabled": False}}
    coordinator.async_add_listener(lambda: None, context=(BOOST, VACATION))

    data = await coordinator._async_update_data()

    assert data[BOOST] == {"enabled": True}
    assert data[VACATION] == {"enabled": False}
    assert data[REAL_TIME] == {"target_temperature": 21.0}


def _entity(name: str, device_name: str) -> SimpleNamespace:
    """Return a stand-in for an entity, with what the action helpers use."""
    return SimpleNamespace(
        name=name,
        _manager=SimpleNamespace(device_name=device_name, mac_address="AA:BB:CC:DD:EE:FF"),
    )


async def test_read_current_returns_value() -> None:
    """Test that an action gets the current settings from the read function."""
    read = AsyncMock(return_value={"enabled": True})

    value = await EnstoCoordinatorEntity._read_current(_entity("Boost mode", "First"), read)

    assert value == {"enabled": True}


async def test_read_current_error_shows_cause() -> None:
    """Test that a failed read before an action shows the cause."""
    read = AsyncMock(
        side_effect=EnstoBleError("Could not read boost config: TimeoutError")
    )
    read.side_effect.__cause__ = TimeoutError()

    with pytest.raises(
        HomeAssistantError,
        match="^Could not read the current Boost mode from First: TimeoutError$",
    ):
        await EnstoCoordinatorEntity._read_current(_entity("Boost mode", "First"), read)


async def test_read_current_not_connected() -> None:
    """Test that a dropped connection before an action shows as not connected."""
    read = AsyncMock(
        side_effect=EnstoNotConnectedError("Could not read boost config: not connected")
    )

    with pytest.raises(
        HomeAssistantError, match="^Could not change Boost mode: First is not connected$"
    ):
        await EnstoCoordinatorEntity._read_current(_entity("Boost mode", "First"), read)


async def test_read_current_invalid_data() -> None:
    """Test that invalid data from the device stops the action."""
    read = AsyncMock(return_value=None)

    with pytest.raises(
        HomeAssistantError, match="^Could not read the current Boost mode from First$"
    ):
        await EnstoCoordinatorEntity._read_current(_entity("Boost mode", "First"), read)


async def test_refresh_key_keeps_value_on_failure(
    coordinator: EnstoCoordinator,
) -> None:
    """Test that a failed read after a write keeps the previous value."""
    coordinator.data = {BOOST: {"enabled": True}}

    await coordinator.async_refresh_key(BOOST)

    assert coordinator.data[BOOST] == {"enabled": True}
