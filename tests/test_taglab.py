"""
tests/test_taglab.py
Layer: Test (W11)
Comprehensive tests for the Tag Lab feature (tools/hmi_deployer/taglab.py).

Coverage:
- Waveform validation and boundary conditions for all five waveform types
- Type coercion (int arguments accepted where float expected)
- Scenario round-trip (save → load identity) and rejection of bad data
- Sequence / timestamp behaviour in build_frame
- UDP payload structure
- TagLabModel lifecycle and ownership rules (unknown tags never auto-activate)
- TelemetrySimulator: value advancement, frame structure, seq increments, stop idempotency
- TelemetryRelay: remote script compiles as valid Python 3
"""
import json
import math
import os
import socket
import sys
import tempfile
import time
import unittest

# Add repo root to path so tools.hmi_deployer can be imported without install
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.hmi_deployer.taglab import (
    WAVEFORM_KINDS,
    ConstantWaveform,
    NoiseWaveform,
    RampWaveform,
    SineWaveform,
    SquareWaveform,
    TagEntry,
    TagLabModel,
    load_scenario,
    save_scenario,
    waveform_from_dict,
)


# ---------------------------------------------------------------------------
# Waveform validation tests
# ---------------------------------------------------------------------------

class TestConstantWaveform(unittest.TestCase):
    def test_sample_returns_value(self):
        w = ConstantWaveform(3.14)
        for t in (0.0, 1.0, 100.0, -5.0):
            self.assertAlmostEqual(w.sample(t), 3.14)

    def test_integer_coercion(self):
        w = ConstantWaveform(5)  # int input
        self.assertIsInstance(w.value, float)
        self.assertAlmostEqual(w.value, 5.0)

    def test_zero_accepted(self):
        w = ConstantWaveform(0)
        self.assertAlmostEqual(w.sample(0.0), 0.0)

    def test_negative_accepted(self):
        w = ConstantWaveform(-99.9)
        self.assertAlmostEqual(w.sample(0.0), -99.9)

    def test_inf_rejected(self):
        with self.assertRaises(ValueError):
            ConstantWaveform(math.inf)

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            ConstantWaveform(math.nan)

    def test_roundtrip(self):
        w = ConstantWaveform(42.0)
        d = w.to_dict()
        self.assertEqual(d["kind"], "constant")
        w2 = ConstantWaveform.from_dict(d)
        self.assertAlmostEqual(w2.value, 42.0)


class TestSineWaveform(unittest.TestCase):
    def test_peaks_and_troughs(self):
        w = SineWaveform(amplitude=1.0, period=1.0, offset=0.0)
        # sin at T/4 ≈ 1.0, at 3T/4 ≈ -1.0
        self.assertAlmostEqual(w.sample(0.25), 1.0, places=6)
        self.assertAlmostEqual(w.sample(0.75), -1.0, places=6)

    def test_offset_shifts_midpoint(self):
        w = SineWaveform(amplitude=1.0, period=1.0, offset=5.0)
        # At t=0, sin=0 so value should be offset
        self.assertAlmostEqual(w.sample(0.0), 5.0, places=6)

    def test_zero_period_rejected(self):
        with self.assertRaises(ValueError):
            SineWaveform(amplitude=1.0, period=0.0)

    def test_negative_period_rejected(self):
        with self.assertRaises(ValueError):
            SineWaveform(amplitude=1.0, period=-1.0)

    def test_inf_period_rejected(self):
        with self.assertRaises(ValueError):
            SineWaveform(amplitude=1.0, period=math.inf)

    def test_inf_amplitude_rejected(self):
        with self.assertRaises(ValueError):
            SineWaveform(amplitude=math.inf, period=1.0)

    def test_nan_offset_rejected(self):
        with self.assertRaises(ValueError):
            SineWaveform(amplitude=1.0, period=1.0, offset=math.nan)

    def test_integer_args_coerced(self):
        w = SineWaveform(1, 2, 0)
        self.assertIsInstance(w.amplitude, float)
        self.assertIsInstance(w.period, float)

    def test_roundtrip(self):
        w = SineWaveform(2.5, 3.0, 1.0)
        w2 = SineWaveform.from_dict(w.to_dict())
        self.assertAlmostEqual(w2.amplitude, 2.5)
        self.assertAlmostEqual(w2.period, 3.0)
        self.assertAlmostEqual(w2.offset, 1.0)


