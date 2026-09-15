"""Tests for daemon/modbus.py — Modbus TCP client and simulator."""

import json
import socket
import struct
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))

import modbus


# ---------------------------------------------------------------------------
# Helpers: build raw Modbus TCP frames
# ---------------------------------------------------------------------------

def _build_mbap(txn_id: int, unit_id: int, fc: int, payload: bytes = b"") -> bytes:
    """Build a raw MBAP header + PDU frame (unit_id at byte 6)."""
    mbap = struct.pack(">HHH", txn_id, 0, 5 + len(payload))
    return mbap + struct.pack(">BB", unit_id, fc) + payload


def _build_read_response(txn_id: int, unit_id: int, fc: int, byte_count: int, data: bytes) -> bytes:
    """Build a normal read response (FC 1/2/3/4)."""
    if isinstance(data, list):
        data = bytes(data)
    pdu = struct.pack(">BBB", unit_id, fc, byte_count) + data
    return _build_mbap(txn_id, unit_id, fc, b"")[:6] + pdu


def _build_read_reg_response(txn_id: int, unit_id: int, reg_count: int, values: list) -> bytes:
    """Build a holding/input register read response (FC 3/4)."""
    byte_count = reg_count * 2
    data = struct.pack(">" + "H" * reg_count, *values)
    return _build_read_response(txn_id, unit_id, 0x03, byte_count, data)


def _build_exception_response(txn_id: int, unit_id: int, fc: int, exc_code: int) -> bytes:
    """Build a Modbus exception response."""
    pdu = struct.pack(">BBB", unit_id, fc | 0x80, exc_code)
    return _build_mbap(txn_id, unit_id, fc, b"")[:6] + pdu


# ---------------------------------------------------------------------------
# Test: ModbusError
# ---------------------------------------------------------------------------

class ModbusErrorTest(unittest.TestCase):
    def test_error_code_preserved(self):
        exc = modbus.ModbusError(2)
        self.assertEqual(exc.code, 2)

    def test_str_contains_code(self):
        exc = modbus.ModbusError(3)
        self.assertIn("Modbus exception", str(exc))

    def test_str_contains_label(self):
        exc = modbus.ModbusError(2)
        self.assertIn("illegal_address", str(exc))

    def test_unknown_code(self):
        exc = modbus.ModbusError(99)
        self.assertIn("unknown", str(exc))


# ---------------------------------------------------------------------------
# Test: MBAP helpers
# ---------------------------------------------------------------------------

class MBAPHelperTest(unittest.TestCase):
    def test_build_header(self):
        frame = modbus._build_header(0xDEAD, 1, 3, b"\x02\x00")
        txn, _, length = struct.unpack(">HHH", frame[:6])
        self.assertEqual(txn, 0xDEAD)
        self.assertEqual(length, 5 + 2)  # 5 (unit_id+FC+byte_count) + 2 payload

    def test_parse_header(self):
        frame = modbus._build_header(0x1234, 5, 3, b"")
        txn, unit, length = modbus._parse_header(frame)
        self.assertEqual(txn, 0x1234)
        self.assertEqual(unit, 5)
        self.assertEqual(length, 5)

    def test_parse_header_short(self):
        with self.assertRaises(modbus.ModbusError):
            modbus._parse_header(b"\x00\x01")

    def test_parse_header_bad_protocol(self):
        frame = b"\x00\x01\xff\x00\x00\x05"
        with self.assertRaises(modbus.ModbusError):
            modbus._parse_header(frame)


# ---------------------------------------------------------------------------
# Test: Value encoding/decoding
# ---------------------------------------------------------------------------

