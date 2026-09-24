"""ui/python/fx/orb.py -- the orb effect.

Counts below are derived from the source
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



# Port checks against upstream spec/orbs-golden.json (thinking-orbs
# 0.3.1): (state, size, t, dotCount, lineCount, first dot, last dot, first
# line), dots as x, y, z, r, white, a; lines as x1, y1, x2, y2, white, a, w.
_GOLDEN = [
    ('working', 64, 0.6, 516, 0, [32.34438, 30.683937, -24.13443, 0.356187, 0.72, 0.200238], [31.65562, 33.316063, 24.13443, 0.356187, 0.72, 0.499762], None),
    ('working', 64, 1.7, 516, 0, [32.914704, 31.715425, -24.153751, 0.356187, 0.72, 0.200118], [31.085296, 32.284575, 24.153751, 0.356187, 0.72, 0.499882], None),
    ('working', 20, 0.6, 39, 0, [11.235898, 9.940794, -7.451958, 0.425401, 0.72, 0.202026], [9.230714, 10.206142, 7.51188, 1.321364, 0.080613, 1], None),
    ('working', 20, 1.7, 39, 0, [10.285845, 9.91107, -7.548047, 0.425401, 0.72, 0.200118], [9.714155, 10.08893, 7.548047, 0.425401, 0.72, 0.499882], None),
    ('searching', 64, 0.6, 204, 0, [33.490622, 32.435651, -0.998247, 0.3, 0.619527, 0.45], [30.509378, 31.564349, 0.998247, 1.047571, 0.080473, 0.452023], None),
    ('searching', 64, 1.7, 204, 0, [31.900072, 31.862813, -0.999979, 0.3, 0.619994, 0.45], [32.099928, 32.137187, 0.999979, 1.226772, 0.080006, 0.700132], None),
    ('searching', 20, 0.6, 54, 0, [11.574668, 10.979949, -0.974085, 0.3, 0.613003, 0.45], [8.425332, 9.020051, 0.974085, 0.785661, 0.086997, 0.451532], None),
    ('searching', 20, 1.7, 54, 0, [11.391322, 10.794572, -0.980725, 0.3, 0.614796, 0.45], [8.608678, 9.205428, 0.980725, 0.976657, 0.085204, 0.979487], None),
    ('solving', 64, 0.6, 138, 0, [32.999536, 35.206761, -0.991773, 0.3, 0.617779, 1], [34.395262, 28.752372, 0.988104, 0.951566, 0.083212, 1], None),
    ('solving', 64, 1.7, 138, 0, [36.224701, 34.103952, -0.983692, 0.3, 0.615597, 1], [34.544387, 30.006191, 0.992383, 0.953077, 0.082057, 1], None),
    ('solving', 20, 0.6, 30, 0, [8.121109, 13.194107, -0.892058, 0.3, 0.590856, 1], [8.422388, 13.144049, 0.903313, 0.829897, 0.106106, 1], None),
    ('solving', 20, 1.7, 30, 0, [10.144267, 10.604283, -0.997126, 0.3, 0.619224, 1], [10.864201, 7.2722, 0.93714, 0.840657, 0.096972, 1], None),
    ('listening', 64, 0.6, 134, 0, [29.764214, 35.472327, -23.59208, 0.3, 0.616191, 1], [34.080924, 28.768185, 21.957968, 0.837966, 0.160169, 1], None),
    ('listening', 64, 1.7, 134, 0, [29.452889, 26.820117, -24.96421, 0.311263, 0.5955, 1], [31.814541, 28.243704, 25.975582, 1.08362, 0.064285, 1], None),
    ('listening', 20, 0.6, 42, 0, [9.17525, 9.487216, -7.986373, 0.3, 0.597281, 1], [10.767284, 10.477054, 7.429901, 0.684609, 0.141971, 1], None),
    ('listening', 20, 1.7, 42, 0, [11.601351, 9.551738, -7.619978, 0.3, 0.612337, 1], [8.386569, 10.451643, 7.677457, 0.742565, 0.115848, 1], None),
    ('connecting', 64, 0.6, 48, 81, [23.99695, 34.67833, -0.944099, 0.662966, 0.537422, 1], [31.723599, 32.180593, 0.999917, 1.490098, 0.100019, 1], [40.743047, 12.360858, 25.929776, 13.006921, 0.42, 0.137696, 0.6]),
    ('connecting', 64, 1.7, 48, 86, [33.977576, 25.363526, -0.962719, 0.673322, 0.541612, 1], [34.57579, 32.330693, 0.994841, 1.120417, 0.101161, 1], [41.267017, 11.923016, 26.092415, 12.415575, 0.42, 0.120141, 0.6]),
    ('connecting', 20, 0.6, 9, 0, [12.345722, 12.323515, -0.910862, 0.652664, 0.05, 0.522284], [5.573026, 8.166562, 0.800785, 0.816565, 0.144823, 1], None),
    ('connecting', 20, 1.7, 9, 0, [9.463514, 5.457987, -0.820464, 0.584018, 0.509604, 1], [6.063945, 7.72457, 0.822818, 0.697856, 0.139866, 1], None),
    ('weaving', 64, 0.6, 153, 0, [34.742259, 29.322907, -24.016153, 0.31661, 0.78, 0.101374], [28.349991, 32.646624, 24.035842, 0.31661, 0.78, 0.318715], None),
    ('weaving', 64, 1.7, 153, 0, [32.561152, 34.70856, -24.162186, 0.31661, 0.78, 0.100714], [30.386025, 37.921821, 23.532733, 0.31661, 0.78, 0.316439], None),
    ('weaving', 20, 0.6, 35, 0, [11.45075, 9.567985, -7.44773, 0.3, 0.78, 0.102204], [9.832985, 10.473972, 7.583367, 0.3, 0.78, 0.319759], None),
    ('weaving', 20, 1.7, 35, 0, [8.227592, 9.589242, -7.379014, 0.3, 0.78, 0.103198], [9.638712, 8.62566, 7.28806, 0.793642, 0.109235, 0.988713], None),
    ('composing', 64, 0.6, 566, 0, [37.322389, 30.655967, -24.348868, 0.31661, 0.78, 0.102693], [38.863508, 29.053978, 23.816272, 0.31661, 0.78, 0.31496], None),
    ('composing', 64, 1.7, 566, 0, [28.951635, 36.366175, -24.385356, 0.3, 0.694935, 0.406907], [38.863508, 29.053978, 23.816272, 0.31661, 0.78, 0.31496], None),
    ('composing', 20, 0.6, 208, 0, [7.795005, 12.112063, -7.177547, 0.3, 0.682444, 0.42394], [10, 6.759833, 7.095162, 0.431603, 0.27988, 0.972891], None),
    ('composing', 20, 1.7, 208, 0, [10, 12.155109, -7.496366, 0.3, 0.691436, 0.411678], [12.198967, 7.933103, 7.19253, 0.433285, 0.277134, 0.976636], None),
    ('breathing', 64, 0.6, 484, 0, [41.791591, 53.440594, -8.838984, 0.467922, 0.557908, 0.593762], [55.395251, 28.636271, 8.863436, 0.638987, 0.401877, 0.806532], None),
    ('breathing', 64, 1.7, 484, 0, [12.189342, 44.731537, -8.830866, 0.468, 0.557836, 0.59386], [38.655342, 54.666012, 8.85859, 0.63894, 0.401919, 0.806473], None),
    ('breathing', 20, 0.6, 120, 0, [12.339578, 17.20048, -1.987396, 0.4153, 0.536055, 0.623562], [3.883903, 5.556396, 1.984477, 0.519, 0.424028, 0.776326], None),
    ('breathing', 20, 1.7, 120, 0, [3.87639, 14.449063, -1.986914, 0.415313, 0.536041, 0.62358], [12.35304, 17.241913, 1.998832, 0.519375, 0.423623, 0.776878], None),
    ('shaping', 64, 0.6, 24, 0, [32, 9.301059, 0, 1.039198, 0.1, 1], [26.126072, 10.078267, 0, 1.039198, 0.1, 1], None),
    ('shaping', 64, 1.7, 24, 0, [32, 9.632946, 0, 1.039198, 0.1, 1], [26.871972, 11.533978, 0, 1.039198, 0.1, 1], None),
    ('shaping', 20, 0.6, 18, 0, [10, 2.906581, 0, 0.831194, 0.1, 1], [7.574087, 3.334876, 0, 0.831194, 0.1, 1], None),
    ('shaping', 20, 1.7, 18, 0, [10, 3.010296, 0, 0.831194, 0.1, 1], [7.895991, 3.876692, 0, 0.831194, 0.1, 1], None),
]


class OrbPortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def test_matches_upstream_golden_vectors(self):
        for state, size, t, n_dots, n_lines, first, last, line in _GOLDEN:
            dots, lines = frame(state, size, t)
            key = (state, size, t)
            self.assertEqual(len(dots), n_dots, key)
            self.assertEqual(len(lines), n_lines, key)
            for got, want in ((dots[0], first), (dots[-1], last)):
                for a, b in zip((got.x, got.y, got.z, got.r, got.white, got.a), want):
                    self.assertAlmostEqual(a, b, delta=1e-4, msg=key)
            if line:
                l0 = lines[0]
                for a, b in zip((l0.x1, l0.y1, l0.x2, l0.y2, l0.white, l0.a, l0.w), line):
                    self.assertAlmostEqual(a, b, delta=1e-4, msg=key)

    def test_size_32_uses_its_interpolated_preset(self):
        self.assertAlmostEqual(preset_speed("working", 32), 2.9072, places=4)
        # orbitN round(12 * .4251) = 5, ghostN round(40 * .4251) = 17, 3 particles
        self.assertEqual(len(frame("working", 32, 1.0)[0]), 5 * 17 + 5 * 3)
        # other sizes take the nearest tuned preset
        self.assertEqual(preset_speed("shaping", 48), preset_speed("shaping", 64))
        self.assertEqual(preset_speed("shaping", 24), preset_speed("shaping", 20))

    def test_still_frame_is_orb_time_0_6(self):
        orb = ThinkingOrb(state="connecting", size=64, speed=2.0)
        self.addCleanup(orb.deleteLater)
        self.assertAlmostEqual(orb.still_time() * preset_speed("connecting", 64) * 2.0, 0.6)
        ref = ThinkingOrb(state="connecting", size=64)
        self.addCleanup(ref.deleteLater)
        self.assertEqual(difference(orb.render_at(orb.still_time()), ref.render_at(ref.still_time())), 0)

    def test_ink_ramp(self):
        orb = ThinkingOrb(state="shaping", size=64)
        self.addCleanup(orb.deleteLater)
        c = orb._color(0.1, 1.0, True)
        self.assertEqual((c.red(), c.green(), c.blue()), (230, 230, 230))
        c = orb._color(0.1, 0.5, False)
        self.assertEqual((c.red(), c.alpha()), (26, 128))
        orb.set_color(QColor(200, 100, 0))
        c = orb._color(0.5, 1.0, True)
        self.assertEqual((c.red(), c.green(), c.blue()), (100, 50, 0))
        c = orb._color(0.5, 1.0, False)
        self.assertEqual((c.red(), c.green(), c.blue()), (228, 178, 128))
        orb.set_color(None)
        self.assertEqual(orb._color(0.5, 1.0, True).red(), 128)

    def test_default_widget_and_unknown_state(self):
        orb = ThinkingOrb()
        self.addCleanup(orb.deleteLater)
        self.assertEqual((orb.state(), orb.width(), orb.height()), ("working", 20, 20))
        self.assertEqual(orb.accessibleName(), LABELS["working"])
        with self.assertRaises(ValueError):
            frame("dancing", 64, 1.0)

if __name__ == "__main__":
    unittest.main()
