"""designer/layout: the grid, the per-type rules and arrange (W1 gate).

FROZEN: the minimum W1 must pass; add more below, never change these.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from designer.layout import Grid, WidgetRule, arrange, fit_size, grid_for, rule_for  # noqa: E402
from designer.layout.arrange import align_edges, overlaps  # noqa: E402
from designer.model import DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "layout"


def _load(name):
    project = DesignerProject.load(str(FIXTURES / name))
    return project, project.pages[0]


class GridTests(unittest.TestCase):
    def test_grid_for_scales_with_the_screen(self):
        small, big = grid_for(480, 272), grid_for(1920, 1080)
        for g in (small, big):
            self.assertIsInstance(g, Grid)
            self.assertEqual(g.columns, 12)
            self.assertGreaterEqual(g.rows, 6)
            self.assertGreaterEqual(g.margin, 12)
            self.assertGreater(g.gutter, 0)
        self.assertLess(small.margin, big.margin)
        self.assertLessEqual(big.margin, 40)

    def test_cells_tile_the_content_area(self):
        g = grid_for(1024, 768)
        self.assertEqual(g.col_x(0), g.margin)
        self.assertEqual(g.col_x(11) + g.col_span(1), g.width - g.margin)
        self.assertEqual(g.row_y(0), g.margin)
        self.assertEqual(g.row_y(g.rows - 1) + g.row_span(1), g.height - g.margin)
        x, y, w, h = g.cell(0, 0, 6, 3)
        self.assertEqual((x, y), (g.margin, g.margin))
        self.assertEqual(w, g.col_span(6))
        self.assertEqual(h, g.row_span(3))

    def test_snap_is_idempotent_and_inside(self):
        g = grid_for(1024, 768)
        raw = g.snap(37, 41, 393, 197)
        self.assertEqual(g.snap(*raw), raw)
        x, y, w, h = raw
        self.assertGreaterEqual(x, g.margin)
        self.assertGreaterEqual(y, g.margin)
        self.assertLessEqual(x + w, g.width - g.margin)
        self.assertLessEqual(y + h, g.height - g.margin)
        self.assertIn(x, [g.col_x(c) for c in range(12)])


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_dials_are_square_and_have_a_floor(self):
        rule = rule_for(self.registry, "ShClusterGauge")
        self.assertIsInstance(rule, WidgetRule)
        self.assertTrue(rule.square)
        self.assertEqual(fit_size(rule, 400, 260)[0], fit_size(rule, 400, 260)[1])
        w, h = fit_size(rule, 20, 20)
        self.assertGreaterEqual(min(w, h), rule.min_width)

    def test_the_baselines_fuel_gauge_is_corrected(self):
        # The real defect: ShFuelQuantity (design 190x130) asked for 864x100.
        rule = rule_for(self.registry, "ShFuelQuantity")
        w, h = fit_size(rule, 864, 100)
        self.assertLessEqual(w, 864)
        self.assertGreaterEqual(h, rule.min_height)
        self.assertLess(w / h, 864 / 100)

    def test_controls_keep_a_touch_height(self):
        rule = rule_for(self.registry, "ShButton")
        self.assertGreaterEqual(rule.min_height, 40)
        self.assertGreaterEqual(fit_size(rule, 120, 12)[1], 40)

    def test_unknown_type_is_permissive(self):
        rule = rule_for(self.registry, "ShNope")
        self.assertIsNone(rule.aspect)
        self.assertEqual(fit_size(rule, 300, 200), (300, 200))


class ArrangeTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_arrange_fixes_the_ai_baseline(self):
        project, page = _load("ai-baseline.edsui")
        before = len(overlaps(page))
        self.assertGreater(before, 0, "fixture should contain the baseline's overlap")
        ids = [w.id for w in page.widgets]
        report = arrange(project, page, self.registry)
        self.assertEqual([w.id for w in page.widgets], ids)      # nothing invented or dropped
        self.assertEqual(report.overlaps_before, before)
        self.assertEqual(report.overlaps_after, 0)
        self.assertEqual(len(overlaps(page)), 0)
        g = grid_for(project.screen.width, project.screen.height)
        for w in page.widgets:
            self.assertGreaterEqual(w.geometry["x"], g.margin)
            self.assertGreaterEqual(w.geometry["y"], g.margin)
            self.assertLessEqual(w.geometry["x"] + w.geometry["width"], g.width - g.margin)
            self.assertLessEqual(w.geometry["y"] + w.geometry["height"], g.height - g.margin)

    def test_arrange_is_stable(self):
        project, page = _load("ai-baseline.edsui")
        arrange(project, page, self.registry)
        first = [dict(w.geometry) for w in page.widgets]
        second_report = arrange(project, page, self.registry)
        self.assertEqual([dict(w.geometry) for w in page.widgets], first)
        self.assertEqual(second_report.moved, 0)
        self.assertEqual(second_report.resized, 0)

    def test_arrange_reduces_distinct_edges(self):
        project, page = _load("ai-baseline.edsui")
        lefts = {w.geometry["x"] for w in page.widgets}
        arrange(project, page, self.registry)
        self.assertLessEqual(len({w.geometry["x"] for w in page.widgets}), len(lefts))

    def test_align_edges_pulls_near_equal_edges_together(self):
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=[
            DesignerWidget(type="ShValueTile", id="a", geometry={"x": 40, "y": 40, "width": 200, "height": 120}),
            DesignerWidget(type="ShValueTile", id="b", geometry={"x": 44, "y": 200, "width": 200, "height": 120}),
        ])])
        page = project.pages[0]
        moved = align_edges(page, grid_for(project.screen.width, project.screen.height))
        self.assertGreaterEqual(moved, 1)
        self.assertEqual(page.widgets[0].geometry["x"], page.widgets[1].geometry["x"])

    def test_hand_built_page_is_barely_touched(self):
        project, page = _load("hand-built.edsui")
        report = arrange(project, page, self.registry)
        self.assertEqual(report.overlaps_after, 0)
        # A designed page is already close to the grid: at most a third of it moves.
        self.assertLessEqual(report.moved, max(1, len(page.widgets) // 3))


if __name__ == "__main__":
    unittest.main()