class ValueCodecTest(unittest.TestCase):
    def test_encode_int16(self):
        data = modbus.encode_value(100, "int16")
        self.assertEqual(data, b"\x00d")  # big-endian: 0x0064

    def test_encode_int16_negative(self):
        data = modbus.encode_value(-100, "int16")
        self.assertEqual(len(data), 2)
        val = struct.unpack(">h", data)[0]
        self.assertEqual(val, -100)

    def test_encode_uint16(self):
        data = modbus.encode_value(65535, "uint16")
        self.assertEqual(data, b"\xff\xff")

    def test_encode_int32(self):
        data = modbus.encode_value(0x12345678, "int32")
        self.assertEqual(data, b"\x12\x34\x56\x78")

    def test_encode_uint32(self):
        data = modbus.encode_value(0xDEADBEEF, "uint32")
        self.assertEqual(len(data), 4)
        self.assertEqual(struct.unpack(">I", data)[0], 0xDEADBEEF)

    def test_encode_float32(self):
        data = modbus.encode_value(3.14, "float32")
        self.assertEqual(len(data), 4)

    def test_encode_bool_true(self):
        data = modbus.encode_value(1, "bool")
        self.assertEqual(data, b"\xFF")

    def test_encode_bool_false(self):
        data = modbus.encode_value(0, "bool")
        self.assertEqual(data, b"\x00")

    def test_encode_unknown_type(self):
        with self.assertRaises(KeyError):
            modbus.encode_value(42, "quack")

    def test_decode_int16(self):
        val = modbus.decode_value(b"\x00d", "int16")
        self.assertEqual(val, 100)

    def test_decode_int32_big(self):
        val = modbus.decode_value(b"\x12\x34\x56\x78", "int32", "big")
        self.assertEqual(val, 0x12345678)

    def test_decode_int32_little(self):
        val = modbus.decode_value(b"\x78\x56\x34\x12", "int32", "little")
        self.assertEqual(val, 0x12345678)

    def test_decode_float32(self):
        val = modbus.decode_value(struct.pack(">f", 3.14), "float32")
        self.assertAlmostEqual(val, 3.14, places=5)

    def test_decode_bool(self):
        val = modbus.decode_value(b"\x00", "bool")
        self.assertEqual(val, 0)
        val = modbus.decode_value(b"\xFF", "bool")
        self.assertEqual(val, 1)

    def test_decode_unknown_type(self):
        with self.assertRaises(ValueError):
            modbus.decode_value(b"\x00", "quack")

    def test_scale_read_float(self):
        val = modbus.scale_read(100.0, "float32", 2.0, 5.0)
        self.assertAlmostEqual(val, 205.0, places=5)

    def test_scale_read_int16(self):
        val = modbus.scale_read(100, "int16", 0.1, 0.0)
        self.assertAlmostEqual(val, 10.0, places=5)

    def test_scale_write_float(self):
        raw = modbus.scale_write(205.0, "float32", 2.0, 5.0)
        self.assertAlmostEqual(raw, 100.0, places=3)

    def test_scale_write_int16(self):
        raw = modbus.scale_write(10.0, "int16", 0.1, 0.0)
        self.assertEqual(raw, 100)


# ---------------------------------------------------------------------------
# Test: ModbusSim (in-memory simulator)
# ---------------------------------------------------------------------------

class ModbusSimTest(unittest.TestCase):
    def setUp(self):
        self.sim = modbus.ModbusSim()

    def test_read_coils_single(self):
        self.sim.set_coil(0, True)
        data = self.sim.poll_coils(0, 1)
        self.assertEqual(data, bytearray(b"\x01"))

    def test_read_coils_all_false(self):
        data = self.sim.poll_coils(0, 1)
        self.assertEqual(data, bytearray(b"\x00"))

    def test_write_coil(self):
        self.sim.write_single_coil(0, True)
        self.assertTrue(self.sim.coils[0])
        self.sim.write_single_coil(0, False)
        self.assertFalse(self.sim.coils[0])

    def test_read_holding_registers(self):
        self.sim.set_register(100, 42)
        data = self.sim.poll_holding_registers(100, 1)
        self.assertEqual(struct.unpack(">H", data)[0], 42)

    def test_write_holding_register(self):
        self.sim.write_single_register(100, 12345)
        self.assertEqual(self.sim.holding_registers[100], 12345)
        data = self.sim.poll_holding_registers(100, 1)
        self.assertEqual(struct.unpack(">H", data)[0], 12345)

    def test_read_input_registers(self):
        self.sim.set_input_register(50, 77)
        data = self.sim.poll_input_registers(50, 1)
        self.assertEqual(struct.unpack(">H", data)[0], 77)

    def test_read_discrete_inputs(self):
        self.sim.set_discrete(10, True)
        data = self.sim.poll_discrete_inputs(10, 1)
        self.assertEqual(data, bytearray(b"\x01"))

    def test_read_nonexistent(self):
        data = self.sim.poll_holding_registers(9999, 1)
        self.assertEqual(data, bytearray(b"\x00\x00"))

    def test_multi_register_write(self):
        self.sim.write_multiple_registers(10, [1, 2, 3, 4, 5])
        for i in range(5):
            self.assertEqual(self.sim.holding_registers[10 + i], i + 1)

    def test_get_coil_map(self):
        self.sim.set_coil(0, True)
        self.sim.set_coil(1, False)
        m = self.sim.get_coil_map()
        self.assertEqual(m[0], True)
        self.assertEqual(m[1], False)

    def test_get_register_map(self):
        self.sim.set_register(100, 42)
        m = self.sim.get_register_map()
        self.assertEqual(m[100], 42)

    def test_online_is_true(self):
        self.assertTrue(self.sim.online)