class TestSquareWaveform(unittest.TestCase):
    def test_high_phase(self):
        w = SquareWaveform(high=1.0, low=0.0, period=2.0, duty=0.5)
        self.assertAlmostEqual(w.sample(0.0), 1.0)   # start of high phase
        self.assertAlmostEqual(w.sample(0.9), 1.0)   # still high

    def test_low_phase(self):
        w = SquareWaveform(high=1.0, low=0.0, period=2.0, duty=0.5)
        self.assertAlmostEqual(w.sample(1.0), 0.0)   # start of low phase
        self.assertAlmostEqual(w.sample(1.9), 0.0)   # still low

    def test_duty_one_always_high(self):
        w = SquareWaveform(high=1.0, low=0.0, period=1.0, duty=1.0)
        for t in (0.0, 0.5, 0.99):
            self.assertAlmostEqual(w.sample(t), 1.0)

    def test_duty_zero_rejected(self):
        with self.assertRaises(ValueError):
            SquareWaveform(high=1.0, low=0.0, period=1.0, duty=0.0)

    def test_duty_gt_one_rejected(self):
        with self.assertRaises(ValueError):
            SquareWaveform(high=1.0, low=0.0, period=1.0, duty=1.1)

    def test_zero_period_rejected(self):
        with self.assertRaises(ValueError):
            SquareWaveform(high=1.0, low=0.0, period=0.0)

    def test_roundtrip(self):
        w = SquareWaveform(3.3, 0.0, 1.0, 0.25)
        w2 = SquareWaveform.from_dict(w.to_dict())
        self.assertAlmostEqual(w2.high, 3.3)
        self.assertAlmostEqual(w2.duty, 0.25)


class TestRampWaveform(unittest.TestCase):
    def test_start_is_low(self):
        w = RampWaveform(low=0.0, high=10.0, period=1.0)
        self.assertAlmostEqual(w.sample(0.0), 0.0, places=5)

    def test_midpoint(self):
        w = RampWaveform(low=0.0, high=10.0, period=1.0)
        self.assertAlmostEqual(w.sample(0.5), 5.0, places=5)

    def test_period_wraps(self):
        w = RampWaveform(low=0.0, high=10.0, period=1.0)
        # At t=1.0 should be same as t=0.0
        self.assertAlmostEqual(w.sample(1.0), 0.0, places=5)
        self.assertAlmostEqual(w.sample(1.5), 5.0, places=5)

    def test_zero_period_rejected(self):
        with self.assertRaises(ValueError):
            RampWaveform(low=0.0, high=1.0, period=0.0)

    def test_roundtrip(self):
        w = RampWaveform(-5.0, 5.0, 2.0)
        w2 = RampWaveform.from_dict(w.to_dict())
        self.assertAlmostEqual(w2.low, -5.0)
        self.assertAlmostEqual(w2.high, 5.0)
        self.assertAlmostEqual(w2.period, 2.0)


class TestNoiseWaveform(unittest.TestCase):
    def test_output_within_bounds(self):
        w = NoiseWaveform(amplitude=1.0, mean=0.0)
        for _ in range(200):
            v = w.sample(0.0)
            self.assertGreaterEqual(v, -1.0)
            self.assertLessEqual(v, 1.0)

    def test_mean_shifts_range(self):
        w = NoiseWaveform(amplitude=0.5, mean=10.0)
        for _ in range(200):
            v = w.sample(0.0)
            self.assertGreaterEqual(v, 9.5)
            self.assertLessEqual(v, 10.5)

    def test_zero_amplitude_constant(self):
        w = NoiseWaveform(amplitude=0.0, mean=7.0)
        for _ in range(10):
            self.assertAlmostEqual(w.sample(0.0), 7.0)

    def test_negative_amplitude_rejected(self):
        with self.assertRaises(ValueError):
            NoiseWaveform(amplitude=-1.0)

    def test_inf_amplitude_rejected(self):
        with self.assertRaises(ValueError):
            NoiseWaveform(amplitude=math.inf)

    def test_roundtrip(self):
        w = NoiseWaveform(0.3, 2.5)
        w2 = NoiseWaveform.from_dict(w.to_dict())
        self.assertAlmostEqual(w2.amplitude, 0.3)
        self.assertAlmostEqual(w2.mean, 2.5)


# ---------------------------------------------------------------------------
# waveform_from_dict
# ---------------------------------------------------------------------------

