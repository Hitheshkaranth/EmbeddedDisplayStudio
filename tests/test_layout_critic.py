"""designer/layout/critic.py -- composition measured (W2 gate).

FROZEN: the minimum W2 must pass; add more below, never change these.

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



# ===========================================================================
# STAND-IN, removed at integration.
#
# W1 owns designer/layout/grid.py and constraints.py; in this worktree their
# bodies still raise NotImplementedError, and the critic cannot measure a
# screen without a grid to measure against or a rule to measure a widget's
# aspect by. These two functions are the docstrings of `grid_for` and
# `rule_for` read literally, patched into the critic's module namespace so
# the gate can run. Delete this whole block once W1's branch lands: nothing
# in designer/layout/critic.py depends on it.
# ===========================================================================
from designer.layout import critic as _critic                       # noqa: E402
from designer.layout.constraints import (                           # noqa: E402
    SQUARE_TYPES, TOUCH_MIN_HEIGHT, WidgetRule)
from designer.layout.grid import COLUMNS, Grid                      # noqa: E402

_FREE_ASPECT = ("Text", "Image", "Rectangle")


class _StandInGrid(Grid):
    """Grid with the bodies its docstrings describe (STAND-IN)."""

    @property
    def content_width(self):
        return self.width - 2 * self.margin

    @property
    def content_height(self):
        return self.height - 2 * self.margin

    def _col_pitch(self):
        return (self.content_width - (self.columns - 1) * self.gutter) / float(self.columns)

    def _row_pitch(self):
        return (self.content_height - (self.rows - 1) * self.gutter) / float(self.rows)

    def col_x(self, col):
        return int(round(self.margin + col * (self._col_pitch() + self.gutter)))

    def col_span(self, span):
        return int(round(span * self._col_pitch() + (span - 1) * self.gutter))

    def row_y(self, row):
        return int(round(self.margin + row * (self._row_pitch() + self.gutter)))

    def row_span(self, span):
        return int(round(span * self._row_pitch() + (span - 1) * self.gutter))


def _standin_grid_for(width, height):
    margin = min(40, max(12, int(round(min(width, height) * 0.035))))
    gutter = min(24, max(8, int(round(margin * 0.6))))
    rows = min(24, max(6, int((height - 2 * margin) // (gutter * 2))))
    return _StandInGrid(int(width), int(height), margin, gutter, COLUMNS, rows)


def _standin_rule_for(registry, widget_type):
    definition = registry.get(widget_type) if registry is not None else None
    if definition is None:
        return WidgetRule(widget_type, 24, 24, None, 0.15, False, True)
    min_w = max(24, int(round(definition.default_width * 0.6)))
    min_h = max(24, int(round(definition.default_height * 0.6)))
    if definition.action_signals:
        min_h = max(min_h, TOUCH_MIN_HEIGHT)
    if widget_type in SQUARE_TYPES:
        return WidgetRule(widget_type, min_w, min_h, 1.0, 0.0, True, True)
    free = definition.container or widget_type in _FREE_ASPECT
    aspect = None if free else definition.default_width / float(definition.default_height)
    return WidgetRule(widget_type, min_w, min_h, aspect, 0.15, False, True)


try:
    _critic.grid_for(1024, 768)
except NotImplementedError:
    _critic.grid_for = _standin_grid_for
try:
    _critic.rule_for(default_registry(), "ShButton")
except NotImplementedError:
    _critic.rule_for = _standin_rule_for


# ===========================================================================
# W2's own tests -- what the critic promises beyond the gate's minimum.
# ===========================================================================


def _tile(widget_id, x, y, w=300, h=160, kind="ShValueTile"):
    return DesignerWidget(type=kind, id=widget_id,
                          geometry={"x": x, "y": y, "width": w, "height": h})


def _project(*widgets, width=1024, height=768):
    project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=list(widgets))])
    project.screen.width, project.screen.height = width, height
    return project, project.pages[0]


class CriticBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.registry = default_registry()

    def test_the_same_screen_always_scores_the_same(self):
        first_project, first_page = _load("ai-baseline.edsui")
        second_project, second_page = _load("ai-baseline.edsui")
        first = critique(first_project, first_page, self.registry)
        second = critique(second_project, second_page, self.registry)
        self.assertEqual(first.score, second.score)
        self.assertEqual(first.scores, second.scores)
        self.assertEqual(first.issues, second.issues)

    def test_issues_come_worst_first_and_every_detail_is_quantified(self):
        project, page = _load("ai-baseline.edsui")
        verdict = critique(project, page, self.registry)
        rank = {"error": 0, "warning": 1, "nit": 2}
        order = [rank[issue.severity] for issue in verdict.issues]
        self.assertEqual(order, sorted(order))
        self.assertTrue(verdict.errors())
        for issue in verdict.issues:
            self.assertIn(issue.kind, AXES)
            self.assertTrue(issue.detail.strip())
            self.assertTrue(any(char.isdigit() for char in issue.detail), issue.detail)

    def test_the_score_is_the_weighted_mean_of_the_scored_axes(self):
        from designer.layout.critic import WEIGHTS
        project, page = _load("hand-built.edsui")
        verdict = critique(project, page, self.registry)
        scored = {axis: value for axis, value in verdict.scores.items() if value is not None}
        expected = (sum(WEIGHTS[axis] * value for axis, value in scored.items())
                    / sum(WEIGHTS[axis] for axis in scored))
        self.assertAlmostEqual(verdict.score, expected, places=1)
        self.assertNotIn("clipping", scored)   # its weight left the denominator

    def test_summary_is_one_line_carrying_the_score_and_the_worst_issue(self):
        project, page = _load("ai-baseline.edsui")
        verdict = critique(project, page, self.registry)
        line = verdict.summary()
        self.assertNotIn("\n", line)
        self.assertIn("score", line)
        self.assertIn(verdict.issues[0].detail, line)

    def test_shared_edges_score_full_alignment(self):
        project, page = _project(_tile("a", 100, 100), _tile("b", 500, 100),
                                 _tile("c", 100, 400), _tile("d", 500, 400))
        shared = critique(project, page, self.registry)
        self.assertEqual(shared.scores["alignment"], 100.0)
        for index, widget in enumerate(page.widgets):
            widget.geometry["x"] += index * 17      # every edge now its own
            widget.geometry["y"] += index * 13
        scattered = critique(project, page, self.registry)
        self.assertLess(scattered.scores["alignment"], 60)

    def test_geometry_on_the_grid_scores_the_grid_axis(self):
        grid = _critic.grid_for(1024, 768)
        x, y = grid.col_x(1), grid.row_y(2)
        w, h = grid.col_span(4), grid.row_span(3)
        project, page = _project(_tile("a", x, y, w, h), _tile("b", grid.col_x(7), y, w, h))
        self.assertEqual(critique(project, page, self.registry).scores["grid"], 100.0)
        page.widgets[0].geometry["x"] = x + 9
        self.assertLess(critique(project, page, self.registry).scores["grid"], 100.0)

    def test_a_proportion_issue_names_the_size_the_type_wants(self):
        project, page = _load("ai-baseline.edsui")
        verdict = critique(project, page, self.registry)
        issue = next(i for i in verdict.issues
                     if i.kind == "proportion" and i.widget_id == "fuelQty")
        self.assertEqual(issue.severity, "error")
        self.assertIn("864x100", issue.detail)
        self.assertIn("190x130", issue.detail)          # ShFuelQuantity's design size
        self.assertIn("ShFuelQuantity", issue.detail)

    def test_an_overlap_issue_names_both_widgets_and_the_area(self):
        project, page = _load("ai-baseline.edsui")
        issue = next(i for i in critique(project, page, self.registry).issues
                     if i.kind == "overlap")
        self.assertIn("fuelQty", issue.detail)
        self.assertIn("startStopBtn", issue.detail)
        self.assertIn("5600", issue.detail)

    def test_one_or_two_widgets_are_exempt_from_hierarchy(self):
        project, page = _project(_tile("a", 100, 100))
        self.assertEqual(critique(project, page, self.registry).scores["hierarchy"], 100.0)
        page.widgets.append(_tile("b", 500, 100, 80, 40))
        self.assertEqual(critique(project, page, self.registry).scores["hierarchy"], 100.0)

    def test_ink_piled_in_one_corner_is_less_balanced_than_ink_spread(self):
        project, page = _project(_tile("a", 60, 60), _tile("b", 380, 60),
                                 _tile("c", 60, 300), _tile("d", 380, 300))
        piled = critique(project, page, self.registry).scores["balance"]
        page.widgets[1].geometry["x"] = 640
        page.widgets[2].geometry["y"] = 540
        page.widgets[3].geometry.update({"x": 640, "y": 540})
        spread = critique(project, page, self.registry).scores["balance"]
        self.assertGreater(spread, piled + 10)

    def test_an_explicit_grid_is_the_one_measured_against(self):
        project, page = _project(_tile("a", 60, 60, 200, 100))
        normal = _critic.grid_for(1024, 768)
        wide = type(normal)(1024, 768, 200, normal.gutter, normal.columns, normal.rows)
        self.assertLess(critique(project, page, self.registry, grid=wide).scores["margins"],
                        critique(project, page, self.registry, grid=normal).scores["margins"])

    def test_a_render_of_the_wrong_size_is_scaled_not_refused(self):
        from PySide6.QtGui import QImage
        project, page = _load("hand-built.edsui")
        image = QImage(512, 384, QImage.Format_RGB32)
        image.fill(0xFF101418)                      # the page background, nothing drawn
        verdict = critique(project, page, self.registry, image=image)
        self.assertEqual(verdict.scores["clipping"], 100.0)
        self.assertIsNone(verdict.scores["contrast"])   # no ink to measure

    def test_render_for_critique_never_raises(self):
        project, page = _load("hand-built.edsui")

        class _NoBinary:
            available = False

            def render_page_sync(self, *args, **kwargs):
                raise AssertionError("must not be asked for a render")

        class _Broken:
            available = True

            def render_page_sync(self, *args, **kwargs):
                raise RuntimeError("hmi-ui exploded")

        self.assertIsNone(render_for_critique(project, page, _NoBinary()))
        self.assertIsNone(render_for_critique(project, page, _Broken()))


if __name__ == "__main__":
    unittest.main()
