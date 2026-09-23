"""ui/python/fx/liquid.py -- W-E's gate.

FROZEN: the tests below are the minimum; add more in a new class at the
bottom, never change these.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, clock_has  # noqa: E402

from PySide6.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import ui.python.fx as fx  # noqa: E402
from ui.python.fx.liquid import LiquidTabBar  # noqa: E402

NAMES = ("Designer", "AI Design", "Code", "Display Console", "Tag Lab")


def _drive(bar, seconds, base=None, step=1 / 60):
    """Advance the bar's animation by calling its clock callback directly."""
    from ui.python.fx import FxClock
    t = fx.now() if base is None else base
    end = t + seconds
    while t < end:
        t += step
        entry = FxClock.instance()._subs.get(id(bar))
        if entry is None:
            break
        entry[1](t)
    return t


class LiquidTabBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)
        self.bar = LiquidTabBar()
        self.addCleanup(self.bar.deleteLater)
        for name in NAMES:
            self.bar.addTab(name)
        self.bar.resize(self.bar.sizeHint())
        self.bar.show()
        self.app.processEvents()

    def test_is_a_tab_bar(self):
        seen = []
        self.bar.currentChanged.connect(seen.append)
        QTest.mouseClick(self.bar, Qt.LeftButton, pos=self.bar.tabRect(2).center())
        self.assertEqual(self.bar.currentIndex(), 2)
        self.assertEqual(seen, [2])

    def test_rests_under_the_current_tab(self):
        self.assertTrue(self.bar.settled())
        pill = self.bar.pill_rect()
        self.assertAlmostEqual(pill.center().x(), self.bar.tabRect(0).center().x(), delta=1.0)
        self.assertFalse(clock_has(self.bar), "no clock while settled")

    def test_flows_to_a_new_tab_and_settles(self):
        self.bar.setCurrentIndex(3)
        self.assertTrue(clock_has(self.bar))
        t = _drive(self.bar, 0.07)
        pill = self.bar.pill_rect()
        start, end = self.bar.tabRect(0).center().x(), self.bar.tabRect(3).center().x()
        self.assertTrue(start < pill.center().x() < end, "moving between the tabs")
        goo = self.bar.goo_path().boundingRect()
        self.assertGreater(goo.width(), self.bar.tabRect(3).width() * 0.9, "stretched / tailed while moving")
        _drive(self.bar, 1.5, base=t)
        self.assertTrue(self.bar.settled())
        self.assertAlmostEqual(self.bar.pill_rect().center().x(), end, delta=1.0)
        self.assertFalse(clock_has(self.bar))

    def test_jumps_when_animations_are_off(self):
        fx.set_animations_enabled(False)
        self.addCleanup(fx.set_animations_enabled, True)
        self.bar.setCurrentIndex(4)
        self.assertTrue(self.bar.settled())
        self.assertAlmostEqual(self.bar.pill_rect().center().x(), self.bar.tabRect(4).center().x(), delta=1.0)

    def test_paints_the_pill_under_the_selected_tab(self):
        self.bar.set_colors(QColor("#006fee"), QColor("#ffffff"), QColor("#a1a1aa"), QColor("#18181b"))
        self.bar.setCurrentIndex(1)
        _drive(self.bar, 1.5)
        image = self.bar.grab().toImage()
        r = self.bar.tabRect(1)
        edge = QColor(image.pixel(r.left() + 6, r.center().y()))
        self.assertLess(abs(edge.blue() - 0xee) + abs(edge.red() - 0x00), 90, edge.name())

    def test_themes(self):
        self.bar.set_theme("light")
        self.bar.set_theme("dark")
        self.bar.grab()


if __name__ == "__main__":
    unittest.main()