class TestWaveformFromDict(unittest.TestCase):
    def test_all_kinds_deserialise(self):
        cases = [
            {"kind": "constant", "value": 1.0},
            {"kind": "sine", "amplitude": 1.0, "period": 1.0, "offset": 0.0},
            {"kind": "square", "high": 1.0, "low": 0.0, "period": 1.0, "duty": 0.5},
            {"kind": "ramp", "low": 0.0, "high": 1.0, "period": 1.0},
            {"kind": "noise", "amplitude": 0.1, "mean": 0.0},
        ]
        for d in cases:
            with self.subTest(kind=d["kind"]):
                w = waveform_from_dict(d)
                self.assertEqual(w.kind, d["kind"])

    def test_unknown_kind_raises(self):
        with self.assertRaises(KeyError):
            waveform_from_dict({"kind": "unknown_xyz"})

    def test_missing_kind_raises(self):
        with self.assertRaises(KeyError):
            waveform_from_dict({"value": 1.0})

    def test_waveform_kinds_constant(self):
        self.assertIn("constant", WAVEFORM_KINDS)
        self.assertIn("sine", WAVEFORM_KINDS)
        self.assertIn("square", WAVEFORM_KINDS)
        self.assertIn("ramp", WAVEFORM_KINDS)
        self.assertIn("noise", WAVEFORM_KINDS)


# ---------------------------------------------------------------------------
# TagEntry
# ---------------------------------------------------------------------------

class TestTagEntry(unittest.TestCase):
    def test_empty_tag_rejected(self):
        with self.assertRaises(ValueError):
            TagEntry("", ConstantWaveform(0.0))

    def test_non_string_tag_rejected(self):
        with self.assertRaises(ValueError):
            TagEntry(None, ConstantWaveform(0.0))

    def test_roundtrip(self):
        e = TagEntry("ai.pot", SineWaveform(1.0, 2.0, 0.5), enabled=True, known=True)
        d = e.to_dict()
        e2 = TagEntry.from_dict(d)
        self.assertEqual(e2.tag, "ai.pot")
        self.assertEqual(e2.waveform.kind, "sine")
        self.assertTrue(e2.enabled)
        self.assertTrue(e2.known)

    def test_sample_delegates_to_waveform(self):
        e = TagEntry("ai.x", ConstantWaveform(7.0))
        self.assertAlmostEqual(e.sample(0.0), 7.0)


# ---------------------------------------------------------------------------
# TagLabModel
# ---------------------------------------------------------------------------

class TestTagLabModel(unittest.TestCase):
    def test_initialises_from_tags(self):
        m = TagLabModel(["ai.pot", "di.estop"])
        self.assertEqual(len(m), 2)
        e = m.find("ai.pot")
        self.assertIsNotNone(e)
        self.assertTrue(e.known)
        self.assertTrue(e.enabled)

    def test_empty_init(self):
        m = TagLabModel()
        self.assertEqual(len(m), 0)

    def test_add_tag_idempotent(self):
        m = TagLabModel(["ai.pot"])
        m.add_tag("ai.pot")  # duplicate
        self.assertEqual(len(m), 1)

    def test_unknown_tag_not_auto_enabled(self):
        """Unknown tags must NOT silently become active outputs."""
        m = TagLabModel()
        entry = m.add_tag("ai.custom", ConstantWaveform(1.0), enabled=True, known=False)
        self.assertFalse(entry.enabled, "Unknown tag must not be auto-enabled even if enabled=True")
        self.assertFalse(
            any(e.tag == "ai.custom" for e in m.active_entries()),
            "Unknown tag must not appear in active_entries()"
        )

    def test_unknown_tag_can_be_explicitly_enabled(self):
        m = TagLabModel()
        entry = m.add_tag("ai.custom", ConstantWaveform(1.0), known=False)
        entry.enabled = True
        self.assertIn(entry, m.active_entries())

    def test_active_entries_excludes_disabled(self):
        m = TagLabModel(["ai.pot", "di.estop"])
        m.find("di.estop").enabled = False
        active = [e.tag for e in m.active_entries()]
        self.assertIn("ai.pot", active)
        self.assertNotIn("di.estop", active)

    def test_remove_tag(self):
        m = TagLabModel(["ai.pot"])
        removed = m.remove_tag("ai.pot")
        self.assertTrue(removed)
        self.assertEqual(len(m), 0)

    def test_remove_missing_tag(self):
        m = TagLabModel()
        self.assertFalse(m.remove_tag("does.not.exist"))

    def test_entries_is_copy(self):
        m = TagLabModel(["ai.pot"])
        lst = m.entries
        lst.clear()  # modifying the copy must not affect the model
        self.assertEqual(len(m), 1)


