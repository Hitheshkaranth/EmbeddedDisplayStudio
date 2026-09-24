"""ui/python/fx/liquid.py -- the liquid effect."""
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


class LiquidTabBarBehaviourTests(unittest.TestCase):
    """Further checks: the goo stays one piece, retargeting, the switch."""

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

    def _one_piece(self, path):
        from PySide6.QtCore import QPointF
        box = path.boundingRect()
        cy = self.bar.pill_rect().center().y()
        x = box.left() + 0.75
        while x < box.right() - 0.75:
            if not path.contains(QPointF(x, cy)):
                return False
            x += 0.5
        return True

    def test_goo_is_never_detached(self):
        self.bar.setCurrentIndex(4)
        t = fx.now()
        grew_tail = False
        for _ in range(90):
            t = _drive(self.bar, 1 / 60, base=t)
            goo = self.bar.goo_path()
            if goo.boundingRect().width() > self.bar.pill_rect().width() + 2:
                grew_tail = True
            self.assertTrue(self._one_piece(goo), "a gap along the goo's axis")
        self.assertTrue(grew_tail, "the drop never stretched or grew a tail")

    def test_retarget_mid_flight_settles_on_the_last_tab(self):
        self.bar.setCurrentIndex(4)
        t = _drive(self.bar, 0.08)
        self.bar.setCurrentIndex(1)
        self.assertTrue(clock_has(self.bar))
        _drive(self.bar, 2.0, base=t)
        self.assertTrue(self.bar.settled())
        self.assertAlmostEqual(self.bar.pill_rect().center().x(),
                               self.bar.tabRect(1).center().x(), delta=1.0)
        self.assertFalse(clock_has(self.bar))

    def test_switch_off_mid_flight_jumps(self):
        self.bar.setCurrentIndex(3)
        _drive(self.bar, 0.05)
        fx.set_animations_enabled(False)
        self.addCleanup(fx.set_animations_enabled, True)
        self.assertTrue(self.bar.settled())
        self.assertFalse(clock_has(self.bar))
        self.assertAlmostEqual(self.bar.pill_rect().center().x(),
                               self.bar.tabRect(3).center().x(), delta=1.0)

    def test_big_frame_gap_stays_stable(self):
        self.bar.setCurrentIndex(4)
        t = _drive(self.bar, 0.02)
        _drive(self.bar, 3.0, base=t, step=0.5)       # dt capped at 0.1
        pill = self.bar.pill_rect()
        self.assertTrue(abs(pill.center().x()) < 10 * self.bar.width())
        _drive(self.bar, 2.0, base=t + 3.0)
        self.assertTrue(self.bar.settled())

    def test_icons_and_style_sheet(self):
        from PySide6.QtGui import QIcon, QPixmap
        pix = QPixmap(16, 16)
        pix.fill(QColor("#ffffff"))
        self.bar.setTabIcon(0, QIcon(pix))
        self.bar.setObjectName("primaryNav")
        self.bar.setStyleSheet("QTabBar#primaryNav::tab { padding: 9px 18px; margin-right: 8px;"
                               " border-radius: 16px; background: #27272a; }")
        self.app.processEvents()
        self.bar.set_colors(QColor("#006fee"), QColor("#ffffff"), QColor("#a1a1aa"), QColor(0, 0, 0, 0))
        image = self.bar.grab().toImage()
        r = self.bar.tabRect(0)
        pill = self.bar.pill_rect()
        self.assertLess(pill.right(), r.right() - 4, "the ::tab margin is not under the pill")
        edge = QColor(image.pixel(int(pill.left()) + 6, int(pill.center().y())))
        self.assertEqual(edge.name(), "#006fee")
