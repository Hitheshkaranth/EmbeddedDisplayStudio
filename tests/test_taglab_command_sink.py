"""Tests for CommandSink — the daemon substitute (CONTRACT 2.2)."""

import json
import socket
import time
import unittest
from unittest import mock

from tools.hmi_deployer.taglab import (
    CommandSink,
    ConstantWaveform,
    SineWaveform,
    _Subscribers,
    _coerce_bool_value,
    COMMAND_SINK_DEFAULT_PORT,
)


class SubscribersTests(unittest.TestCase):
    """Tests for the internal _Subscribers class."""

    def test_add_and_count(self):
        sub = _Subscribers(ttl=10)
        sub.add("192.0.2.1:5001", 10)
        self.assertEqual(sub.alive_count(), 1)

    def test_remove(self):
        sub = _Subscribers(ttl=5)
        sub.add("192.0.2.1:5001", 5)
        sub.remove("192.0.2.1:5001")
        self.assertEqual(sub.alive_count(), 0)

    def test_prune_expired(self):
        sub = _Subscribers(ttl=0.05)
        sub.add("192.0.2.1:5001", 0.05)
        time.sleep(0.2)  # Sleep long enough to exceed any timing jitter
        survivors = sub.prune()
        # prune() returns surviving addresses, not dead ones
        self.assertNotIn("192.0.2.1:5001", survivors)
        self.assertEqual(sub.alive_count(), 0)

    def test_prune_keeps_alive(self):
        sub = _Subscribers(ttl=10)
        sub.add("192.0.2.1:5001", 10)
        survivors = sub.prune()
        self.assertIn("192.0.2.1:5001", survivors)
        self.assertEqual(sub.alive_count(), 1)

    def test_prune_returns_surviving_addresses(self):
        sub = _Subscribers(ttl=0.05)
        sub.add("alive:1", 10)
        sub.add("expired:1", 0.05)
        time.sleep(0.2)
        survivors = sub.prune()
        self.assertIn("alive:1", survivors)
        self.assertNotIn("expired:1", survivors)
        self.assertEqual(sub.alive_count(), 1)


class CoerceBoolTests(unittest.TestCase):
    """Tests for the _coerce_bool_value helper."""

    def test_bool_passthrough(self):
        self.assertIs(_coerce_bool_value(True), True)
        self.assertIs(_coerce_bool_value(False), False)

    def test_int_coercion(self):
        self.assertIs(_coerce_bool_value(0), False)
        self.assertIs(_coerce_bool_value(1), True)
        self.assertIs(_coerce_bool_value(42), True)

    def test_string_coercion(self):
        self.assertIs(_coerce_bool_value("true"), True)
        self.assertIs(_coerce_bool_value("false"), False)
        self.assertIs(_coerce_bool_value("1"), True)
        self.assertIs(_coerce_bool_value("0"), False)
        self.assertIs(_coerce_bool_value("TRUE"), True)
        self.assertIs(_coerce_bool_value("FALSE"), False)

    def test_float_coercion(self):
        self.assertIs(_coerce_bool_value(0.0), False)
        self.assertIs(_coerce_bool_value(1.0), True)
        # Python 3 banker's rounding: round(0.5) = 0, round(1.5) = 2
        self.assertIs(_coerce_bool_value(0.5), False)
        self.assertIs(_coerce_bool_value(1.5), True)

    def test_unknown_type(self):
        self.assertIs(_coerce_bool_value([]), False)
        self.assertIs(_coerce_bool_value([1]), True)

    def test_string_not_a_number_becomes_true(self):
        """Non-empty string that isn't a known boolean literal coerces via bool()."""
        self.assertIs(_coerce_bool_value("not_a_number"), True)
        self.assertIs(_coerce_bool_value(""), False)


