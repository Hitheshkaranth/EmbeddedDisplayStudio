"""designer/layout/critic.py -- composition measured.

The bar that matters: the hand-built dashboard must score well above the
real AI draft, and every defect visible in that draft must be named.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.layout import Critique, critique, grid_for  # noqa: E402
from designer.layout.critic import AXES, render_for_critique  # noqa: E402
from designer.model import DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "layout"
BIN = REPO_ROOT / "native" / "hmi-ui" / "out" / "hmi-ui"


def _load(name):
    project = DesignerProject.load(str(FIXTURES / name))
    return project, project.pages[0]


class CritiqueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.registry = default_registry()

    def test_shape_of_a_critique(self):
        project, page = _load("hand-built.edsui")
        verdict = critique(project, page, self.registry)
        self.assertIsInstance(verdict, Critique)
        self.assertGreaterEqual(verdict.score, 0)
        self.assertLessEqual(verdict.score, 100)
        for axis in AXES:
            self.assertIn(axis, verdict.scores)
        for axis in ("overlap", "margins", "alignment", "grid", "hierarchy", "balance", "proportion"):
            self.assertIsNotNone(verdict.scores[axis], axis)
            self.assertGreaterEqual(verdict.scores[axis], 0)
            self.assertLessEqual(verdict.scores[axis], 100)
        # No render was given: the pixel axes are not guessed.
        self.assertIsNone(verdict.scores["clipping"])
        self.assertIsNone(verdict.scores["contrast"])
        self.assertIsInstance(verdict.summary(), str)

    def test_the_hand_built_screen_beats_the_ai_draft(self):
        good_project, good_page = _load("hand-built.edsui")
        bad_project, bad_page = _load("ai-baseline.edsui")
        good = critique(good_project, good_page, self.registry)
        bad = critique(bad_project, bad_page, self.registry)
        self.assertGreater(good.score, bad.score + 20,
                           f"hand-built {good.score:.0f} vs AI draft {bad.score:.0f}")
        self.assertGreaterEqual(good.score, 70)
        self.assertLessEqual(bad.score, 60)

    def test_the_drafts_real_defects_are_named(self):
        project, page = _load("ai-baseline.edsui")
        verdict = critique(project, page, self.registry)
        kinds = {issue.kind for issue in verdict.issues}
        self.assertIn("overlap", kinds)
        self.assertIn("proportion", kinds)          # the 864x100 fuel gauge
        overlap = next(i for i in verdict.issues if i.kind == "overlap")
        self.assertIn(overlap.widget_id, ("fuelQty", "startStopBtn"))
        self.assertEqual(overlap.severity, "error")
        self.assertTrue(any(char.isdigit() for char in overlap.detail), overlap.detail)
        self.assertEqual(verdict.errors(), tuple(i for i in verdict.issues if i.severity == "error"))

    def test_axes_respond_to_the_thing_they_measure(self):
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=[
            DesignerWidget(type="ShValueTile", id="a", geometry={"x": 40, "y": 40, "width": 300, "height": 160}),
            DesignerWidget(type="ShValueTile", id="b", geometry={"x": 400, "y": 40, "width": 300, "height": 160}),
        ])])
        page = project.pages[0]
        clean = critique(project, page, self.registry)
        page.widgets[1].geometry["x"] = 60          # now it overlaps a
        dirty = critique(project, page, self.registry)
        self.assertLess(dirty.scores["overlap"], clean.scores["overlap"])
        self.assertLess(dirty.score, clean.score)
        page.widgets[1].geometry["x"] = 400
        page.widgets[1].geometry["y"] = -30         # now it leaves the screen
        off = critique(project, page, self.registry)
        self.assertLess(off.scores["margins"], clean.scores["margins"])

    def test_empty_page(self):
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=[])])
        verdict = critique(project, project.pages[0], self.registry)
        self.assertEqual(verdict.score, 0)
        self.assertTrue(verdict.issues)

    @unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
    def test_pixel_axes_with_a_render(self):
        from designer.preview import NativeRenderer
        project, page = _load("hand-built.edsui")
        renderer = NativeRenderer()
        image = render_for_critique(project, page, renderer)
        self.assertIsNotNone(image)
        verdict = critique(project, page, self.registry, image=image)
        self.assertIsNotNone(verdict.scores["clipping"])
        self.assertIsNotNone(verdict.scores["contrast"])
        self.assertGreaterEqual(verdict.score, 70)
        renderer.shutdown()