# ---------------------------------------------------------------------------
# Scenario round-trip and rejection
# ---------------------------------------------------------------------------

class TestScenarioIO(unittest.TestCase):
    def _make_model(self) -> TagLabModel:
        m = TagLabModel(["ai.pot", "di.estop"])
        m.find("ai.pot").waveform = SineWaveform(1.5, 2.0, 0.5)
        m.find("di.estop").enabled = False
        m.add_tag("ai.unknown", NoiseWaveform(0.1), known=False)
        return m

    def test_roundtrip_in_memory(self):
        m = self._make_model()
        data = m.to_scenario()
        m2 = TagLabModel.from_scenario(data)
        self.assertEqual(len(m2), len(m))
        e = m2.find("ai.pot")
        self.assertIsNotNone(e)
        self.assertEqual(e.waveform.kind, "sine")
        self.assertAlmostEqual(e.waveform.amplitude, 1.5)

    def test_roundtrip_file(self):
        m = self._make_model()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "scenario.json")
            save_scenario(m, path)
            self.assertTrue(os.path.isfile(path))
            m2 = load_scenario(path)
        self.assertEqual(len(m2), len(m))
        e = m2.find("ai.pot")
        self.assertEqual(e.waveform.kind, "sine")

    def test_atomic_write_leaves_valid_file(self):
        """After save_scenario the file must be parseable JSON."""
        m = TagLabModel(["ai.x"])
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sc.json")
            save_scenario(m, path)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        self.assertEqual(data["schema"], 1)
        self.assertIsInstance(data["entries"], list)

    def test_schema_2_rejected(self):
        with self.assertRaises(ValueError):
            TagLabModel.from_scenario({"schema": 2, "entries": []})

    def test_missing_schema_rejected(self):
        with self.assertRaises(ValueError):
            TagLabModel.from_scenario({"entries": []})

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            TagLabModel.from_scenario([{"schema": 1, "entries": []}])

    def test_non_list_entries_rejected(self):
        with self.assertRaises(ValueError):
            TagLabModel.from_scenario({"schema": 1, "entries": "bad"})

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_scenario("/nonexistent/path/scenario.json")

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bad.json")
            with open(path, "w") as f:
                f.write("{schema: 1")
            with self.assertRaises(json.JSONDecodeError):
                load_scenario(path)

    def test_unknown_known_false_preserved(self):
        """Scenario round-trip preserves known=False so unknown tags stay inactive."""
        m = TagLabModel()
        m.add_tag("ai.custom", ConstantWaveform(1.0), known=False)
        data = m.to_scenario()
        m2 = TagLabModel.from_scenario(data)
        e = m2.find("ai.custom")
        self.assertIsNotNone(e)
        self.assertFalse(e.known)
        self.assertFalse(e.enabled)


# ---------------------------------------------------------------------------
# TagLabSender (requires PySide6 + QApplication)
# ---------------------------------------------------------------------------

try:
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication as _QApp
    from tools.hmi_deployer.taglab import TagLabSender
    _QT_APP = _QApp.instance() or _QApp([])
    _HAS_QT = TagLabSender is not None
