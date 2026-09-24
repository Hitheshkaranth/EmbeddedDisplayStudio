"""ui/python/fx/beam.py and glow.py -- the border beam and working glow."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, clock_has, coverage, difference, paint_ms, region_alpha  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QFrame  # noqa: E402

import ui.python.fx as fx  # noqa: E402
from ui.python.fx.beam import FADE_IN_S, FADE_OUT_S, SIZES, VARIANTS, BorderBeam  # noqa: E402
from ui.python.fx.glow import WorkingGlow  # noqa: E402


def _card(w=320, h=180):
    card = QFrame()
    card.resize(w, h)
    return card


def _run(widget, seconds, base=None, step=1 / 30):
    """Drive widget._tick from base over `seconds`; returns the last t."""
    t = fx.now() if base is None else base
    end = t + seconds
    while t < end:
        t += step
        widget._tick(t)
    return t


class BorderBeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def _beam(self, size="md", variant="colorful", w=320, h=180):
        card = _card(w, h)
        self.addCleanup(card.deleteLater)
        beam = BorderBeam(card, size=size, variant=variant)
        return card, beam

    def test_overlay_follows_target_and_passes_clicks(self):
        card, beam = self._beam()
        self.assertIs(beam.parent(), card)
        self.assertEqual(beam.geometry(), card.rect())
        card.resize(400, 220)
        self.app.processEvents()
        self.assertEqual(beam.geometry(), card.rect())
        self.assertTrue(beam.testAttribute(Qt.WA_TransparentForMouseEvents))

    def test_inactive_draws_nothing(self):
        _card_, beam = self._beam()
        beam.set_active(False)
        self.assertEqual(beam.fade(), 0.0)
        self.assertLess(coverage(beam.render_at(fx.now()), step=3), 0.001)

    def test_fade_in_then_border_glow(self):
        _card_, beam = self._beam()
        beam.set_active(True)
        self.assertTrue(beam.is_active())
        self.assertTrue(clock_has(beam))
        t = _run(beam, FADE_IN_S + 0.2)
        self.assertAlmostEqual(beam.fade(), 1.0, places=3)
        image = beam.render_at(t)
        self.assertGreater(coverage(image, step=2), 0.01)
        # A border effect: the middle of a card stays (nearly) clear.
        self.assertLess(region_alpha(image, .35, .35, .65, .65), 12)

    def test_it_moves(self):
        _card_, beam = self._beam()
        beam.set_active(True)
        t = _run(beam, FADE_IN_S + 0.1)
        self.assertGreater(difference(beam.render_at(t), beam.render_at(t + 0.5)), 0.2)

    def test_fade_out_stops_the_clock(self):
        _card_, beam = self._beam()
        beam.set_active(True)
        t = _run(beam, FADE_IN_S + 0.1)
        beam.set_active(False)
        self.assertFalse(beam.is_active())
        _run(beam, FADE_OUT_S + 0.2, base=t)
        self.assertEqual(beam.fade(), 0.0)
        self.assertFalse(clock_has(beam))

    def test_toggle_during_fade_is_applied_after(self):
        _card_, beam = self._beam()
        beam.set_active(True)
        t = _run(beam, 0.2)
        beam.set_active(False)
        beam.set_active(True)
        t = _run(beam, 1.5, base=t)
        self.assertTrue(beam.is_active())
        self.assertAlmostEqual(beam.fade(), 1.0, places=3)

    def test_line_glows_at_the_bottom(self):
        _card_, beam = self._beam(size="line")
        beam.set_active(True)
        t = _run(beam, 1.4)          # past the line's edge ramp-in
        image = beam.render_at(t)
        self.assertGreater(region_alpha(image, 0, .8, 1, 1), region_alpha(image, 0, 0, 1, .4) + 5)

    def test_every_size_variant_theme_renders(self):
        for size in SIZES:
            for variant in VARIANTS:
                for theme in ("dark", "light"):
                    _card_, beam = self._beam(size=size, variant=variant)
                    beam.set_theme(theme)
                    beam.set_active(True)
                    t = _run(beam, 1.4)
                    self.assertGreater(coverage(beam.render_at(t), step=3), 0.002, (size, variant, theme))

    def test_paint_budget(self):
        _card_, beam = self._beam(w=480, h=240)
        beam.set_active(True)
        _run(beam, FADE_IN_S + 0.1)
        self.assertLess(paint_ms(beam), 25.0)


class WorkingGlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def _glow(self):
        glow = WorkingGlow(height=8)
        glow.resize(360, 8)
        self.addCleanup(glow.deleteLater)
        return glow

    def test_sweeps_while_running(self):
        glow = self._glow()
        self.assertEqual(glow.height(), 8)
        glow.start()
        t = _run(glow, 0.6)
        self.assertAlmostEqual(glow.level(), 0.55, delta=0.1)
        a, b = glow.render_at(t), glow.render_at(t + 0.4)
        self.assertGreater(coverage(a, step=2), 0.03)
        self.assertGreater(difference(a, b), 0.3)

    def test_stop_fades_and_releases_the_clock(self):
        glow = self._glow()
        glow.start()
        t = _run(glow, 0.6)
        glow.stop()
        _run(glow, 0.6, base=t)
        self.assertEqual(glow.level(), 0.0)
        self.assertFalse(clock_has(glow))
        self.assertLess(coverage(glow.render_at(t + 1)), 0.001)

    def test_light_theme(self):
        glow = self._glow()
        glow.set_theme("light")
        glow.start()
        t = _run(glow, 0.6)
        self.assertGreater(coverage(glow.render_at(t), step=2), 0.03)


class BeamGlowWorkerTests(unittest.TestCase):
    """Further checks: still frames, corners, strength, the time base."""

    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)
        self.addCleanup(fx.set_animations_enabled, True)

    def _beam(self, **kw):
        card = _card()
        self.addCleanup(card.deleteLater)
        return BorderBeam(card, **kw)

    def test_nothing_outside_the_rounded_corners(self):
        from PySide6.QtGui import QColor, QImage
        for size in SIZES:
            beam = self._beam(size=size)
            beam.set_active(True)
            t = _run(beam, 1.4)
            for dt in (0.0, 0.5, 1.0, 1.5):
                image = beam.render_at(t + dt).convertToFormat(QImage.Format_ARGB32)
                w, h = image.width(), image.height()
                for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (1, 1), (w - 2, h - 2)):
                    self.assertEqual(QColor.fromRgba(image.pixel(x, y)).alpha(), 0, (size, x, y))

    def test_animations_off_still_frame_and_no_clock(self):
        fx.set_animations_enabled(False)
        beam = self._beam()
        beam.set_active(True)
        self.assertFalse(clock_has(beam))
        self.assertEqual(beam.fade(), 1.0)
        self.assertGreater(coverage(beam.render_at(beam.still_time()), step=2), 0.01)
        beam.set_active(False)
        self.assertEqual(beam.fade(), 0.0)
        self.assertLess(coverage(beam.render_at(beam.still_time()), step=3), 0.001)

    def test_strength_zero_draws_nothing(self):
        beam = self._beam(strength=0.0)
        beam.set_active(True)
        t = _run(beam, 1.0)
        self.assertLess(coverage(beam.render_at(t), step=3), 0.001)

    def test_foreign_time_base_still_fades_in(self):
        # The gallery drives from t=1000 while set_active stamps fx.now().
        beam = self._beam()
        beam.set_active(True)
        _run(beam, FADE_IN_S + 0.2, base=1000.0)
        self.assertAlmostEqual(beam.fade(), 1.0, places=3)

    def test_variant_and_radius_setters(self):
        beam = self._beam()
        beam.set_active(True)
        t = _run(beam, 1.0)
        a = beam.render_at(t)
        beam.set_variant("sunset")
        beam.set_radius(4)
        self.assertGreater(difference(a, beam.render_at(t)), 0.05)

    def test_line_every_moment_stays_at_the_bottom(self):
        beam = self._beam(size="line")
        beam.set_active(True)
        t = _run(beam, 0.7)
        for dt in (0.0, 0.8, 1.6, 2.4):
            image = beam.render_at(t + dt)
            self.assertLess(region_alpha(image, 0, 0, 1, .3), 3)

    def test_glow_animations_off(self):
        fx.set_animations_enabled(False)
        glow = WorkingGlow(height=8)
        glow.resize(360, 8)
        self.addCleanup(glow.deleteLater)
        glow.start()
        self.assertFalse(clock_has(glow))
        self.assertAlmostEqual(glow.level(), 0.55)
        self.assertGreater(coverage(glow.render_at(0.0), step=2), 0.03)
        glow.stop()
        self.assertEqual(glow.level(), 0.0)
        self.assertLess(coverage(glow.render_at(0.0)), 0.001)

    def test_glow_paint_budget(self):
        glow = WorkingGlow(height=10)
        glow.resize(600, 10)
        self.addCleanup(glow.deleteLater)
        glow.start()
        _run(glow, 0.5)
        self.assertLess(paint_ms(glow), 10.0)

if __name__ == "__main__":
    unittest.main()
