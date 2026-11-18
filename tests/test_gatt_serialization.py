"""Unit tests for GATT serialization and split read/write deadlock prevention."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.hass_ensto_ble.ensto_thermostat_manager import (
    EnstoThermostatManager,
)


@pytest.fixture
def manager_with_mock_client(hass: HomeAssistant) -> tuple[EnstoThermostatManager, MagicMock]:
    """Return an EnstoThermostatManager wired to a mocked connected BleakClient."""
    manager = EnstoThermostatManager(hass, "AA:BB:CC:DD:EE:FF")
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.read_gatt_char = AsyncMock()
    mock_client.write_gatt_char = AsyncMock()
    manager.client = mock_client
    manager._authenticated = True
    return manager, mock_client


async def test_single_read_acquires_lock(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test single GATT read executes and releases the lock."""
    manager, mock_client = manager_with_mock_client
    mock_client.read_gatt_char.return_value = b"\x01\x02"
    assert not manager._gatt_lock.locked()
    result = await manager._ble_read("dummy-uuid", "test")
    assert result == b"\x01\x02"
    assert not manager._gatt_lock.locked()


async def test_single_write_acquires_lock(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test single GATT write executes and releases the lock."""
    manager, mock_client = manager_with_mock_client
    mock_client.write_gatt_char.return_value = None
    assert not manager._gatt_lock.locked()
    success = await manager._ble_write("dummy-uuid", b"\x01", "test")
    assert success is True
    assert not manager._gatt_lock.locked()


async def test_split_read_does_not_deadlock(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that split read completes under GATT lock without deadlocking."""
    manager, mock_client = manager_with_mock_client
    mock_client.read_gatt_char.side_effect = [
        b"\x00abc",
        b"\x40def\x00\x00",
    ]

    result = await asyncio.wait_for(
        manager._ble_read_split("dummy-uuid", "split test"),
        timeout=2.0,
    )
    assert result == b"abcdef"
    assert not manager._gatt_lock.locked()


async def test_split_write_does_not_deadlock(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that split write completes under GATT lock without deadlocking."""
    manager, mock_client = manager_with_mock_client
    payload = b"12345678"
    success = await asyncio.wait_for(
        manager._ble_write_split("dummy-uuid", payload, "split write test"),
        timeout=2.0,
    )
    assert success is True
    assert mock_client.write_gatt_char.call_count == 2
    assert not manager._gatt_lock.locked()


async def test_concurrent_reads_serialize(
    manager_with_mock_client: tuple[EnstoThermostatManager, MagicMock],
) -> None:
    """Test that concurrent _ble_read calls serialize properly."""
    manager, mock_client = manager_with_mock_client
    execution_order: list[str] = []

    async def slow_read(uuid: str) -> bytes:
        execution_order.append(f"start_{uuid}")
        await asyncio.sleep(0.05)
        execution_order.append(f"end_{uuid}")
        return b"ok"

    mock_client.read_gatt_char.side_effect = slow_read

    task1 = asyncio.create_task(manager._ble_read("uuid1", "read 1"))
    task2 = asyncio.create_task(manager._ble_read("uuid2", "read 2"))

    await asyncio.gather(task1, task2)

    assert len(execution_order) == 4
    assert execution_order[0][:5] == "start"
    assert execution_order[1][:3] == "end"
    assert execution_order[2][:5] == "start"
    assert execution_order[3][:3] == "end"
    assert execution_order[0][6:] == execution_order[1][4:]
    assert execution_order[2][6:] == execution_order[3][4:]
