"""ui/python/fx/avatar.py -- W-C's gate.

FROZEN: the tests below are the minimum; add more in a new class at the
bottom, never change these.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fx_helpers import app, coverage, difference, paint_ms, region_alpha  # noqa: E402

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402

import ui.python.fx as fx  # noqa: E402
from ui.python.fx.avatar import AVATAR_STATES, PRESET_COLOURS, SHAPES, BotAvatar, shape_path  # noqa: E402


def _simulate(avatar, seconds, step=1 / 60):
    t = 1000.0
    out = []
    end = t + seconds
    while t < end:
        t += step
        avatar._tick(t)
        out.append(dict(avatar.pose()))
    return out


class ShapeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def test_shapes_fit_the_design_box(self):
        for shape in SHAPES:
            path = shape_path(shape)
            box = path.boundingRect()
            self.assertFalse(path.isEmpty(), shape)
            self.assertTrue(-1 <= box.left() and box.right() <= 101 and -1 <= box.top() and box.bottom() <= 101,
                            (shape, box))
            self.assertGreater(box.width(), 50, shape)
            self.assertTrue(path.contains(QPointF(50, 55)), shape)   # the face sits inside

    def test_circle_and_clover_geometry(self):
        box = shape_path("circle").boundingRect()
        self.assertAlmostEqual(box.width(), 84, delta=0.5)
        self.assertAlmostEqual(box.center().x(), 50, delta=0.5)
        clover = shape_path("clover")
        # Four lobes: the lobe tips are in, the diagonal notches between them are out.
        for p in ((50, 8), (92, 50), (50, 92), (8, 50)):
            self.assertTrue(clover.contains(QPointF(*p)), p)
        for p in ((85, 15), (15, 85)):
            self.assertFalse(clover.contains(QPointF(*p)), p)

    def test_unknown_shape(self):
        with self.assertRaises(ValueError):
            shape_path("teapot")


class BotAvatarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def _avatar(self, **kw):
        avatar = BotAvatar(**kw)
        self.addCleanup(avatar.deleteLater)
        return avatar

    def test_renders_body_in_its_colour(self):
        for shape in SHAPES:
            avatar = self._avatar(shape=shape, size=60)
            self.assertEqual((avatar.width(), avatar.height()), (60, 60))
            image = avatar.render_at(1.0)
            self.assertGreater(coverage(image), 0.15, shape)
            self.assertLess(region_alpha(image, 0, 0, 1, .06), 60, shape)   # overscan margin above
            want = QColor(PRESET_COLOURS[shape])
            hues = [QColor.fromRgba(image.pixel(x, y)) for y in range(15, 45) for x in range(15, 45)]
            hues = [c for c in hues if c.alpha() > 200 and c.hsvSaturation() > 60 and c.value() > 90]
            if want.hsvSaturation() > 60:
                self.assertTrue(hues, shape)
                mean = sum(c.hsvHue() for c in hues) / len(hues)
                self.assertLess(abs(mean - want.hsvHue()), 25, shape)

    def test_states_blend_and_settle(self):
        avatar = self._avatar()
        for state in AVATAR_STATES:
            avatar.set_state(state)
            _simulate(avatar, 1.6)
            self.assertEqual(avatar.state(), state)
            w = avatar.pose()["w"]
            self.assertAlmostEqual(sum(w), 1.0, places=3)
            self.assertAlmostEqual(w[AVATAR_STATES.index(state)], 1.0, places=2)
        with self.assertRaises(ValueError):
            avatar.set_state("dancing")

    def test_it_blinks(self):
        avatar = self._avatar(seed=0.2)
        poses = _simulate(avatar, 10.0)
        self.assertTrue(any(p["blink"] > 0.8 for p in poses))
        self.assertTrue(any(abs(p["yaw"]) > 0.05 for p in poses))    # idle wander

    def test_working_hops(self):
        avatar = self._avatar(state="working")
        poses = _simulate(avatar, 3.0)
        self.assertLess(min(p["y"] for p in poses), -8)

    def test_poke_hops(self):
        avatar = self._avatar()
        _simulate(avatar, 0.5)
        avatar.poke()
        poses = _simulate(avatar, 1.2)
        self.assertLess(min(p["y"] for p in poses), -10)

    def test_sleeping_eyes_differ_from_awake(self):
        awake, asleep = self._avatar(size=80), self._avatar(size=80, state="sleeping")
        _simulate(asleep, 2.0)
        self.assertGreater(difference(awake.render_at(5.0), asleep.render_at(5.0)), 0.5)

    def test_deterministic_with_seed(self):
        a, b = self._avatar(seed=0.5), self._avatar(seed=0.5)
        self.assertEqual(_simulate(a, 1.0)[-1], _simulate(b, 1.0)[-1])

    def test_paint_budget(self):
        avatar = self._avatar(size=48)
        self.assertLess(paint_ms(avatar), 12.0)



class AvatarPortTests(unittest.TestCase):
    """W-C's own checks on the port (engine fidelity, still frame, extras)."""

    @classmethod
    def setUpClass(cls):
        cls.app = app()

    def setUp(self):
        fx.set_animations_enabled(True)

    def _avatar(self, **kw):
        avatar = BotAvatar(**kw)
        self.addCleanup(avatar.deleteLater)
        return avatar

    def test_mulberry32_matches_the_source(self):
        from ui.python.fx.avatar import _mulberry32
        # node: rng(Math.floor(0.37 * 1e6) + 1), three draws
        r = _mulberry32(370001)
        self.assertEqual([r(), r(), r()], [0.6975546323228627, 0.9667365262284875, 0.9297918432857841])

    def test_every_source_shape_parses(self):
        for shape in SHAPES + ("triangle",):
            path = shape_path(shape)
            self.assertTrue(path.contains(QPointF(50, 60)), shape)
            box = path.boundingRect()
            self.assertTrue(0 <= box.left() and box.right() <= 100, (shape, box))
        # the squircle is 86 wide, rebuilt from the generator's formula
        self.assertAlmostEqual(shape_path("square").boundingRect().width(), 86, delta=0.5)

    def test_pose_fields(self):
        pose = self._avatar().pose()
        for key in ("yaw", "pitch", "roll", "x", "y", "sx", "sy", "eyeOpen", "blink",
                    "lookX", "lookY", "breath", "laugh", "w"):
            self.assertIn(key, pose)
        self.assertEqual(pose["w"], [1.0, 0.0, 0.0])

    def test_still_frame_is_the_rest_pose(self):
        a, b = self._avatar(size=80), self._avatar(size=80)
        a.start()
        _simulate(a, 3.0)
        a.stop()
        self.assertEqual(difference(a.render_at(1.0), b.render_at(1.0)), 0.0)
        with self.assertRaises(ValueError):
            a.set_shape("teapot")
        with self.assertRaises(ValueError):
            BotAvatar(state="dancing")

    def test_shape_switch_and_crisp_render(self):
        avatar = self._avatar(size=80)
        before = avatar.render_at(1.0)
        avatar.set_shape("droid")
        self.assertGreater(difference(before, avatar.render_at(1.0)), 1.0)
        avatar._shading = "crisp"
        self.assertGreater(coverage(avatar.render_at(1.0)), 0.15)

    def test_pointer_turns_the_head(self):
        avatar = self._avatar(size=90, interactive=True)
        avatar._pointer = QPointF(90, 40)       # to the right of the head
        poses = _simulate(avatar, 1.5)
        self.assertGreater(poses[-1]["lookX"], 1.0)


if __name__ == "__main__":
    unittest.main()
