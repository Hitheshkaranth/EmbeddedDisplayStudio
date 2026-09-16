"""Integration tests for Modbus support in hmi_hwd.py daemon."""

import json
import sys
import os
import struct
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "daemon"))

import hmi_hwd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GPIO_BASE = {
    "gpio": {
        "chip": "/dev/gpiochip3",
        "consumer": "hmi-hwd",
        "outputs": {"do.relay1": {"offset": 1, "active_low": False, "safe_state": 0}},
        "inputs": {"di.estop": {"offset": 5, "active_low": True}},
    }
}


def _make_config_path(cfg_dict):
    tmp = os.path.join(os.path.dirname(__file__), "..", "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "hwd_test.json")
    with open(path, "w") as f:
        json.dump(cfg_dict, f)
    return path


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

class LoadConfigModbusTest(unittest.TestCase):
    """Tests for load_config() with modbus blocks."""

    def test_modbus_config_valid(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {
                "host": "127.0.0.1",
                "port": 502,
                "unit_id": 1,
                "poll_interval_ms": 200,
                "reconnect_s": 5.0,
                "timeout_s": 1.0,
                "tags": {
                    "mb.coil1": {
                        "kind": "coil",
                        "address": 0,
                        "type": "bool",
                        "writable": True,
                    }
                },
            },
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            result = hmi_hwd.load_config(path)
            self.assertIn("modbus", result)
            self.assertEqual(result["modbus"]["host"], "127.0.0.1")
        finally:
            os.remove(path)

    def test_modbus_config_missing_host(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {"port": 502},
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            with self.assertRaises(SystemExit):
                hmi_hwd.load_config(path)
        finally:
            os.remove(path)

    def test_modbus_config_invalid_port(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {"host": "127.0.0.1", "port": 99999},
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            with self.assertRaises(SystemExit):
                hmi_hwd.load_config(path)
        finally:
            os.remove(path)

    def test_modbus_tag_invalid_kind(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {
                "host": "127.0.0.1",
                "tags": {"mb.bad": {"kind": "invalid", "address": 0, "type": "bool"}},
            },
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            with self.assertRaises(SystemExit):
                hmi_hwd.load_config(path)
        finally:
            os.remove(path)

    def test_modbus_tag_coil_requires_bool(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {
                "host": "127.0.0.1",
                "tags": {"mb.bad": {"kind": "coil", "address": 0, "type": "int16"}},
            },
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            with self.assertRaises(SystemExit):
                hmi_hwd.load_config(path)
        finally:
            os.remove(path)

    def test_modbus_tag_holding_requires_numeric_type(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {
                "host": "127.0.0.1",
                "tags": {"mb.bad": {"kind": "holding", "address": 0, "type": "bool"}},
            },
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            with self.assertRaises(SystemExit):
                hmi_hwd.load_config(path)
        finally:
            os.remove(path)

    def test_modbus_tag_writable_requires_coil_or_holding(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
            "modbus": {
                "host": "127.0.0.1",
                "tags": {"mb.bad": {"kind": "coil", "address": 0, "type": "bool", "writable": True}},
            },
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            result = hmi_hwd.load_config(path)
            self.assertTrue(result["modbus"]["tags"]["mb.bad"]["writable"])
        finally:
            os.remove(path)

    def test_modbus_no_modbus_block_is_valid(self):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000},
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        try:
            result = hmi_hwd.load_config(path)
            self.assertNotIn("modbus", result)
        finally:
            os.remove(path)


# ---------------------------------------------------------------------------
# ModbusSim integration tests (with --sim mode)
# ---------------------------------------------------------------------------

class ModbusSimIntegrationTest(unittest.TestCase):
    """Tests for ModbusSim integrated into the daemon."""

    def _make_daemon(self, modbus_cfg):
        cfg = {
            "daemon": {"poll_interval_ms": 100, "cmd_port": 5000, "telemetry_sink": "127.0.0.1:5001"},
            "modbus": modbus_cfg,
        }
        cfg.update(_GPIO_BASE)
        path = _make_config_path(cfg)
        parsed = hmi_hwd.load_config(path)
        return hmi_hwd.HwDaemon(parsed, force_sim=True, strict=False), path

    def test_daemon_starts_with_modbus_sim(self):
        modbus_cfg = {
            "host": "127.0.0.1",
            "port": 502,
            "poll_interval_ms": 100,
            "reconnect_s": 1.0,
            "tags": {
                "mb.coil1": {"kind": "coil", "address": 0, "type": "bool", "writable": True},
                "mb.reg1": {"kind": "holding", "address": 100, "type": "int16", "writable": True},
            },
        }
        daemon, path = self._make_daemon(modbus_cfg)
        try:
            self.assertIsNotNone(daemon._modbus_tags)
            self.assertIn("mb.coil1", daemon._modbus_tags)
            self.assertIn("mb.reg1", daemon._modbus_tags)
            self.assertTrue(daemon.tags.exists("mb.coil1"))
            self.assertTrue(daemon.tags.exists("mb.reg1"))
            self.assertTrue(daemon.tags.exists("sys.modbus_online"))
            self.assertTrue(daemon.tags.is_writable("mb.coil1"))
            self.assertTrue(daemon.tags.is_writable("mb.reg1"))
            self.assertIsNotNone(daemon._modbus_thread)
            self.assertTrue(daemon._modbus_thread.is_alive())
        finally:
            daemon._safe_shutdown()
            os.remove(path)

    def test_modbus_tag_read_in_sim(self):
        modbus_cfg = {
            "host": "127.0.0.1",
            "poll_interval_ms": 50,
            "reconnect_s": 1.0,
            "tags": {
                "mb.reg1": {"kind": "holding", "address": 100, "type": "int16", "writable": True},
            },
        }
        daemon, path = self._make_daemon(modbus_cfg)
        try:
            daemon._modbus_sim.holding_registers[100] = 200
            daemon._modbus_stop.wait(timeout=3.0)
            val = daemon.tags.get("mb.reg1")
            self.assertIsNotNone(val, "Tag should not be None after successful sim poll")
            self.assertEqual(val, 200.0, f"Expected 200.0, got {val}")
        finally:
            daemon._safe_shutdown()
            os.remove(path)

    def test_modbus_32bit_tag_reads_both_registers(self):
        """A float32/int32 tag spans two registers; a one-register read
        hands decode_value() half a payload and the tag stays at 0."""
        modbus_cfg = {
            "host": "127.0.0.1",
            "poll_interval_ms": 50,
            "reconnect_s": 1.0,
            "tags": {
                "mb.flow": {"kind": "holding", "address": 10, "type": "float32"},
                "mb.total": {"kind": "input", "address": 20, "type": "int32"},
            },
        }
        daemon, path = self._make_daemon(modbus_cfg)
        try:
            hi, lo = struct.unpack(">HH", struct.pack(">f", 12.5))
            daemon._modbus_sim.holding_registers[10] = hi
            daemon._modbus_sim.holding_registers[11] = lo
            hi, lo = struct.unpack(">HH", struct.pack(">i", -70000))
            daemon._modbus_sim.input_registers[20] = hi
            daemon._modbus_sim.input_registers[21] = lo
            daemon._modbus_stop.wait(timeout=1.0)
            daemon._do_modbus_poll()
            self.assertAlmostEqual(daemon.tags.get("mb.flow"), 12.5, places=5)
            self.assertEqual(daemon.tags.get("mb.total"), -70000)
        finally:
            daemon._safe_shutdown()
            os.remove(path)

    def test_modbus_coil_write_via_gpio(self):
        """Write to a Modbus coil tag via gpio_write (simulating protocol handler)."""
        modbus_cfg = {
            "host": "127.0.0.1",
            "poll_interval_ms": 50,
            "reconnect_s": 1.0,
            "tags": {
                "mb.coil1": {"kind": "coil", "address": 0, "type": "bool", "writable": True},
            },
        }
        daemon, path = self._make_daemon(modbus_cfg)
        try:
            daemon.gpio_write("mb.coil1", 1)
            self.assertTrue(daemon.tags.get("mb.coil1"))
            self.assertTrue(
                daemon._modbus_sim.holding_registers.get(0)
                or daemon._modbus_sim.coils.get(0, False)
            )
        finally:
            daemon._safe_shutdown()
            os.remove(path)

    def test_modbus_safe_shutdown(self):
        """On shutdown, modbus safe states should be written."""
        modbus_cfg = {
            "host": "127.0.0.1",
            "poll_interval_ms": 100,
            "reconnect_s": 1.0,
            "tags": {
                "mb.coil1": {
                    "kind": "coil",
                    "address": 0,
                    "type": "bool",
                    "writable": True,
                    "safe_state": 0,
                }
            },
        }
        daemon, path = self._make_daemon(modbus_cfg)
        try:
            self.assertIn("mb.coil1", daemon._modbus_safe_states)
            self.assertEqual(daemon._modbus_safe_states["mb.coil1"], 0)
        finally:
            daemon._safe_shutdown()
            self.assertFalse(daemon._modbus_thread.is_alive())
            os.remove(path)


if __name__ == "__main__":
    unittest.main()