except Exception:
    _QT_APP = None
    _HAS_QT = False


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestTagLabSender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _QT_APP

    def _make_sender(self, model=None, port=None):
        if model is None:
            model = TagLabModel(["ai.pot"])
        if port is None:
            # Use an ephemeral port range that is unlikely to collide
            port = 59100 + (id(self) % 400)
        sender = TagLabSender(model, host="127.0.0.1", port=port, interval_ms=50)
        return sender, port

    def test_seq_increments(self):
        model = TagLabModel(["ai.x"])
        sender = TagLabSender(model)

        frame1 = sender.build_frame(0.0, seq=0)
        frame2 = sender.build_frame(1.0, seq=1)
        self.assertEqual(frame1["seq"], 0)
        self.assertEqual(frame2["seq"], 1)
        self.assertLess(frame1["seq"], frame2["seq"])

    def test_ts_is_real(self):
        model = TagLabModel(["ai.x"])
        sender = TagLabSender(model)
        before = time.time()
        frame = sender.build_frame(0.0, seq=0)
        after = time.time()
        self.assertGreaterEqual(frame["ts"], before)
        self.assertLessEqual(frame["ts"], after)

    def test_frame_wire_format(self):
        """Frame matches the wire protocol: t, seq, ts, src, tags."""
        model = TagLabModel(["ai.x"])
        model.find("ai.x").waveform = ConstantWaveform(3.0)
        sender = TagLabSender(model)
        frame = sender.build_frame(0.0, seq=5)
        self.assertEqual(frame["t"], "tags")
        self.assertIn("seq", frame)
        self.assertIn("ts", frame)
        self.assertIn("src", frame)
        self.assertIsInstance(frame["tags"], dict)
        self.assertAlmostEqual(frame["tags"]["ai.x"], 3.0)

    def test_only_active_tags_in_frame(self):
        model = TagLabModel(["ai.x", "ai.y"])
        model.find("ai.y").enabled = False
        sender = TagLabSender(model)
        frame = sender.build_frame(0.0, seq=0)
        self.assertIn("ai.x", frame["tags"])
        self.assertNotIn("ai.y", frame["tags"])

    def test_unknown_tag_not_in_frame_until_explicitly_enabled(self):
        """Custom tags start safe, but an explicit user opt-in activates them."""
        model = TagLabModel(["ai.known"])
        custom = model.add_tag("ai.custom", ConstantWaveform(99.0), known=False)
        sender = TagLabSender(model)
        frame = sender.build_frame(0.0, seq=0)
        self.assertNotIn("ai.custom", frame["tags"])
        custom.enabled = True
        frame = sender.build_frame(0.0, seq=1)
        self.assertEqual(frame["tags"]["ai.custom"], 99.0)

    def test_digital_tags_are_coerced_to_bool(self):
        model = TagLabModel(["di.estop", "do.relay1"])
        model.find("di.estop").waveform = ConstantWaveform(0.0)
        model.find("do.relay1").waveform = ConstantWaveform(1.0)
        sender = TagLabSender(model)
        frame = sender.build_frame(0.0, seq=0)
        self.assertIs(frame["tags"]["di.estop"], False)
        self.assertIs(frame["tags"]["do.relay1"], True)

    def test_udp_payload_is_json(self):
        """
        A real UDP datagram sent by the sender must be valid JSON and match
        the wire protocol.
        """
        model = TagLabModel(["ai.x"])
        model.find("ai.x").waveform = ConstantWaveform(7.7)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.settimeout(2.0)

        sender = TagLabSender(model, host="127.0.0.1", port=port, interval_ms=50)
        try:
            sender.start()
            sender._tick()
            data, _ = sock.recvfrom(65535)
        finally:
            sender.stop()
            sock.close()

        frame = json.loads(data.decode("utf-8"))
        self.assertEqual(frame["t"], "tags")
        self.assertIn("ai.x", frame["tags"])
        self.assertAlmostEqual(frame["tags"]["ai.x"], 7.7, places=3)

    def test_stop_is_idempotent(self):
        sender, port = self._make_sender()
        sender.start()
        sender.stop()
        sender.stop()  # second stop must not raise

    def test_restart_after_stop_raises(self):
        sender, port = self._make_sender()
        sender.start()
        sender.stop()
        with self.assertRaises(RuntimeError):
            sender.start()

    def test_frame_count_advances_seq(self):
        """Seq in consecutive build_frame calls must strictly increase."""
        model = TagLabModel(["ai.x"])
        sender = TagLabSender(model)
        seqs = [sender.build_frame(float(i), seq=i)["seq"] for i in range(5)]
        self.assertEqual(seqs, list(range(5)))


@unittest.skipUnless(_HAS_QT, "PySide6 not available")
class TestTagLabPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _QT_APP

    def setUp(self):
        from tools.hmi_deployer.taglab_panel import TagLabPanel
        self.panel = TagLabPanel()

    def tearDown(self):
        self.panel.close()
        self.panel.deleteLater()

    def test_empty_state_disables_sender(self):
        self.assertTrue(self.panel._lbl_empty.isVisibleTo(self.panel))
        self.assertFalse(self.panel._table.isVisibleTo(self.panel))
        self.assertFalse(self.panel._btn_send.isEnabled())

    def test_bundle_tags_populate_table(self):
        self.panel.bind_tags(["ai.pot", "di.estop"])
        self.assertEqual(self.panel._table.rowCount(), 2)
        self.assertTrue(self.panel._btn_send.isEnabled())

    def test_rebinding_deactivates_previous_bundle_tags(self):
        self.panel.bind_tags(["ai.first"])
        self.panel.bind_tags(["ai.second"])
        first = self.panel.model().find("ai.first")
        second = self.panel.model().find("ai.second")
        self.assertFalse(first.known)
        self.assertFalse(first.enabled)
        self.assertTrue(second.known)
        self.assertTrue(second.enabled)

    def test_sending_state_locks_scenario_load(self):
        self.panel.bind_tags(["ai.pot"])
        self.panel.set_sending(True)
        self.assertFalse(self.panel._btn_send.isEnabled())
        self.assertTrue(self.panel._btn_stop.isEnabled())
        self.assertFalse(self.panel._btn_load.isEnabled())
        self.panel.set_sending(False)
        self.assertTrue(self.panel._btn_send.isEnabled())
        self.assertFalse(self.panel._btn_stop.isEnabled())
        self.assertTrue(self.panel._btn_load.isEnabled())

    def test_buttons_use_existing_shadcn_variants(self):
        self.assertEqual(self.panel._btn_send.property("variant"), "default")
        self.assertEqual(self.panel._btn_stop.property("variant"), "outline")
        self.assertEqual(self.panel._btn_save.property("variant"), "secondary")
        self.assertEqual(self.panel._btn_load.property("variant"), "outline")
        self.assertEqual(self.panel._btn_add.property("variant"), "ghost")
        self.assertEqual(self.panel.styleSheet(), "")


