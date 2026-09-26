"""tag_source defects found in review that the frozen gate did not cover."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.tag_source import EngineTagSource, SimulatedTagSource  # noqa: E402


class Engine(QObject):
    onlineChanged = Signal()

    def __init__(self):
        super().__init__()
        self.online = False

    def get_online(self):
        return self.online

    def value(self, name, fallback=None):
        return fallback

    def write(self, tag, value):
        pass


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class TagSourceQcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_no_relay_before_start_and_again_after_restart(self):
        engine = Engine()
        src = EngineTagSource(engine)
        seen = []
        src.onlineChanged.connect(seen.append)
        engine.online = True
        engine.onlineChanged.emit()
        self.assertEqual(seen, [], "not started: nothing relayed")
        src.start()
        src.stop()
        src.start()
        engine.online = False
        engine.onlineChanged.emit()
        self.assertEqual(seen, [True, True, False])

    def test_elapsed_is_zero_before_start(self):
        sim = SimulatedTagSource(["sys.uptime"], clock=Clock())
        self.assertEqual(sim.value("sys.uptime"), 0.0)

    def test_sample_ignores_overrides(self):
        sim = SimulatedTagSource(["ai.rpm"], clock=Clock())
        sim.write("ai.rpm", 42.0)
        self.assertEqual(sim.value("ai.rpm"), 42.0)
        self.assertNotEqual(sim.sample("ai.rpm", 0.0), 42.0)

    def test_range_covers_whole_dial(self):
        sim = SimulatedTagSource(["ai.rpm"])
        sim.set_range("ai.rpm", 0, 6000)
        values = [sim.sample("ai.rpm", t / 10) for t in range(200)]
        self.assertLess(min(values), 300)
        self.assertGreater(max(values), 5700)


if __name__ == "__main__":
    unittest.main()
