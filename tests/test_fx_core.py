"""ui/python/fx/__init__.py -- the shared clock, the switch, FxWidget."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, clock_has, coverage  # noqa: F401  (sets sys.path)

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

import ui.python.fx as fx  # noqa: E402


class _Dot(fx.FxWidget):
    def __init__(self):
        super().__init__()
        self.resize(20, 20)
        self.ticks = []

    def paint_frame(self, painter, t):
        painter.fillRect(QRectF(0, 0, 10 + (t % 1) * 10, 20), QColor("#ff0000"))

    def advance(self, t, dt):
        self.ticks.append((t, dt))


class FxCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)
        self.addCleanup(fx.set_animations_enabled, True)

    def test_start_stop_subscribes(self):
        w = _Dot()
        self.addCleanup(w.deleteLater)
        w.start()
        self.assertTrue(clock_has(w) and fx.FxClock.instance().is_running())
        w.stop()
        self.assertFalse(clock_has(w))

    def test_switch_off_stops_and_still_frame(self):
        w = _Dot()
        self.addCleanup(w.deleteLater)
        w.start()
        fx.set_animations_enabled(False)
        self.assertFalse(fx.animations_enabled())
        self.assertFalse(clock_has(w))
        self.assertFalse(w.animating())
        fx.set_animations_enabled(True)
        self.assertTrue(clock_has(w))

    def test_tick_advances_with_capped_dt(self):
        w = _Dot()
        self.addCleanup(w.deleteLater)
        w.start()
        w._tick(100.0)
        w._tick(100.5)
        self.assertEqual(w.ticks, [(100.0, 0.0), (100.5, 0.1)])

    def test_hidden_widgets_are_skipped(self):
        w = _Dot()
        self.addCleanup(w.deleteLater)
        w.start()
        fx.FxClock.instance()._tick()          # not shown: no callback
        self.assertEqual(w.ticks, [])
        w.show()
        fx.FxClock.instance()._tick()
        self.assertEqual(len(w.ticks), 1)

    def test_render_at(self):
        w = _Dot()
        self.addCleanup(w.deleteLater)
        self.assertGreater(coverage(w.render_at(0.5)), 0.7)

    def test_helpers(self):
        self.assertAlmostEqual(fx.EASE_IN_OUT(0.5), 0.5, places=4)
        self.assertAlmostEqual(fx.EASE(1.0), 1.0, places=4)
        self.assertEqual(fx.js_round(2.5), 3)
        self.assertEqual(fx.js_round(-2.5), -2)
        self.assertAlmostEqual(fx.smoothstep(0, 1, 0.5), 0.5)
        self.assertTrue(0 <= fx.hash01(3, 4) < 1)


if __name__ == "__main__":
    unittest.main()
