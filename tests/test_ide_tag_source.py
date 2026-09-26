"""designer/ide/tag_source.py (FROZEN gate for W3)."""
import os
import sys
import time
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.tag_source import (  # noqa: E402
    SIM_PERIOD_MS, EngineTagSource, SimulatedTagSource, TagSource, ranges_from_index,
)
from designer.model.project import DesignerBinding  # noqa: E402
from ide_v2_fixture import make_project, widget  # noqa: E402


def spin(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


class FakeEngine(QObject):
    onlineChanged = Signal()

    def __init__(self):
        super().__init__()
        self.values = {"ai.rpm": 1200.5, "di.estop": False}
        self.online = False
        self.writes = []
        self.fail = False

    def get_online(self):
        return self.online

    def value(self, name, fallback=None):
        if self.fail:
            raise RuntimeError("engine gone")
        return self.values.get(name, fallback)

    def write(self, tag, value):
        if self.fail:
            raise RuntimeError("engine gone")
        self.writes.append((tag, value))


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class BaseTests(unittest.TestCase):
    def test_base_interface(self):
        s = TagSource()
        self.assertEqual(s.snapshot(["a.b"]), {"a.b": None})
        self.assertFalse(s.write("a.b", 1))
        self.assertFalse(s.can_write())


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_reads_and_online(self):
        engine = FakeEngine()
        src = EngineTagSource(engine)
        self.assertIs(src.engine(), engine)
        self.assertEqual(src.name(), "Panel")
        self.assertEqual(src.value("ai.rpm"), 1200.5)
        self.assertIsNone(src.value("ai.none"))
        self.assertEqual(src.snapshot(["ai.rpm", "di.estop"]), {"ai.rpm": 1200.5, "di.estop": False})
        self.assertFalse(src.is_online())
        seen = []
        src.onlineChanged.connect(seen.append)
        src.start()
        engine.online = True
        engine.onlineChanged.emit()
        self.assertEqual(seen, [True])
        self.assertTrue(src.is_online())
        src.stop()
        engine.online = False
        engine.onlineChanged.emit()
        self.assertEqual(seen, [True], "stopped source must not relay")

    def test_polls_while_online(self):
        engine = FakeEngine()
        engine.online = True
        src = EngineTagSource(engine)
        ticks = []
        src.valuesChanged.connect(lambda: ticks.append(1))
        src.start()
        spin(EngineTagSource.POLL_MS * 3)
        src.stop()
        self.assertGreaterEqual(len(ticks), 1)
        n = len(ticks)
        spin(EngineTagSource.POLL_MS * 2)
        self.assertEqual(len(ticks), n)

    def test_write_and_errors(self):
        engine = FakeEngine()
        src = EngineTagSource(engine)
        self.assertTrue(src.can_write())
        self.assertTrue(src.write("do.pump", True))
        self.assertTrue(src.write("mb.sp", 3.5))
        self.assertFalse(src.write("do.pump", {"x": 1}))
        self.assertEqual(engine.writes, [("do.pump", True), ("mb.sp", 3.5)])
        engine.fail = True
        self.assertIsNone(src.value("ai.rpm"))
        self.assertFalse(src.write("do.pump", True))

    def test_none_engine(self):
        src = EngineTagSource(None)
        self.assertFalse(src.is_online())
        self.assertIsNone(src.value("ai.rpm"))
        self.assertFalse(src.can_write())
        src.start()
        src.stop()


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.clock = Clock()
        self.sim = SimulatedTagSource(["ai.rpm", "di.estop", "sys.uptime", "sys.errors"], clock=self.clock)

    def test_formula(self):
        h = zlib.crc32(b"ai.rpm")
        import math
        period = 4 + (h % 7)
        phase = math.radians(h % 360)
        for t in (0.0, 1.3, 7.77):
            want = round(50 + 40 * math.sin(2 * math.pi * t / period + phase), 3)
            self.assertAlmostEqual(self.sim.sample("ai.rpm", t), want, places=3)
        hb = zlib.crc32(b"di.estop")
        pb = 2 + (hb % 5)
        self.assertIs(self.sim.sample("di.estop", 0.0), True)
        self.assertIs(self.sim.sample("di.estop", pb * 0.75), False)
        self.assertEqual(self.sim.sample("sys.uptime", 12.5), 12.5)
        self.assertEqual(self.sim.sample("sys.errors", 12.5), 0)
        self.assertIsNone(self.sim.sample("ai.other", 1.0))

    def test_value_uses_clock_and_start(self):
        self.sim.start()
        self.clock.t += 2.0
        self.assertEqual(self.sim.value("sys.uptime"), 2.0)
        self.assertEqual(self.sim.value("ai.rpm"), self.sim.sample("ai.rpm", 2.0))
        self.sim.stop()

    def test_ranges(self):
        self.sim.set_range("ai.rpm", 0, 6000)
        for t in (0.0, 0.5, 1.0, 2.0, 3.3):
            v = self.sim.sample("ai.rpm", t)
            self.assertTrue(750 - 1e-6 <= v <= 5250 + 1e-6, v)  # 10..90 % of 0..6000
        self.sim.set_tags(["ai.rpm"])
        self.assertTrue(10 <= self.sim.sample("ai.rpm", 0.5) <= 90)
        self.assertEqual(self.sim.tags(), ["ai.rpm"])

    def test_overrides(self):
        self.assertTrue(self.sim.can_write())
        ticks = []
        self.sim.valuesChanged.connect(lambda: ticks.append(1))
        self.assertTrue(self.sim.write("ai.rpm", 42.0))
        self.assertFalse(self.sim.write("ai.unknown", 1))
        self.assertEqual(self.sim.value("ai.rpm"), 42.0)
        self.assertEqual(ticks, [1])
        self.sim.clear_overrides()
        self.assertNotEqual(self.sim.value("ai.rpm"), 42.0)

    def test_online_and_timer(self):
        seen = []
        self.sim.onlineChanged.connect(seen.append)
        ticks = []
        self.sim.valuesChanged.connect(lambda: ticks.append(1))
        self.assertFalse(self.sim.is_online())
        self.sim.start()
        self.sim.start()
        spin(SIM_PERIOD_MS * 4)
        self.sim.stop()
        self.sim.stop()
        self.assertEqual(seen, [True, False])
        self.assertGreaterEqual(len(ticks), 2)


class RangesTests(unittest.TestCase):
    def test_ranges_from_index(self):
        project = make_project()
        project.pages[0].widgets[0].properties.update({"minimum": 0, "maximum": 6000})
        project.pages[1].widgets.append(widget("ShGauge", "g2", bindings={"value": DesignerBinding("ai.oiltemp")},
                                               minValue=-40, maxValue=150))
        project.pages[1].widgets.append(widget("ShGauge", "g3", bindings={"value": DesignerBinding("ai.bad")},
                                               minimum=5, maximum=5))
        ranges = ranges_from_index(DesignIndex.build(project))
        self.assertEqual(ranges["ai.rpm"], (0.0, 6000.0))
        self.assertEqual(ranges["ai.oiltemp"], (-40.0, 150.0))
        self.assertNotIn("ai.bad", ranges)
        self.assertNotIn("di.estop", ranges)


if __name__ == "__main__":
    unittest.main()
