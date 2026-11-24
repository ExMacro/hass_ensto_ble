"""Unit tests for keeping the thermostat time zone at Home Assistant's (#42)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.hass_ensto_ble.coordinator import (
    DAYLIGHT_SAVING,
    EnstoCoordinator,
    has_daylight_saving,
    standard_utc_offset,
)
from custom_components.hass_ensto_ble.exceptions import EnstoBleError


def _dst_config(enabled: bool, offset: int) -> dict:
    return {
        'enabled': enabled,
        'winter_to_summer_offset': 0,
        'summer_to_winter_offset': 0,
        'timezone_offset': offset,
    }


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> EnstoCoordinator:
    """Return a coordinator in Europe/Helsinki whose entities use no other data."""
    await hass.config.async_set_time_zone("Europe/Helsinki")
    manager = MagicMock()
    manager.mac_address = "AA:BB:CC:DD:EE:FF"
    manager.device_name = "First"
    manager.model_number = "ECO16BT"
    manager.supports_external_control.return_value = False
    manager.connected_at = 1.0
    manager._ble_read_split = AsyncMock(return_value=b"realtime")
    manager.parse_real_time_indication.return_value = {"target_temperature": 21.0}
    manager.read_daylight_saving = AsyncMock(return_value=_dst_config(True, 120))
    manager.write_daylight_saving = AsyncMock()
    coordinator = EnstoCoordinator(hass, manager)
    # Not the first update, and no entity uses other data
    coordinator.data = {}
    return coordinator


async def test_time_zone_helpers(hass: HomeAssistant) -> None:
    """Test the standard offset and summer time detection."""
    await hass.config.async_set_time_zone("Europe/Helsinki")
    assert standard_utc_offset() == 120
    assert has_daylight_saving()

    await hass.config.async_set_time_zone("UTC")
    assert standard_utc_offset() == 0
    assert not has_daylight_saving()


async def test_wrong_offset_is_corrected(
    coordinator: EnstoCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a summer offset left by old versions is corrected and logged."""
    manager = coordinator.manager
    manager.read_daylight_saving.return_value = _dst_config(True, 180)

    with caplog.at_level(logging.INFO):
        data = await coordinator._read_data()

    manager.write_daylight_saving.assert_awaited_once_with(
        enabled=True, winter_to_summer=0, summer_to_winter=0, timezone_offset=120
    )
    assert data[DAYLIGHT_SAVING]['timezone_offset'] == 120
    assert "Corrected time zone offset on First (AA:BB:CC:DD:EE:FF) from 180 to 120 min" in caplog.text


async def test_correction_keeps_automatic_dst_off(coordinator: EnstoCoordinator) -> None:
    """Test that correcting the offset leaves the user's daylight saving choice."""
    manager = coordinator.manager
    manager.read_daylight_saving.return_value = _dst_config(False, -76)

    await coordinator._read_data()

    manager.write_daylight_saving.assert_awaited_once_with(
        enabled=False, winter_to_summer=0, summer_to_winter=0, timezone_offset=120
    )


async def test_correct_offset_is_not_written(
    coordinator: EnstoCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that a correct setup causes no write and no log."""
    with caplog.at_level(logging.INFO):
        await coordinator._read_data()

    coordinator.manager.write_daylight_saving.assert_not_awaited()
    assert "time zone" not in caplog.text
    assert "daylight saving" not in caplog.text


async def test_checked_once_per_connection(coordinator: EnstoCoordinator) -> None:
    """Test that the settings are read once per connection, not on every update."""
    manager = coordinator.manager

    await coordinator._read_data()
    await coordinator._read_data()
    assert manager.read_daylight_saving.await_count == 1

    # A new connection checks again
    manager.connected_at = 2.0
    await coordinator._read_data()
    assert manager.read_daylight_saving.await_count == 2


async def test_failed_read_is_retried(coordinator: EnstoCoordinator) -> None:
    """Test that a failed read is retried on the next update."""
    manager = coordinator.manager
    manager.read_daylight_saving.side_effect = [
        EnstoBleError("Could not read daylight saving config: TimeoutError"),
        _dst_config(True, 120),
    ]

    await coordinator._read_data()
    await coordinator._read_data()
    assert manager.read_daylight_saving.await_count == 2


async def test_dst_off_warns_once(
    coordinator: EnstoCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that automatic daylight saving off is warned about once, not on every connection."""
    manager = coordinator.manager
    manager.read_daylight_saving.return_value = _dst_config(False, 120)
    warning = "Automatic daylight saving is off on First (AA:BB:CC:DD:EE:FF)"

    await coordinator._read_data()
    manager.connected_at = 2.0
    await coordinator._read_data()

    assert caplog.text.count(warning) == 1
    assert any(
        record.levelno == logging.WARNING and warning in record.getMessage()
        for record in caplog.records
    )


async def test_no_warning_without_summer_time(
    hass: HomeAssistant, coordinator: EnstoCoordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that automatic daylight saving off is fine when Home Assistant has no summer time."""
    await hass.config.async_set_time_zone("UTC")
    manager = coordinator.manager
    manager.read_daylight_saving.return_value = _dst_config(False, 0)

    await coordinator._read_data()

    manager.write_daylight_saving.assert_not_awaited()
    assert "Automatic daylight saving is off" not in caplog.text
