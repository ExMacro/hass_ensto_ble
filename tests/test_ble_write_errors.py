"""Unit tests for errors raised by the GATT write primitives."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.hass_ensto_ble.base_entity import EnstoCoordinatorEntity
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
    mock_client.write_gatt_char = AsyncMock()
    manager.client = mock_client
    manager._authenticated = True
    return manager, mock_client


async def test_write_not_connected(hass: HomeAssistant) -> None:
    """Test that a write without a connection raises EnstoNotConnectedError."""
    manager = EnstoThermostatManager(hass, "AA:BB:CC:DD:EE:FF")

    with pytest.raises(EnstoNotConnectedError, match="Could not write test: not connected"):
        await manager._ble_write_unlocked("dummy-uuid", b"\x01", "test")


async def test_write_bleak_error(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a BleakError raises EnstoBleError with the cause and drops the client."""
    manager, mock_client = manager_with_mock_client
    mock_client.write_gatt_char.side_effect = BleakError("Device disconnected")

    with pytest.raises(EnstoBleError, match="Could not write test: Device disconnected") as err:
        await manager._ble_write_unlocked("dummy-uuid", b"\x01", "test")

    # The original error is kept as the cause
    assert isinstance(err.value.__cause__, BleakError)
    # The broken connection is dropped and closed on the next connect
    assert manager.client is None
    assert manager._stale_client is mock_client


async def test_write_timeout_shows_error_type(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a TimeoutError, which has no message, shows its type as the cause."""
    manager, mock_client = manager_with_mock_client
    mock_client.write_gatt_char.side_effect = TimeoutError()

    with pytest.raises(EnstoBleError, match="Could not write test: TimeoutError$"):
        await manager._ble_write_unlocked("dummy-uuid", b"\x01", "test")


async def test_split_write_stops_at_failed_packet(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that a split write raises on the first failed packet and sends no more."""
    manager, mock_client = manager_with_mock_client
    mock_client.write_gatt_char.side_effect = BleakError("Write failed")

    with pytest.raises(EnstoBleError):
        await manager._ble_write_split_unlocked("dummy-uuid", b"12345678", "split test")

    assert mock_client.write_gatt_char.call_count == 1


async def test_locked_write_raises_and_releases_lock(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that the locked wrapper passes the error on and releases the lock."""
    manager, mock_client = manager_with_mock_client
    mock_client.write_gatt_char.side_effect = BleakError("Write failed")

    with pytest.raises(EnstoBleError):
        await manager._ble_write("dummy-uuid", b"\x01", "test")
    assert not manager._gatt_lock.locked()


async def test_write_function_range_check_raises_value_error(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that an out-of-range value raises ValueError without writing."""
    manager, mock_client = manager_with_mock_client

    with pytest.raises(ValueError, match="Heating power value must be between 0 and 9999"):
        await manager.write_heating_power(10000)
    mock_client.write_gatt_char.assert_not_called()


async def test_entity_write_error_shows_cause() -> None:
    """Test that an entity action shows the cause of a failed write."""
    entity = SimpleNamespace(
        name="Heating mode",
        _manager=SimpleNamespace(device_name="Third", mac_address="AA:BB:CC:DD:EE:FF"),
        _async_refresh=AsyncMock(),
        coordinator=SimpleNamespace(lock=asyncio.Lock()),
    )

    async def failing_write() -> None:
        raise EnstoBleError("Could not write heating mode: TimeoutError") from TimeoutError()

    with pytest.raises(
        HomeAssistantError, match="^Could not write Heating mode to Third: TimeoutError$"
    ):
        await EnstoCoordinatorEntity._write(entity, failing_write())
    entity._async_refresh.assert_not_awaited()


async def test_entity_write_not_connected() -> None:
    """Test that an entity action shows a dropped connection as not connected."""
    entity = SimpleNamespace(
        name="Boost mode",
        _manager=SimpleNamespace(device_name="Second", mac_address="AA:BB:CC:DD:EE:FF"),
        _async_refresh=AsyncMock(),
        coordinator=SimpleNamespace(lock=asyncio.Lock()),
    )

    async def failing_write() -> None:
        raise EnstoNotConnectedError("Could not write boost config: not connected")

    with pytest.raises(
        HomeAssistantError, match="^Could not change Boost mode: Second is not connected$"
    ):
        await EnstoCoordinatorEntity._write(entity, failing_write())


def test_errors_are_home_assistant_errors() -> None:
    """Test that the errors are HomeAssistantErrors, so Home Assistant shows them."""
    assert issubclass(EnstoBleError, HomeAssistantError)
    assert issubclass(EnstoNotConnectedError, EnstoBleError)