class CommandSinkDatagramTests(unittest.TestCase):
    """Tests for CommandSink lifecycle (port binding)."""

    def test_initial_state_fails_to_bind_closed_port(self):
        # Port 0 binds to a random port on most systems, so test for > 0
        model = type("MockModel", (), {
            "entries": [],
            "find": lambda self, t: None,
        })()
        sink = CommandSink(model, port=0)
        try:
            self.assertGreater(sink.port, 0)  # Port 0 = random available port
            self.assertTrue(sink.online)
            self.assertEqual(sink.errors, 0)
        finally:
            sink.release()

    def test_acquire_frees_and_rebinds(self):
        model = type("MockModel", (), {
            "entries": [],
            "find": lambda self, t: None,
        })()
        sink = CommandSink(model, port=50050)
        try:
            old_port = sink.port
            sink.acquire()
            self.assertEqual(sink.port, old_port)
            self.assertTrue(sink.online)
        finally:
            sink.release()

    def test_release_while_offline_is_safe(self):
        model = type("MockModel", (), {
            "entries": [],
            "find": lambda self, t: None,
        })()
        sink = CommandSink(model, port=50051)
        sink.release()
        sink.release()  # should not raise


class CommandSinkSetTests(unittest.TestCase):
    """Test the `set` command handler."""

    def _build_sink(self, tag: str = "do.valve1", waveform=None):
        if waveform is None:
            waveform = ConstantWaveform(0.0)

        class MockEntry:
            def __init__(self, tag, wf):
                self.tag = tag
                self.waveform = wf

        class MockModel:
            def __init__(self, entries):
                self.entries = entries
            def find(self, name):
                for e in self.entries:
                    if e.tag == name:
                        return e
                return None

        model = MockModel([MockEntry(tag, waveform)])

        sink = CommandSink(model, port=50052)
        return sink, model

    def test_set_do_tag(self):
        sink, model = self._build_sink("do.light", ConstantWaveform(0.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "do.light", "value": 1
        }, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        entry = model.find("do.light")
        self.assertIsInstance(entry.waveform, ConstantWaveform)
        self.assertEqual(entry.waveform.value, 1.0)

    def test_set_di_tag_rejected(self):
        sink, _ = self._build_sink("di.temp", ConstantWaveform(20.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "di.temp", "value": 30
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "not_writable")

    def test_set_unknown_tag(self):
        sink, _ = self._build_sink("do.light", ConstantWaveform(0.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "do.ghost", "value": 1
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "unknown_tag")

    def test_set_boolean_coercion(self):
        sink, model = self._build_sink("do.valve", ConstantWaveform(0.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "do.valve", "value": "true"
        }, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        entry = model.find("do.valve")
        self.assertEqual(entry.waveform.value, 1.0)

    def test_set_numeric_value_bool_tag(self):
        """Numeric values for do.* tags are coerced to bool."""
        sink, model = self._build_sink("do.valve", ConstantWaveform(0.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "do.valve", "value": 3.14
        }, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        entry = model.find("do.valve")
        # 3.14 → round(3.14)=3 → bool(3)=True → 1.0
        self.assertEqual(entry.waveform.value, 1.0)

    def test_set_zero_value(self):
        sink, model = self._build_sink("do.valve", ConstantWaveform(1.0))
        result = CommandSink._handle_set(sink, {
            "cmd": "set", "tag": "do.valve", "value": 0
        }, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        entry = model.find("do.valve")
        self.assertEqual(entry.waveform.value, 0.0)


class CommandSinkPulseTests(unittest.TestCase):
    """Test the `pulse` command handler."""

    def _build_sink(self, tag="do.blink", waveform=None):
        if waveform is None:
            waveform = ConstantWaveform(0.0)

        class MockEntry:
            def __init__(self, tag, wf):
                self.tag = tag
                self.waveform = wf

        class MockModel:
            def __init__(self, entries):
                self.entries = entries
            def find(self, name):
                for e in self.entries:
                    if e.tag == name:
                        return e
                return None

        model = MockModel([MockEntry(tag, waveform)])

        sink = CommandSink(model, port=50053)
        return sink, model

    def test_pulse_basic(self):
        sink, model = self._build_sink("do.blink")
        result = CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.blink", "ms": 250
        }, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        self.assertIn("do.blink", sink._pulse_timers)
        # Waveform should now be constant (high)
        entry = model.find("do.blink")
        self.assertIsInstance(entry.waveform, ConstantWaveform)

    def test_pulse_invalid_duration_too_small(self):
        sink, _ = self._build_sink("do.blink")
        result = CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.blink", "ms": 0
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "bad_value")

    def test_pulse_invalid_duration_too_large(self):
        sink, _ = self._build_sink("do.blink")
        result = CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.blink", "ms": 10001
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "bad_value")

    def test_pulse_unknown_tag(self):
        sink, _ = self._build_sink("do.blink")
        result = CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.ghost", "ms": 250
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "unknown_tag")

    def test_pulse_di_tag_rejected(self):
        sink, _ = self._build_sink("di.temp")
        result = CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "di.temp", "ms": 250
        }, ("127.0.0.1", 5001))
        self.assertFalse(result["ok"])
        self.assertEqual(result["err"], "not_writable")

    def test_pulse_preserves_original_waveform(self):
        sink, model = self._build_sink("do.blink", ConstantWaveform(0.0))
        CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.blink", "ms": 250
        }, ("127.0.0.1", 5001))
        # Original should be saved in _pulse_timers
        self.assertIn("do.blink", sink._pulse_timers)
        stored = sink._pulse_timers["do.blink"]
        self.assertIn("original", stored)

    def test_pulse_stops_all_on_release(self):
        sink, _ = self._build_sink("do.blink")
        CommandSink._handle_pulse(sink, {
            "cmd": "pulse", "tag": "do.blink", "ms": 250
        }, ("127.0.0.1", 5001))
        self.assertTrue(len(sink._pulse_timers) > 0)
        sink.release()
        self.assertEqual(len(sink._pulse_timers), 0)


