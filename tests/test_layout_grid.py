"""designer/layout: the grid, the per-type rules and arrange.
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


# -- further tests ---------------------------------------------------------
from designer.layout.constraints import wants_caption  # noqa: E402

PANELS = ((480, 272), (800, 480), (1024, 768), (1280, 800), (1920, 1080), (2560, 1440))


def _box(widget):
    geometry = widget.geometry
    return (geometry["x"], geometry["y"],
            geometry["x"] + geometry["width"], geometry["y"] + geometry["height"])


def _overlapping(widgets):
    pairs = []
    for index, first in enumerate(widgets):
        for second in widgets[index + 1:]:
            ax, ay, ar, ab = _box(first)
            bx, by, br, bb = _box(second)
            if min(ar, br) > max(ax, bx) and min(ab, bb) > max(ay, by):
                pairs.append((first.id, second.id))
    return pairs


def _page(*widgets, width=1024, height=768):
    project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=list(widgets))])
    project.screen.width, project.screen.height = width, height
    return project, project.pages[0]


def _widget(widget_type, widget_id, x, y, w, h, **kwargs):
    return DesignerWidget(type=widget_type, id=widget_id,
                          geometry={"x": x, "y": y, "width": w, "height": h}, **kwargs)


class GridShapeTests(unittest.TestCase):
    def test_every_panel_tiles_exactly(self):
        for width, height in PANELS:
            g = grid_for(width, height)
            with self.subTest(panel=(width, height)):
                self.assertEqual(g.col_x(0), g.margin)
                self.assertEqual(g.col_x(g.columns - 1) + g.col_span(1), width - g.margin)
                self.assertEqual(g.row_y(0), g.margin)
                self.assertEqual(g.row_y(g.rows - 1) + g.row_span(1), height - g.margin)
                self.assertTrue(6 <= g.rows <= 24)
                # Columns never run backwards and never touch each other.
                lefts = g.col_lefts()
                self.assertEqual(lefts, sorted(lefts))
                self.assertTrue(all(lefts[i + 1] - (lefts[i] + g.col_span(1)) >= g.gutter
                                    for i in range(g.columns - 1)))

    def test_a_cell_is_already_snapped(self):
        for width, height in PANELS:
            g = grid_for(width, height)
            for col, row, cspan, rspan in ((0, 0, 1, 1), (3, 2, 4, 3), (8, 4, 4, 2), (11, 5, 1, 1)):
                cell = g.cell(col, row, cspan, rspan)
                with self.subTest(panel=(width, height), cell=(col, row, cspan, rspan)):
                    self.assertEqual(g.snap(*cell), cell)
                    self.assertEqual(g.nearest_cell(cell[0], cell[1]), (col, row))

    def test_cells_stay_inside_the_content_area(self):
        g = grid_for(1024, 768)
        x, y, w, h = g.cell(10, 8, 6, 6)
        self.assertLessEqual(x + w, g.width - g.margin)
        self.assertLessEqual(y + h, g.height - g.margin)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_snap_of_anything_lands_on_the_grid(self):
        g = grid_for(1280, 800)
        for rect in ((0, 0, 10, 10), (-40, -40, 2000, 2000), (700, 500, 1, 1), (333, 222, 481, 97)):
            x, y, w, h = g.snap(*rect)
            with self.subTest(rect=rect):
                self.assertIn(x, g.col_lefts())
                self.assertIn(y, g.row_tops())
                self.assertIn(x + w, g.col_rights())
                self.assertIn(y + h, g.row_bottoms())
                self.assertEqual(g.snap(x, y, w, h), (x, y, w, h))


class RuleShapeTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_a_tape_stays_a_tall_strip(self):
        rule = rule_for(self.registry, "ShTape")   # design 80 x 260
        w, h = fit_size(rule, 400, 200)
        self.assertLess(w, h)
        self.assertLessEqual(w / h, rule.aspect * (1 + rule.tolerance) + 1e-9)
        self.assertLessEqual(w, 400)

    def test_fit_never_grows_past_the_box_unless_a_minimum_says_so(self):
        for definition in self.registry.definitions():
            rule = rule_for(self.registry, definition.type)
            w, h = fit_size(rule, 300, 300)
            with self.subTest(type=definition.type):
                self.assertTrue(w <= 300 or w == rule.min_width)
                self.assertTrue(h <= 300 or h == rule.min_height)
                self.assertGreaterEqual(w, rule.min_width)
                self.assertGreaterEqual(h, rule.min_height)

    def test_fit_is_idempotent_for_every_type(self):
        for definition in self.registry.definitions():
            rule = rule_for(self.registry, definition.type)
            for box in ((864, 100), (20, 20), (1000, 30), (37, 900), (240, 240)):
                once = fit_size(rule, *box)
                with self.subTest(type=definition.type, box=box):
                    self.assertEqual(fit_size(rule, *once), once)
                    self.assertEqual([int(value) for value in once], list(once))

    def test_chrome_is_not_growable_but_instruments_are(self):
        self.assertFalse(rule_for(self.registry, "ShButton").growable)
        self.assertFalse(rule_for(self.registry, "Text").growable)
        self.assertFalse(rule_for(self.registry, "ShStatDot").growable)
        self.assertTrue(rule_for(self.registry, "ShClusterGauge").growable)
        self.assertTrue(rule_for(self.registry, "ShTrendChart").growable)
        self.assertTrue(rule_for(self.registry, "ShAlarmTable").growable)

    def test_only_a_face_without_a_label_wants_a_caption(self):
        self.assertTrue(wants_caption(self.registry, "ShFuelQuantity"))
        self.assertTrue(wants_caption(self.registry, "ShAutoLevel"))
        self.assertFalse(wants_caption(self.registry, "ShClusterGauge"))
        self.assertFalse(wants_caption(self.registry, "ShValueTile"))
        self.assertFalse(wants_caption(self.registry, "Text"))
        self.assertFalse(wants_caption(self.registry, "ShNope"))


class ArrangeShapeTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def _assert_composed(self, page, grid):
        self.assertEqual(_overlapping(page.widgets), [])
        for widget in page.widgets:
            x, y, right, bottom = _box(widget)
            self.assertGreaterEqual(x, grid.margin)
            self.assertGreaterEqual(y, grid.margin)
            self.assertLessEqual(right, grid.width - grid.margin)
            self.assertLessEqual(bottom, grid.height - grid.margin)

    def test_a_pile_of_widgets_is_spread_out(self):
        project, page = _page(*[
            _widget("ShValueTile", f"tile{index}", 100 + index, 100 + index, 220, 110)
            for index in range(6)
        ])
        grid = grid_for(project.screen.width, project.screen.height)
        report = arrange(project, page, self.registry)
        self.assertEqual(report.overlaps_after, 0)
        self.assertEqual(len(page.widgets), 6)
        self._assert_composed(page, grid)

    def test_offscreen_and_oversized_widgets_come_back_in(self):
        project, page = _page(
            _widget("ShGauge", "far", -400, 900, 200, 200),
            _widget("ShTrendChart", "huge", 10, 10, 4000, 3000),
            width=800, height=480)
        grid = grid_for(800, 480)
        report = arrange(project, page, self.registry)
        self.assertEqual(report.offscreen_before, 2)
        self.assertEqual(report.offscreen_after, 0)
        self._assert_composed(page, grid)

    def test_a_locked_widget_is_never_touched(self):
        project, page = _page(
            _widget("ShClusterGauge", "dial", 300, 200, 240, 240, locked=True),
            _widget("ShValueTile", "tile", 320, 220, 220, 110))
        before = dict(page.widgets[0].geometry)
        arrange(project, page, self.registry)
        self.assertEqual(dict(page.widgets[0].geometry), before)
        self.assertEqual(_overlapping(page.widgets), [])

    def test_children_are_composed_inside_their_parent(self):
        project, page = _page(_widget("ShCard", "card", 100, 100, 460, 360, children=[
            _widget("ShValueTile", "kidA", 10, 10, 220, 110),
            _widget("ShValueTile", "kidB", 20, 30, 220, 110),
        ]))
        arrange(project, page, self.registry)
        card = page.widgets[0]
        self.assertEqual([child.id for child in card.children], ["kidA", "kidB"])
        self.assertEqual(_overlapping(card.children), [])
        for child in card.children:
            x, y, right, bottom = _box(child)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(right, card.geometry["width"])
            self.assertLessEqual(bottom, card.geometry["height"])

    def test_a_small_panel_is_composed_too(self):
        project, page = _page(
            _widget("ShClusterGauge", "dial", 10, 10, 300, 300),
            _widget("ShButton", "go", 30, 30, 120, 12),
            _widget("Text", "label", 12, 250, 300, 30),
            width=480, height=272)
        arrange(project, page, self.registry)
        self._assert_composed(page, grid_for(480, 272))
        self.assertGreaterEqual(page.widgets[1].geometry["height"], 40)

    def test_nothing_is_invented_dropped_or_renamed(self):
        project, page = _load("ai-baseline.edsui")
        before = [(widget.type, widget.id, dict(widget.properties),
                   {key: binding.tag for key, binding in widget.bindings.items()},
                   dict(widget.actions)) for widget in page.walk()]
        arrange(project, page, self.registry)
        after = [(widget.type, widget.id, dict(widget.properties),
                  {key: binding.tag for key, binding in widget.bindings.items()},
                  dict(widget.actions)) for widget in page.walk()]
        self.assertEqual(after, before)
        for widget in page.walk():
            for value in widget.geometry.values():
                self.assertIsInstance(value, int)

    def test_two_runs_of_the_same_draft_agree(self):
        first_project, first_page = _load("ai-baseline.edsui")
        second_project, second_page = _load("ai-baseline.edsui")
        arrange(first_project, first_page, self.registry)
        arrange(second_project, second_page, self.registry)
        self.assertEqual([dict(widget.geometry) for widget in first_page.widgets],
                         [dict(widget.geometry) for widget in second_page.widgets])

    def test_the_hand_built_page_stays_put_the_second_time(self):
        project, page = _load("hand-built.edsui")
        arrange(project, page, self.registry)
        settled = [dict(widget.geometry) for widget in page.widgets]
        report = arrange(project, page, self.registry)
        self.assertEqual([dict(widget.geometry) for widget in page.widgets], settled)
        self.assertEqual((report.moved, report.resized), (0, 0))

    def test_a_given_grid_is_the_one_used(self):
        project, page = _page(_widget("ShValueTile", "tile", 33, 41, 220, 110))
        grid = grid_for(640, 480)
        arrange(project, page, self.registry, grid=grid)
        self.assertGreaterEqual(page.widgets[0].geometry["x"], grid.margin)
        self.assertLessEqual(_box(page.widgets[0])[2], 640 - grid.margin)

    def test_overlaps_reports_both_ids_and_the_area(self):
        _project, page = _page(
            _widget("ShValueTile", "a", 100, 100, 200, 100),
            _widget("ShValueTile", "b", 250, 150, 200, 100))
        found = overlaps(page)
        self.assertEqual(found, [("a", "b", 50 * 50)])

    def test_align_edges_leaves_a_diagonal_alone(self):
        project, page = _page(
            _widget("ShValueTile", "a", 40, 40, 200, 120),
            _widget("ShValueTile", "b", 52, 200, 200, 120),
            _widget("ShValueTile", "c", 64, 360, 200, 120))
        before = [dict(widget.geometry) for widget in page.widgets]
        align_edges(page, grid_for(project.screen.width, project.screen.height))
        self.assertEqual([dict(widget.geometry) for widget in page.widgets], before)


if __name__ == "__main__":
    unittest.main()