# ---------------------------------------------------------------------------
# Test: ModbusTcpClient (with socket mocking)
# ---------------------------------------------------------------------------

class ModbusTcpClientTest(unittest.TestCase):
    def setUp(self):
        self.mock_socket = MagicMock()
        self.client = modbus.ModbusTcpClient("127.0.0.1", 502, 1, timeout_s=1.0)
        self.client._sock = self.mock_socket

    def _connect_mock(self):
        """Helper to make client think it's connected."""
        self.client._sock = self.mock_socket
        self.client.online = True
        self.client.last_error = None

    def test_read_holding_registers_success(self):
        self._connect_mock()
        frame = _build_read_reg_response(1, 1, 1, [42])
        self.mock_socket.recv.return_value = frame
        result = self.client.read_holding_registers(100, 1)
        self.assertEqual(struct.unpack(">H", result)[0], 42)

    def test_read_coils_success(self):
        self._connect_mock()
        frame = _build_read_response(1, 1, 0x01, 1, [0xFF])
        self.mock_socket.recv.return_value = frame
        result = self.client.read_coils(0, 8)
        self.assertEqual(result, bytearray(b"\xFF"))  # all 8 coils ON

    def test_exception_raised(self):
        self._connect_mock()
        frame = _build_exception_response(1, 1, 3, 2)
        self.mock_socket.recv.return_value = frame
        with self.assertRaises(modbus.ModbusError) as ctx:
            self.client.read_holding_registers(100, 1)
        self.assertEqual(ctx.exception.code, 2)

    def test_write_single_coil(self):
        self._connect_mock()
        frame = _build_mbap(1, 1, 5, struct.pack(">HH", 0, 0xFF00))
        self.mock_socket.recv.return_value = frame
        self.client.write_single_coil(0, True)
        sent = self.mock_socket.sendall.call_args[0][0]
        self.assertEqual(sent[7], 5)  # FC 5 at byte 7

    def test_write_single_register(self):
        self._connect_mock()
        frame = _build_mbap(1, 1, 6, struct.pack(">HH", 100, 42))
        self.mock_socket.recv.return_value = frame
        self.client.write_single_register(100, 42)
        sent = self.mock_socket.sendall.call_args[0][0]
        self.assertEqual(sent[7], 6)  # FC 6 at byte 7

    def test_online_property(self):
        self.assertFalse(self.client.online)
        self._connect_mock()
        self.mock_socket.recv.return_value = _build_read_reg_response(1, 1, 1, [42])
        self.client.read_holding_registers(0, 1)
        self.assertTrue(self.client.online)

    def test_last_error_cleared_on_success(self):
        self.assertFalse(self.client.online)
        self._connect_mock()
        self.client.last_error = "old error"
        self.mock_socket.recv.return_value = _build_read_reg_response(1, 1, 1, [42])
        self.client.read_holding_registers(0, 1)
        self.assertIsNone(self.client.last_error)

    def test_write_multiple_registers(self):
        self._connect_mock()
        frame = _build_mbap(1, 1, 16, struct.pack(">HHB", 10, 3, 6) + struct.pack(">HHH", 1, 2, 3))
        self.mock_socket.recv.return_value = frame
        self.client.write_multiple_registers(10, [1, 2, 3])

    def test_close(self):
        self.mock_socket.fileno.return_value = 0  # make sock look open
        self.client.close()
        self.mock_socket.close.assert_called_once()

    def test_quantity_validation(self):
        with self.assertRaises(modbus.ModbusError):
            self.client.read_coils(0, 0)
        with self.assertRaises(modbus.ModbusError):
            self.client.read_coils(0, 2001)


if __name__ == "__main__":
    unittest.main()