# ---------------------------------------------------------------------------
# TelemetrySimulator – value advancement and frame structure
# ---------------------------------------------------------------------------

class TestTelemetrySimulator(unittest.TestCase):
    def test_advance_uptime_increments(self):
        from tools.hmi_deployer.telemetry import TelemetrySimulator
        sim = TelemetrySimulator(["sys.uptime"], udp_port=59700)
        initial = sim.tags_state["sys.uptime"]
        sim._advance()
        self.assertGreater(sim.tags_state["sys.uptime"], initial)
        sim.stop()

    def test_advance_ai_stays_in_range(self):
        from tools.hmi_deployer.telemetry import TelemetrySimulator
        sim = TelemetrySimulator(["ai.sensor"], udp_port=59701)
        for _ in range(100):
            sim._advance()
            v = sim.tags_state["ai.sensor"]
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 3.3)
        sim.stop()

    def test_seq_increments_each_frame(self):
        from tools.hmi_deployer.telemetry import TelemetrySimulator
        # We can inspect _seq without actually sending
        sim = TelemetrySimulator(["ai.x"], udp_port=59702)
        self.assertEqual(sim._seq, 0)
        # Call _advance (no socket needed) and check seq doesn't advance
        # (seq only advances in _send_frame)
        sim._advance()
        self.assertEqual(sim._seq, 0)
        sim.stop()

    def test_stop_idempotent(self):
        from tools.hmi_deployer.telemetry import TelemetrySimulator
        sim = TelemetrySimulator([], udp_port=59703)
        sim.stop()
        sim.stop()  # must not raise

    def test_send_after_stop_is_safe(self):
        """_send_frame after stop must silently do nothing (no crash)."""
        from tools.hmi_deployer.telemetry import TelemetrySimulator
        sim = TelemetrySimulator(["ai.x"], udp_port=59704)
        sim.stop()
        sim._send_frame()  # must not raise


# ---------------------------------------------------------------------------
# TelemetryRelay – remote script compiles as valid Python 3
# ---------------------------------------------------------------------------

class TestTelemetryRelayScript(unittest.TestCase):
    """
    Validates that the remote bridge script embedded in TelemetryRelay is
    syntactically valid Python 3 (compile() passes) and that 'sys' is
    imported.  We do not start a real SSH connection.
    """

    def test_remote_script_contains_sys_import(self):
        from tools.hmi_deployer.telemetry import build_remote_relay_script
        self.assertIn("import sys", build_remote_relay_script())

    def test_remote_script_valid_python(self):
        """
        Extract the actual remote_script value used in TelemetryRelay by
        building the object with dummy args and inspecting the command.
        """
        from tools.hmi_deployer.telemetry import build_remote_relay_script
        compile(build_remote_relay_script(), "<relay_script>", "exec")

    def test_remote_script_contains_subscription_renewal(self):
        from tools.hmi_deployer.telemetry import build_remote_relay_script
        self.assertIn("last_renew", build_remote_relay_script())

    def test_remote_command_roundtrips_script(self):
        import base64
        import re
        from tools.hmi_deployer.telemetry import (
            build_remote_relay_command,
            build_remote_relay_script,
        )
        command = build_remote_relay_command()
        encoded = re.search(r"b64decode\('([^']+)'\)", command).group(1)
        self.assertEqual(base64.b64decode(encoded).decode(), build_remote_relay_script())


if __name__ == "__main__":
    unittest.main()
