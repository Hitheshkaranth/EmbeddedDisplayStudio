"""ui/python/fx/metal.py and mosaic.py -- W-D's gate.

FROZEN: the tests below are the minimum; add more in a new class at the
bottom, never change these.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, clock_has, coverage, difference, distinct_colours, paint_ms, region_alpha  # noqa: E402

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath  # noqa: E402
from PySide6.QtWidgets import QLabel  # noqa: E402

import ui.python.fx as fx  # noqa: E402
from ui.python.fx.metal import PRESETS, MetalRing, paint_metal  # noqa: E402
from ui.python.fx.mosaic import REVEAL_S, MosaicView  # noqa: E402


def _metal_image(t, preset="chromatic", theme="dark", w=140, h=40):
    image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(10, 5, w - 20, h - 10), (h - 10) / 2, (h - 10) / 2)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    try:
        paint_metal(painter, path, t, preset=preset, theme=theme)
    finally:
        painter.end()
    return image


class MetalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def test_fills_only_the_path_with_stripes(self):
        image = _metal_image(2.0)
        self.assertLess(region_alpha(image, 0, 0, 1, .1), 4)            # outside the pill
        self.assertGreater(region_alpha(image, .3, .4, .7, .6), 200)     # inside
        light = [QColor.fromRgba(image.pixel(x, 20)).lightness() for x in range(30, 110)]
        self.assertGreater(max(light) - min(light), 90)                  # bright and dark bands

    def test_it_flows(self):
        self.assertGreater(difference(_metal_image(1.0), _metal_image(1.7)), 2.0)

    def test_presets_differ_and_gold_is_warm(self):
        images = {p: _metal_image(2.0, preset=p) for p in PRESETS}
        self.assertGreater(difference(images["gold"], images["silver"]), 2.0)
        gold = [QColor.fromRgba(images["gold"].pixel(x, 20)) for x in range(20, 120)]
        self.assertGreater(sum(c.red() for c in gold), sum(c.blue() for c in gold) * 1.1)

    def test_light_theme(self):
        self.assertGreater(region_alpha(_metal_image(2.0, theme="light"), .3, .4, .7, .6), 200)

    def test_ring_wraps_a_child(self):
        label = QLabel("L")
        ring = MetalRing(label, ring=2, padding=3)
        self.addCleanup(ring.deleteLater)
        ring.resize(46, 46)
        ring.show()
        self.app.processEvents()
        self.assertIs(ring.child(), label)
        self.assertIs(label.parent(), ring)
        inner = label.geometry()
        self.assertGreaterEqual(inner.left(), 5)
        self.assertLessEqual(inner.right(), 46 - 5)
        image = ring.render_at(3.0)
        self.assertGreater(region_alpha(image, .45, 0, .55, .04), 150)  # the band at the top
        self.assertEqual(ring.ring_rect().width(), 46)
        ring.start()
        self.assertTrue(clock_has(ring))

    def test_paint_budget(self):
        label = QLabel()
        ring = MetalRing(label)
        self.addCleanup(ring.deleteLater)
        ring.resize(60, 60)
        self.assertLess(paint_ms(ring), 10.0)


class MosaicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def _view(self, w=320, h=200):
        view = MosaicView()
        view.resize(w, h)
        self.addCleanup(view.deleteLater)
        return view

    def _image(self, colour="#3a7bd5", w=160, h=100):
        image = QImage(w, h, QImage.Format_ARGB32)
        image.fill(QColor(colour))
        return image

    def _run(self, view, seconds, base, step=1 / 15):
        t = base
        while t < base + seconds:
            t += step
            view._tick(t)
        return t

    def test_loader_is_a_moving_mosaic(self):
        view = self._view()
        view.set_loading()
        self.assertTrue(view.loading())
        self.assertTrue(clock_has(view))
        base = fx.now()
        t = self._run(view, 0.3, base)
        a, b = view.render_at(t), view.render_at(t + 0.8)
        self.assertGreater(coverage(a, step=3), 0.05)
        self.assertGreaterEqual(distinct_colours(a), 3)
        self.assertGreater(difference(a, b), 0.3)

    def test_reveal_ends_on_the_image(self):
        view = self._view()
        view.set_loading()
        base = fx.now()
        t = self._run(view, 0.3, base)
        view.set_image(self._image())
        self.assertTrue(view.revealing())
        self.assertFalse(view.loading())
        t = self._run(view, REVEAL_S + 0.5, t)
        self.assertFalse(view.revealing())
        self.assertFalse(clock_has(view))
        centre = QColor.fromRgba(view.render_at(t).pixel(160, 100))
        self.assertLess(abs(centre.red() - 0x3a) + abs(centre.green() - 0x7b) + abs(centre.blue() - 0xd5), 30)

    def test_image_without_loading_shows_at_once(self):
        view = self._view()
        view.set_image(self._image("#d53a3a"))
        self.assertFalse(view.revealing())
        self.assertIsNotNone(view.image())
        centre = QColor.fromRgba(view.render_at(fx.now()).pixel(160, 100))
        self.assertGreater(centre.red(), 180)

    def test_message(self):
        view = self._view()
        view.set_loading()
        view.set_message("Nothing selected")
        self.assertEqual(view.message(), "Nothing selected")
        self.assertFalse(view.loading())
        self.assertFalse(clock_has(view))

    def test_light_theme_and_budget(self):
        view = self._view()
        view.set_theme("light")
        view.set_loading()
        self.assertGreater(coverage(view.render_at(fx.now() + 1), step=3), 0.05)
        self.assertLess(paint_ms(view), 25.0)


if __name__ == "__main__":
    unittest.main()