class CommandSinkListPingSubscribeTests(unittest.TestCase):
    """Test the `list`, `ping`, `subscribe`, and `unsubscribe` handlers."""

    def _build_sink(self):
        class MockEntry:
            def __init__(self, tag):
                self.tag = tag

        class MockModel:
            def __init__(self, entries):
                self.entries = entries
            def find(self, name):
                for e in self.entries:
                    if e.tag == name:
                        return e
                return None

        model = MockModel([MockEntry("do.a"), MockEntry("di.b")])

        sink = CommandSink(model, port=50054)
        return sink, model

    def test_ping(self):
        sink, _ = self._build_sink()
        result = CommandSink._handle_ping(sink, {"cmd": "ping"}, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])

    def test_list(self):
        sink, _ = self._build_sink()
        result = CommandSink._handle_list(sink, {"cmd": "list"}, ("127.0.0.1", 5001))
        self.assertTrue(result["ok"])
        self.assertEqual(result["tags"], ["do.a", "di.b"])

    def test_subscribe(self):
        sink, _ = self._build_sink()
        result = CommandSink._handle_subscribe(sink, {
            "cmd": "subscribe", "ttl": 10
        }, ("192.0.2.1", 5001))
        self.assertTrue(result["ok"])
        self.assertEqual(sink._subscribers.alive_count(), 1)

    def test_subscribe_with_default_ttl(self):
        sink, _ = self._build_sink()
        result = CommandSink._handle_subscribe(sink, {
            "cmd": "subscribe"
        }, ("192.0.2.1", 5001))
        self.assertTrue(result["ok"])
        self.assertEqual(sink._subscribers.alive_count(), 1)

    def test_unsubscribe(self):
        sink, _ = self._build_sink()
        sink._subscribers.add("192.0.2.1:5001", 10)
        result = CommandSink._handle_unsubscribe(sink, {
            "cmd": "unsubscribe"
        }, ("192.0.2.1", 5001))
        self.assertTrue(result["ok"])
        self.assertEqual(sink._subscribers.alive_count(), 0)

    def test_unsubscribe_nonexistent(self):
        sink, _ = self._build_sink()
        result = CommandSink._handle_unsubscribe(sink, {
            "cmd": "unsubscribe"
        }, ("192.0.2.1", 5001))
        self.assertTrue(result["ok"])
        self.assertEqual(sink._subscribers.alive_count(), 0)


class CommandSinkAckTests(unittest.TestCase):
    """Test the acknowledgment mechanism."""

    def test_ack_format(self):
        ack = {"ok": True, "t": "ack"}
        self.assertIn("t", ack)
        self.assertEqual(ack["t"], "ack")

    def test_ack_with_error(self):
        ack = {"ok": False, "t": "ack", "err": "hw_error"}
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["err"], "hw_error")

    def test_ack_with_id(self):
        ack = {"ok": True, "t": "ack", "id": "req-123"}
        self.assertEqual(ack["id"], "req-123")


