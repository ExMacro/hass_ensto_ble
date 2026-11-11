"""Unit tests for GATT serialization and split read/write deadlock prevention."""
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Set up Home Assistant & bleak mocks
import tests.mocks

from custom_components.hass_ensto_ble.ensto_thermostat_manager import EnstoThermostatManager

class TestGattSerialization(unittest.IsolatedAsyncioTestCase):
    """Test GATT lock serialization and split read/write behavior."""

    async def asyncSetUp(self):
        self.hass = MagicMock()
        self.manager = EnstoThermostatManager(self.hass, "AA:BB:CC:DD:EE:FF")
        self.mock_client = MagicMock()
        self.mock_client.is_connected = True
        self.mock_client.read_gatt_char = AsyncMock()
        self.mock_client.write_gatt_char = AsyncMock()
        self.manager.client = self.mock_client
        self.manager._authenticated = True

    async def test_single_read_acquires_lock(self):
        """Test single GATT read executes and releases the lock."""
        self.mock_client.read_gatt_char.return_value = b"\x01\x02"
        self.assertFalse(self.manager._gatt_lock.locked())
        result = await self.manager._ble_read("dummy-uuid", "test")
        self.assertEqual(result, b"\x01\x02")
        self.assertFalse(self.manager._gatt_lock.locked())

    async def test_single_write_acquires_lock(self):
        """Test single GATT write executes and releases the lock."""
        self.mock_client.write_gatt_char.return_value = None
        self.assertFalse(self.manager._gatt_lock.locked())
        success = await self.manager._ble_write("dummy-uuid", b"\x01", "test")
        self.assertTrue(success)
        self.assertFalse(self.manager._gatt_lock.locked())

    async def test_split_read_does_not_deadlock(self):
        """Test that split read completes under GATT lock without deadlocking."""
        # Packet 1: header 0x00 (more packets follow), payload b"abc"
        # Packet 2: header 0x40 (last packet bit set), payload b"def"
        self.mock_client.read_gatt_char.side_effect = [
            b"\x00abc",
            b"\x40def\x00\x00",
        ]
        
        # If _ble_read were called instead of _ble_read_unlocked, this would hang/deadlock
        result = await asyncio.wait_for(
            self.manager._ble_read_split("dummy-uuid", "split test"),
            timeout=2.0
        )
        self.assertEqual(result, b"abcdef")
        self.assertFalse(self.manager._gatt_lock.locked())

    async def test_split_write_does_not_deadlock(self):
        """Test that split write completes under GATT lock without deadlocking."""
        payload = b"12345678"
        # If _ble_write were called instead of _ble_write_unlocked, this would hang/deadlock
        success = await asyncio.wait_for(
            self.manager._ble_write_split("dummy-uuid", payload, "split write test"),
            timeout=2.0
        )
        self.assertTrue(success)
        self.assertEqual(self.mock_client.write_gatt_char.call_count, 2)
        self.assertFalse(self.manager._gatt_lock.locked())

    async def test_concurrent_reads_serialize(self):
        """Test that concurrent _ble_read calls serialize properly."""
        execution_order = []

        async def slow_read(uuid):
            execution_order.append(f"start_{uuid}")
            await asyncio.sleep(0.05)
            execution_order.append(f"end_{uuid}")
            return b"ok"

        self.mock_client.read_gatt_char.side_effect = slow_read

        task1 = asyncio.create_task(self.manager._ble_read("uuid1", "read 1"))
        task2 = asyncio.create_task(self.manager._ble_read("uuid2", "read 2"))

        await asyncio.gather(task1, task2)

        # Because _gatt_lock serializes calls, task1 must end before task2 starts (or vice-versa)
        self.assertEqual(len(execution_order), 4)
        self.assertEqual(execution_order[0][:5], "start")
        self.assertEqual(execution_order[1][:3], "end")
        self.assertEqual(execution_order[2][:5], "start")
        self.assertEqual(execution_order[3][:3], "end")
        # Ensure they operated on the same uuid pair in order
        self.assertEqual(execution_order[0][6:], execution_order[1][4:])
        self.assertEqual(execution_order[2][6:], execution_order[3][4:])

if __name__ == "__main__":
    unittest.main()
