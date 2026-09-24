"""ui/python/fx/metal.py and mosaic.py -- the metal and mosaic effects."""
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


class MetalMosaicExtraTests(unittest.TestCase):
    """Further metal and mosaic checks."""

    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)
        self.addCleanup(fx.set_animations_enabled, True)

    def test_paint_metal_restores_painter_state(self):
        image = QImage(80, 30, QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            painter.setOpacity(0.7)
            painter.setClipRect(QRectF(0, 0, 60, 30))
            path = QPainterPath()
            path.addRoundedRect(QRectF(2, 2, 76, 26), 13, 13)
            paint_metal(painter, path, 5.0, preset="gold", theme="light")
            self.assertAlmostEqual(painter.opacity(), 0.7, places=3)
            self.assertTrue(painter.hasClipping())
            self.assertEqual(painter.clipBoundingRect().toRect().width(), 60)
            paint_metal(painter, QPainterPath(), 5.0)          # empty path: a no-op
        finally:
            painter.end()
        self.assertLess(region_alpha(image, .8, .3, 1, .7), 4)  # the clip held

    def test_silver_is_neutral_and_chromatic_has_a_fringe(self):
        silver = [QColor.fromRgba(_metal_image(2.0, preset="silver").pixel(x, 20)) for x in range(20, 120)]
        self.assertLess(abs(sum(c.red() for c in silver) - sum(c.blue() for c in silver)),
                        sum(c.red() for c in silver) * 0.12)
        chroma = _metal_image(2.0, preset="chromatic")
        spread = max(max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())
                     for c in (QColor.fromRgba(chroma.pixel(x, y)) for x in range(20, 120) for y in (12, 20, 28)))
        self.assertGreater(spread, 60)

    def test_ring_radius_and_still_frame(self):
        ring = MetalRing(QLabel("E"), ring=3, radius=6, padding=2, preset="silver")
        self.addCleanup(ring.deleteLater)
        ring.resize(80, 40)
        self.assertEqual(ring.child().geometry().left(), 5)
        self.assertGreaterEqual(ring.sizeHint().width(), ring.child().sizeHint().width() + 10)
        image = ring.render_at(1.0)
        round_ring = MetalRing(QLabel("E"), ring=3, padding=2)
        self.addCleanup(round_ring.deleteLater)
        round_ring.resize(80, 40)
        corner = region_alpha(image, 0, 0, .04, .08)
        self.assertGreater(corner, 60)                                   # radius 6: mostly filled
        self.assertGreater(corner, region_alpha(round_ring.render_at(1.0), 0, 0, .04, .08) + 50)
        fx.set_animations_enabled(False)
        ring.start()
        self.assertFalse(clock_has(ring))

    def test_reveal_rebases_a_foreign_timeline(self):
        view = MosaicView()
        view.resize(240, 150)
        self.addCleanup(view.deleteLater)
        view.set_loading()
        t = 1000.0                           # a gallery-style clock, far from fx.now()
        for _ in range(5):
            t += 1 / 15
            view._tick(t)
        view.set_image(QImage(10, 10, QImage.Format_ARGB32))
        self.assertTrue(view.revealing())
        t += 1 / 15
        view._tick(t)
        self.assertTrue(view.revealing())    # did not end at once
        mid = view.render_at(t + 1.0)
        self.assertGreater(coverage(mid, step=4), 0.3)
        while t < 1000.0 + REVEAL_S + 1.0:
            t += 1 / 15
            view._tick(t)
        self.assertFalse(view.revealing())
        self.assertFalse(clock_has(view))

    def test_reveal_passes_through_blocks(self):
        view = MosaicView()
        view.resize(320, 200)
        self.addCleanup(view.deleteLater)
        view.set_loading()
        base = fx.now()
        image = QImage(160, 100, QImage.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 80, 100, QColor("#000000"))
        painter.end()
        view.set_image(image)
        early = view.render_at(base + 0.5)
        done = view.render_at(base + REVEAL_S + 0.1)
        self.assertGreater(difference(early, done), 3.0)
        edge = QColor.fromRgba(done.pixel(161, 100))            # sharp once revealed
        self.assertGreater(edge.lightness(), 200)

    def test_image_none_message_and_switch_off(self):
        view = MosaicView()
        view.resize(200, 120)
        self.addCleanup(view.deleteLater)
        view.set_loading()
        view.set_image(None)
        self.assertFalse(view.loading())
        self.assertIsNone(view.image())
        self.assertFalse(clock_has(view))
        view.set_message("Rendering failed")
        self.assertGreater(coverage(view.render_at(1.0)), 0.001)
        fx.set_animations_enabled(False)
        view.set_loading()
        view.set_image(QImage(20, 20, QImage.Format_ARGB32))   # no reveal with animations off
        self.assertFalse(view.revealing())
        self.assertIsNotNone(view.image())

    def test_large_mosaic_budget(self):
        view = MosaicView()
        view.resize(640, 400)
        self.addCleanup(view.deleteLater)
        view.set_loading()
        self.assertLess(paint_ms(view, frames=5), 40.0)


if __name__ == "__main__":
    unittest.main()