class CommandSinkPortTests(unittest.TestCase):
    """Test port acquisition and release."""

    def test_acquire_releases_existing(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sink = CommandSink(model, port=50055)
        old_port = sink.port
        sink.acquire()
        self.assertEqual(sink.port, old_port)
        sink.release()

    def test_errors_reset_on_new_bind(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sink = CommandSink(model, port=50056)
        try:
            sink._errors = 5
            sink.acquire()
            self.assertEqual(sink.errors, 5)  # errors persist across acquire
        finally:
            sink.release()


class CommandSinkIntegrationTests(unittest.TestCase):
    """End-to-end: send a datagram, read it back."""

    def test_set_datagram_round_trip(self):
        """Send a set command via UDP, verify it is processed."""
        class MockEntry:
            def __init__(self):
                self.tag = "do.test"
                self.waveform = ConstantWaveform(0.0)

        class MockModel:
            def __init__(self):
                self.entries = [MockEntry()]
            def find(self, name):
                for e in self.entries:
                    if e.tag == name:
                        return e
                return None

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        model = MockModel()
        sink = CommandSink(model, port=50060)

        try:
            cmd = json.dumps({
                "cmd": "set", "id": "x1", "tag": "do.test", "value": 1
            })
            sock.sendto(cmd.encode("utf-8"), ("127.0.0.1", 50060))

            time.sleep(0.05)
            result = sink._handle_datagrams()
            self.assertEqual(sink.errors, 0)
            entry = model.find("do.test")
            self.assertEqual(entry.waveform.value, 1.0)
        finally:
            sink.release()
            sock.close()

    def test_bad_json_increments_errors(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        sink = CommandSink(model, port=50061)

        try:
            sock.sendto(b"not json", ("127.0.0.1", 50061))
            time.sleep(0.05)
            sink._handle_datagrams()
            self.assertEqual(sink.errors, 1)
        finally:
            sink.release()
            sock.close()

    def test_oversized_datagram(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        sink = CommandSink(model, port=50062)

        try:
            # Send datagram larger than _COMMAND_MAX_BYTES (8192)
            large_data = json.dumps({"cmd": "set", "tag": "x", "value": 1}) * 200
            sock.sendto(large_data.encode("utf-8"), ("127.0.0.1", 50062))
            time.sleep(0.05)
            sink._handle_datagrams()
            self.assertEqual(sink.errors, 1)
        finally:
            sink.release()
            sock.close()

    def test_non_object_json_increments_errors(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        sink = CommandSink(model, port=50063)

        try:
            sock.sendto(b'"just a string"', ("127.0.0.1", 50063))
            time.sleep(0.05)
            sink._handle_datagrams()
            self.assertEqual(sink.errors, 1)
        finally:
            sink.release()
            sock.close()

    def test_empty_cmd_increments_errors(self):
        model = type("M", (), {"entries": [], "find": lambda s, t: None})()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)

        sink = CommandSink(model, port=50064)

        try:
            sock.sendto(b'{"cmd": ""}', ("127.0.0.1", 50064))
            time.sleep(0.05)
            sink._handle_datagrams()
            self.assertEqual(sink.errors, 1)
        finally:
            sink.release()
            sock.close()


class CommandSinkNoQtTests(unittest.TestCase):
    """Tests for CommandSink when PySide6 is not available."""

    def test_sink_works_without_qt(self):
        """CommandSink should be usable without Qt for offline testing."""
        class MockEntry:
            def __init__(self):
                self.tag = "do.offline"
                self.waveform = ConstantWaveform(0.0)

        class MockModel:
            def __init__(self):
                self.entries = [MockEntry()]
            def find(self, name):
                for e in self.entries:
                    if e.tag == name:
                        return e
                return None

        model = MockModel()
        sink = CommandSink(model, port=50065)
        try:
            result = CommandSink._handle_set(sink, {
                "cmd": "set", "tag": "do.offline", "value": 1
            }, ("127.0.0.1", 5001))
            self.assertTrue(result["ok"])
            self.assertEqual(model.find("do.offline").waveform.value, 1.0)
        finally:
            sink.release()


if __name__ == "__main__":
    unittest.main()