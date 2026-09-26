"""Extra tests for designer/ide/tag_source.py (W3)."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.tag_source import EngineTagSource, SimulatedTagSource, ranges_from_index  # noqa: E402
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

    def get_online(self):
        return self.online

    def value(self, name, fallback=None):
        return self.values.get(name, fallback)

    def write(self, tag, value):
        self.writes.append((tag, value))


class EngineExtraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_name_and_engine_identity(self):
        engine = FakeEngine()
        src = EngineTagSource(engine)
        self.assertEqual(src.name(), "Panel")
        self.assertIs(src.engine(), engine)

    def test_double_start_stop_no_double_signal(self):
        engine = FakeEngine()
        engine.online = True
        src = EngineTagSource(engine)
        seen = []
        src.onlineChanged.connect(seen.append)
        src.start()
        src.start()
        engine.onlineChanged.emit()
        src.stop()
        src.stop()
        # One True on start; the relay is live once; stop says nothing.
        self.assertEqual(seen, [True])
        engine = FakeEngine()
        src = EngineTagSource(engine)
        self.assertFalse(src.write("do.pump", "hi"))
        self.assertFalse(src.write("do.pump", [1]))
        self.assertFalse(src.write("do.pump", {"k": 1}))


class SimulatorExtraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_tags_sorted(self):
        sim = SimulatedTagSource(["z.1", "a.1", "m.1"])
        self.assertEqual(sim.tags(), ["a.1", "m.1", "z.1"])

    def test_unknown_tag_reads_none(self):
        sim = SimulatedTagSource(["ai.rpm"])
        self.assertIsNone(sim.value("nope"))

    def test_range_scaling_bound(self):
        sim = SimulatedTagSource(["ai.rpm"])
        sim.set_range("ai.rpm", 0, 6000)
        for t in (0.0, 0.5, 1.0, 2.0, 3.3):
            # The 10..90 wave spans the whole 0..6000 dial.
            self.assertTrue(-1e-6 <= sim.sample("ai.rpm", t) <= 6000 + 1e-6, sim.sample("ai.rpm", t))
        sim.set_tags(["ai.rpm"])
        self.assertTrue(10 <= sim.sample("ai.rpm", 0.5) <= 90)


class RangesExtraTests(unittest.TestCase):
    def test_ranges_from_index_second_widget_wins_first(self):
        project = make_project()
        project.pages[0].widgets[0].properties.update({"minimum": 0, "maximum": 6000})
        project.pages[1].widgets.append(widget("ShGauge", "g2", bindings={"value": DesignerBinding("ai.oiltemp")},
                                                minimum=1, maximum=2))
        project.pages[1].widgets.append(widget("ShGauge", "g3", bindings={"value": DesignerBinding("ai.oiltemp")},
                                                minimum=10, maximum=20))
        ranges = ranges_from_index(DesignIndex.build(project))
        self.assertEqual(ranges["ai.oiltemp"], (1.0, 2.0))
        self.assertNotIn("ai.rpm", ranges) if False else self.assertEqual(ranges["ai.rpm"], (0.0, 6000.0))


if __name__ == "__main__":
    unittest.main()