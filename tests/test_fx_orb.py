"""ui/python/fx/orb.py -- W-B's gate.

FROZEN: the tests below are the minimum; add more in a new class at the
bottom, never change these. Counts below are derived from the source
presets/profiles (see docs/UI_FX.md) -- the port must match them.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, coverage, difference, paint_ms  # noqa: E402

from PySide6.QtGui import QColor  # noqa: E402

import ui.python.fx as fx  # noqa: E402
from ui.python.fx.orb import LABELS, SIZES, STATES, ThinkingOrb, frame, preset_speed  # noqa: E402


class OrbFrameTests(unittest.TestCase):
    def test_every_state_and_size_draws_inside_its_box(self):
        for state in STATES:
            for size in SIZES:
                dots, lines = frame(state, size, 3.7)
                self.assertTrue(dots, (state, size))
                for d in dots:
                    self.assertTrue(-2 <= d.x <= size + 2 and -2 <= d.y <= size + 2, (state, size, d))
                    self.assertGreater(d.r, 0)
                    self.assertGreaterEqual(d.a, 0.02)
                zs = [d.z for d in dots]
                self.assertEqual(zs, sorted(zs), (state, size))

    def test_deterministic(self):
        for state in STATES:
            a, b = frame(state, 64, 5.25), frame(state, 64, 5.25)
            self.assertEqual([(d.x, d.y, d.r) for d in a[0]], [(d.x, d.y, d.r) for d in b[0]])

    def test_preset_speeds(self):
        self.assertAlmostEqual(preset_speed("working", 64), 1.885, places=3)
        self.assertAlmostEqual(preset_speed("searching", 64), 2.015, places=3)
        self.assertAlmostEqual(preset_speed("connecting", 20), 6.63, places=3)
        self.assertAlmostEqual(preset_speed("shaping", 64), 2.405, places=3)

    def test_working_counts(self):
        # 12 orbits x (40 ghost dots + 3 particles); ghost alpha >= .2 so none is dropped.
        dots, lines = frame("working", 64, 1.0)
        self.assertEqual(len(dots), 12 * 40 + 12 * 3)
        self.assertEqual(lines, [])

    def test_globe_counts(self):
        # latRings 11 (rings 0..11), lonDensity 29, round(|cos lat| * 29), at least 1 per ring.
        expected = sum(max(1, int(math.floor(abs(math.cos(-math.pi / 2 + math.pi * i / 11)) * 29 + 0.5)))
                       for i in range(12))
        dots, _ = frame("searching", 64, 2.0)
        self.assertEqual(len(dots), expected)

    def test_web_has_lines_and_morph_has_24_dots(self):
        _dots, lines = frame("connecting", 64, 2.0)
        self.assertTrue(lines)
        dots, _ = frame("shaping", 64, 0.5)
        self.assertEqual(len(dots), 24)

    def test_frames_change_over_time(self):
        for state in STATES:
            a = [(round(d.x, 3), round(d.y, 3)) for d in frame(state, 64, 1.0)[0]]
            b = [(round(d.x, 3), round(d.y, 3)) for d in frame(state, 64, 1.9)[0]]
            self.assertNotEqual(a, b, state)


class ThinkingOrbWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def test_renders_both_themes(self):
        for theme in ("dark", "light"):
            orb = ThinkingOrb(state="breathing", size=32)
            self.addCleanup(orb.deleteLater)
            self.assertEqual((orb.width(), orb.height()), (32, 32))
            orb.set_theme(theme)
            image = orb.render_at(10.0)
            self.assertGreater(coverage(image), 0.02)
            # Ink contrast: dark theme draws light dots, light theme dark dots.
            lum = [QColor.fromRgba(image.pixel(x, y)).lightness()
                   for y in range(32) for x in range(32)
                   if QColor.fromRgba(image.pixel(x, y)).alpha() > 128]
            mean = sum(lum) / max(1, len(lum))
            self.assertTrue(mean > 110 if theme == "dark" else mean < 145, (theme, mean))

    def test_animates_and_switches_state(self):
        orb = ThinkingOrb(state="working", size=64)
        self.addCleanup(orb.deleteLater)
        self.assertGreater(difference(orb.render_at(4.0), orb.render_at(4.3)), 0.3)
        orb.set_state("shaping")
        self.assertEqual(orb.state(), "shaping")
        self.assertEqual(orb.label(), LABELS["shaping"])
        self.assertEqual(orb.accessibleName(), LABELS["shaping"])
        with self.assertRaises(ValueError):
            orb.set_state("dancing")

    def test_tint(self):
        orb = ThinkingOrb(state="breathing", size=64, color="#ff0000")
        self.addCleanup(orb.deleteLater)
        image = orb.render_at(3.0)
        reds = [QColor.fromRgba(image.pixel(x, y)) for y in range(64) for x in range(64)]
        reds = [c for c in reds if c.alpha() > 128]
        self.assertTrue(reds)
        self.assertGreater(sum(c.red() for c in reds), sum(c.blue() for c in reds) * 1.5)

    def test_paint_budget(self):
        for state in STATES:
            orb = ThinkingOrb(state=state, size=64)
            self.addCleanup(orb.deleteLater)
            self.assertLess(paint_ms(orb, frames=5), 12.0, state)


if __name__ == "__main__":
    unittest.main()
