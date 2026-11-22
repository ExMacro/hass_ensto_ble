"""Unit tests for the coordinator lock between updates and entity actions (#43)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.hass_ensto_ble.base_entity import EnstoCoordinatorEntity
from custom_components.hass_ensto_ble.coordinator import VACATION, EnstoCoordinator


async def test_write_during_update_is_not_overwritten(hass: HomeAssistant) -> None:
    """Test that an update in progress can't put back a value written meanwhile."""
    device = {VACATION: {"enabled": False}}
    vacation_read = asyncio.Event()
    finish_update = asyncio.Event()

    async def read_vacation_time() -> dict:
        value = dict(device[VACATION])
        vacation_read.set()
        # The update keeps reading other characteristics when the action comes
        await finish_update.wait()
        return value

    manager = MagicMock()
    manager.mac_address = "AA:BB:CC:DD:EE:FF"
    manager.model_number = "ECO16BT"
    manager.supports_external_control.return_value = False
    manager.ensure_connection = AsyncMock()
    manager.connected_at = None
    manager._ble_read_split = AsyncMock(return_value=b"realtime")
    manager.parse_real_time_indication.return_value = {"target_temperature": 21.0}
    manager.read_vacation_time = read_vacation_time

    coordinator = EnstoCoordinator(hass, manager)
    coordinator.data = {VACATION: {"enabled": False}}
    coordinator.async_add_listener(lambda: None, context=(VACATION,))

    entity = SimpleNamespace(
        name="Vacation mode",
        _manager=SimpleNamespace(device_name="First", mac_address="AA:BB:CC:DD:EE:FF"),
        coordinator=coordinator,
        _async_refresh=lambda: coordinator.async_refresh_key(VACATION),
    )

    async def write() -> None:
        device[VACATION] = {"enabled": True}

    # The update has read the old vacation value and is still running
    update = asyncio.create_task(coordinator.async_refresh())
    await vacation_read.wait()

    # The action waits for the update instead of writing in between
    action = asyncio.create_task(EnstoCoordinatorEntity._write(entity, write()))
    await asyncio.sleep(0)
    assert device[VACATION] == {"enabled": False}

    finish_update.set()
    await update
    await action

    assert device[VACATION] == {"enabled": True}
    assert coordinator.data[VACATION] == {"enabled": True}
