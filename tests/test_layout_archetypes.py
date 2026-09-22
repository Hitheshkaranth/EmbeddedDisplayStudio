"""designer/layout: archetypes and the style pass (W3 gate).

FROZEN: the minimum W3 must pass; add more below, never change these.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from designer.layout import (  # noqa: E402
    Archetype, Slot, apply_archetype, apply_style, archetype_for, archetypes, critique,
    grid_for, role_for,
)
from designer.layout.style import TYPE_SCALE, group_into_cards, theme_colour  # noqa: E402
from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "layout"


def _load(name):
    project = DesignerProject.load(str(FIXTURES / name))
    return project, project.pages[0]


class ArchetypeTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_the_catalogue(self):
        catalogue = archetypes()
        self.assertGreaterEqual(len(catalogue), 5)
        ids = [a.id for a in catalogue]
        self.assertEqual(len(ids), len(set(ids)))
        for archetype in catalogue:
            self.assertIsInstance(archetype, Archetype)
            self.assertGreaterEqual(len(archetype.slots), 6)
            self.assertLessEqual(len(archetype.slots), 14)
            names = [s.name for s in archetype.slots]
            self.assertEqual(len(names), len(set(names)))
            self.assertEqual(len([s for s in archetype.slots if s.role == "hero"]), 1, archetype.id)
            for slot in archetype.slots:
                self.assertIsInstance(slot, Slot)
                self.assertGreaterEqual(slot.col, 0)
                self.assertLessEqual(slot.col + slot.cspan, 12)
                self.assertGreaterEqual(slot.rspan, 1)

    def test_archetype_choice_follows_the_brief_then_the_count(self):
        cluster = archetype_for("automotive instrument cluster with RPM and speed", 6)
        self.assertEqual(cluster.id, "hero-centre")
        alarms = archetype_for("alarm overview with an alarm table and a log", 8)
        self.assertEqual(alarms.id, "split")
        self.assertIsInstance(archetype_for("", 3), Archetype)
        self.assertIsInstance(archetype_for("", 14), Archetype)

    def test_roles(self):
        gauge = DesignerWidget(type="ShClusterGauge", id="g", geometry={"x": 0, "y": 0, "width": 400, "height": 400})
        button = DesignerWidget(type="ShButton", id="b", geometry={"x": 0, "y": 0, "width": 120, "height": 40})
        text = DesignerWidget(type="Text", id="t", geometry={"x": 0, "y": 0, "width": 200, "height": 30})
        dot = DesignerWidget(type="ShStatDot", id="d", geometry={"x": 0, "y": 0, "width": 16, "height": 16})
        table = DesignerWidget(type="ShAlarmTable", id="a", geometry={"x": 0, "y": 0, "width": 350, "height": 216})
        page = DesignerPage("main", "Main", widgets=[gauge, button, text, dot, table])
        self.assertEqual(role_for(self.registry, gauge), "hero")
        self.assertEqual(role_for(self.registry, button), "control")
        self.assertEqual(role_for(self.registry, text), "caption")
        self.assertEqual(role_for(self.registry, dot), "status")
        self.assertEqual(role_for(self.registry, table), "table")

    def test_applying_an_archetype_composes_the_draft(self):
        project, page = _load("ai-baseline.edsui")
        ids = sorted(w.id for w in page.widgets)
        before = critique(project, page, self.registry)
        notes = apply_archetype(project, page, archetype_for("engine data summary", len(page.widgets)),
                                self.registry)
        self.assertEqual(sorted(w.id for w in page.widgets), ids)
        self.assertIsInstance(notes, list)
        after = critique(project, page, self.registry)
        self.assertGreater(after.score, before.score)
        self.assertEqual(after.scores["overlap"], 100)
        g = grid_for(project.screen.width, project.screen.height)
        for w in page.widgets:
            self.assertGreaterEqual(w.geometry["x"], g.margin)
            self.assertLessEqual(w.geometry["x"] + w.geometry["width"], g.width - g.margin)

    def test_more_widgets_than_slots_still_places_everything(self):
        widgets = [DesignerWidget(type="ShValueTile", id=f"t{i}",
                                  geometry={"x": 10 * i, "y": 10 * i, "width": 200, "height": 120})
                   for i in range(20)]
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=widgets)])
        page = project.pages[0]
        apply_archetype(project, page, archetypes()[0], self.registry)
        self.assertEqual(len(page.widgets), 20)


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_type_scale_and_tokens(self):
        project, page = _load("ai-baseline.edsui")
        notes = apply_style(project, page, self.registry)
        self.assertIsInstance(notes, list)
        sizes = {int(w.properties["fontSize"]) for w in page.widgets
                 if w.type == "Text" and w.properties.get("fontSize")}
        scale = set(TYPE_SCALE.values())
        for size in sizes:
            self.assertTrue(any(abs(size - step) <= max(2, step * 0.25) for step in scale),
                            f"{size} is not near a step of {sorted(scale)}")
        self.assertRegex(theme_colour(project, "warning"), r"^#[0-9a-fA-F]{6}$")
        self.assertRegex(theme_colour(project, "destructive"), r"^#[0-9a-fA-F]{6}$")

    def test_style_keeps_the_design_intact(self):
        project, page = _load("hand-built.edsui")
        types = [w.type for w in page.widgets]
        bindings = {w.id: dict(w.bindings) for w in page.widgets}
        apply_style(project, page, self.registry)
        self.assertEqual([w.type for w in page.widgets][:len(types)], types)
        for w in page.widgets:
            if w.id in bindings:
                self.assertEqual(set(w.bindings), set(bindings[w.id]))

    def test_cards_group_peers(self):
        widgets = [DesignerWidget(type="ShValueTile", id=f"t{i}",
                                  geometry={"x": 40 + i * 220, "y": 500, "width": 200, "height": 120},
                                  bindings={"value": DesignerBinding(tag=f"line.temp{i}")})
                   for i in range(3)]
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=widgets)])
        page = project.pages[0]
        notes = group_into_cards(project, page, self.registry)
        self.assertIsInstance(notes, list)
        cards = [w for w in page.widgets if w.type == "ShCard"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(cards[0].children), 3)
        self.assertEqual(len([w for w in page.widgets if w.type == "ShValueTile"]), 0)


# ===========================================================================
# STAND-IN, removed at integration.
#
# W1 (grid, constraints) and W2 (critic) raise NotImplementedError in this
# worktree, and the frozen tests above call all three. What follows is the
# smallest thing that satisfies their docstrings, bound onto their modules so
# W3's code exercises the real call sites. Delete this whole block -- down to
# "end of STAND-IN" -- when their implementations land on feat/ai-beauty;
# nothing below it depends on anything defined in it.
# ===========================================================================
import designer.layout.constraints as _standin_constraints  # noqa: E402
import designer.layout.critic as _standin_critic  # noqa: E402
import designer.layout.grid as _standin_grid  # noqa: E402
from designer.layout.constraints import SQUARE_TYPES, TOUCH_MIN_HEIGHT, WidgetRule  # noqa: E402
from designer.layout.critic import WEIGHTS, Critique, Issue  # noqa: E402
from designer.layout.grid import COLUMNS, Grid  # noqa: E402

_STANDIN_FIXED = ("ShButton", "ShToggle", "ShCheckbox", "ShSelect", "ShNumInput",
                  "ShInput", "ShStatDot", "Text", "ShTelltale", "ShProgress", "ShSlider")


def _clamp(value, low, high):
    return max(low, min(high, value))


def _standin_grid_for(width, height):
    margin = _clamp(round(min(width, height) * 0.035), 12, 40)
    gutter = _clamp(round(margin * 0.6), 8, 24)
    rows = _clamp(int(round((height - 2 * margin) / float(gutter * 3))), 6, 24)
    return Grid(int(width), int(height), int(margin), int(gutter), COLUMNS, int(rows))


def _col_pitch(grid):
    return (grid.content_width - (grid.columns - 1) * grid.gutter) / float(grid.columns)


def _row_pitch(grid):
    return (grid.content_height - (grid.rows - 1) * grid.gutter) / float(grid.rows)


Grid.content_width = property(lambda self: self.width - 2 * self.margin)
Grid.content_height = property(lambda self: self.height - 2 * self.margin)
Grid.col_x = lambda self, col: int(round(self.margin + col * (_col_pitch(self) + self.gutter)))
Grid.col_span = lambda self, span: int(round(span * _col_pitch(self) + (span - 1) * self.gutter))
Grid.row_y = lambda self, row: int(round(self.margin + row * (_row_pitch(self) + self.gutter)))
Grid.row_span = lambda self, span: int(round(span * _row_pitch(self) + (span - 1) * self.gutter))


def _standin_cell(self, col, row, cspan=1, rspan=1):
    x, y = self.col_x(col), self.row_y(row)
    w, h = self.col_span(max(1, cspan)), self.row_span(max(1, rspan))
    w = max(1, min(w, self.margin + self.content_width - x))
    h = max(1, min(h, self.margin + self.content_height - y))
    return (x, y, w, h)


def _standin_nearest_cell(self, x, y):
    col = _clamp(int(round((x - self.margin) / (_col_pitch(self) + self.gutter))),
                 0, self.columns - 1)
    row = _clamp(int(round((y - self.margin) / (_row_pitch(self) + self.gutter))),
                 0, self.rows - 1)
    return (col, row)


def _standin_snap(self, x, y, w, h):
    col, row = self.nearest_cell(x, y)
    cspan = _clamp(int(round((w + self.gutter) / (_col_pitch(self) + self.gutter))),
                   1, self.columns - col)
    rspan = _clamp(int(round((h + self.gutter) / (_row_pitch(self) + self.gutter))),
                   1, self.rows - row)
    return self.cell(col, row, cspan, rspan)


Grid.cell = _standin_cell
Grid.nearest_cell = _standin_nearest_cell
Grid.snap = _standin_snap


def _standin_rule_for(registry, widget_type):
    definition = registry.get(widget_type) if registry is not None else None
    if definition is None:
        return WidgetRule(widget_type, 24, 24, None, 0.15, False, True)
    min_width = max(24, int(round(definition.default_width * 0.6)))
    min_height = max(24, int(round(definition.default_height * 0.6)))
    if definition.action_signals:
        min_height = max(min_height, TOUCH_MIN_HEIGHT)
    square = widget_type in SQUARE_TYPES
    aspect = 1.0 if square else definition.default_width / float(definition.default_height)
    return WidgetRule(widget_type, min_width, min_height, aspect, 0.0 if square else 0.15,
                      square, widget_type not in _STANDIN_FIXED)


def _standin_fit_size(rule, width, height):
    width = max(float(width), rule.min_width)
    height = max(float(height), rule.min_height)
    if rule.square:
        side = min(width, height)
        return int(round(side)), int(round(side))
    if rule.aspect:
        actual = width / height if height else rule.aspect
        if abs(actual - rule.aspect) > rule.tolerance * rule.aspect:
            if actual > rule.aspect:
                width = max(rule.min_width, rule.aspect * height)
            else:
                height = max(rule.min_height, width / rule.aspect)
    return int(round(width)), int(round(height))


def _standin_wants_caption(registry, widget_type):
    definition = registry.get(widget_type) if registry is not None else None
    if definition is None or definition.container or widget_type in ("Text", "Image", "Rectangle"):
        return False
    return not any(name in definition.properties
                   for name in ("label", "title", "text", "topLabel", "caption"))


def _standin_rects(page):
    out = []
    for widget in page.widgets:
        geometry = widget.geometry or {}
        out.append((widget, float(geometry.get("x", 0)), float(geometry.get("y", 0)),
                    float(geometry.get("width", 0)), float(geometry.get("height", 0))))
    return out


def _standin_critique(project, page, registry, image=None, grid=None):
    grid = grid or _standin_grid.grid_for(project.screen.width, project.screen.height)
    rects = _standin_rects(page)
    issues = []
    if not rects:
        return Critique(0.0, {axis: None for axis in WEIGHTS}, (Issue("empty", "error", "", "no widgets"),))
    total = sum(max(1.0, w * h) for _x, _a, _b, w, h in rects) or 1.0

    overlapping = 0.0
    for i, (wa, ax, ay, aw, ah) in enumerate(rects):
        for wb, bx, by, bw, bh in rects[i + 1:]:
            dx = min(ax + aw, bx + bw) - max(ax, bx)
            dy = min(ay + ah, by + bh) - max(ay, by)
            if dx > 0 and dy > 0:
                overlapping += dx * dy
                issues.append(Issue("overlap", "error", wa.id,
                                    f"{wa.id} and {wb.id} overlap by {int(dx * dy)} px"))
    overlap = 100.0 if overlapping <= 0 else max(0.0, 100.0 - 400.0 * overlapping / total)

    outside = 0
    for widget, x, y, w, h in rects:
        if (x < grid.margin or y < grid.margin or x + w > grid.width - grid.margin
                or y + h > grid.height - grid.margin):
            outside += 1
            issues.append(Issue("margins", "error", widget.id, f"{widget.id} crosses the margin"))
    margins = 100.0 * (1.0 - outside / float(len(rects)))

    edges = 0
    for index in (0, 1):
        starts = {round(item[1 + index]) for item in rects}
        ends = {round(item[1 + index] + item[3 + index]) for item in rects}
        edges += len(starts) + len(ends)
    ideal, worst = 4.0, 4.0 * len(rects)
    alignment = 100.0 * max(0.0, (worst - edges) / max(1.0, worst - ideal))

    on_grid = 0
    columns = [grid.col_x(c) for c in range(grid.columns)]
    for _widget, x, y, w, h in rects:
        if any(abs(x - c) <= 2 for c in columns) or any(abs(x + w - (c + grid.col_span(1))) <= 2
                                                        for c in columns):
            on_grid += 1
    grid_score = 100.0 * on_grid / float(len(rects))

    areas = sorted((w * h for _a, _b, _c, w, h in rects), reverse=True)
    hierarchy = 100.0 if len(areas) == 1 or areas[0] >= 1.8 * areas[1] else 45.0

    cx = sum((x + w / 2) * w * h for _a, x, _y, w, h in rects) / total
    cy = sum((y + h / 2) * w * h for _a, _x, y, w, h in rects) / total
    off = (abs(cx - grid.width / 2) / (grid.width / 2) + abs(cy - grid.height / 2) / (grid.height / 2)) / 2
    balance = 100.0 * max(0.0, 1.0 - off)

    good = 0
    for widget, _x, _y, w, h in rects:
        rule = _standin_constraints.rule_for(registry, widget.type)
        fitted = _standin_constraints.fit_size(rule, w, h)
        if abs(fitted[0] - w) <= max(2, w * 0.08) and abs(fitted[1] - h) <= max(2, h * 0.08):
            good += 1
        else:
            issues.append(Issue("proportion", "warning", widget.id,
                                f"{widget.id} is {int(w)}x{int(h)}, its type wants "
                                f"{fitted[0]}x{fitted[1]}"))
    proportion = 100.0 * good / float(len(rects))

    scores = {"overlap": overlap, "margins": margins, "alignment": alignment,
              "grid": grid_score, "hierarchy": hierarchy, "balance": balance,
              "proportion": proportion, "clipping": None, "contrast": None}
    weighted = sum(WEIGHTS[axis] * value for axis, value in scores.items() if value is not None)
    divisor = sum(WEIGHTS[axis] for axis, value in scores.items() if value is not None)
    order = {"error": 0, "warning": 1, "nit": 2}
    return Critique(weighted / divisor, scores,
                    tuple(sorted(issues, key=lambda i: (order[i.severity], i.kind, i.widget_id))))


_standin_grid.grid_for = _standin_grid_for
_standin_constraints.rule_for = _standin_rule_for
_standin_constraints.fit_size = _standin_fit_size
_standin_constraints.wants_caption = _standin_wants_caption
_standin_critic.critique = _standin_critique
# The frozen tests bound these names at import, before the stand-ins existed.
grid_for = _standin_grid_for
critique = _standin_critique
# ============================ end of STAND-IN ==============================


def _geometry(page):
    return [(w.id, dict(w.geometry)) for w in page.walk()]


class ArchetypeBoardTests(unittest.TestCase):
    """The five boards as drawings: what covers what."""

    def setUp(self):
        self.registry = default_registry()

    def test_every_board_is_drawn_inside_the_canonical_frame(self):
        from designer.layout.archetypes import CANONICAL_ROWS
        for archetype in archetypes():
            for slot in archetype.slots:
                self.assertGreaterEqual(slot.row, 0, f"{archetype.id}/{slot.name}")
                self.assertLessEqual(slot.row + slot.rspan, CANONICAL_ROWS,
                                     f"{archetype.id}/{slot.name}")
                self.assertGreaterEqual(slot.cspan, 1)
                self.assertIn(slot.role, ("hero", "primary", "secondary", "control",
                                          "status", "caption", "table", "rail"))

    def test_no_two_slots_of_a_board_cover_the_same_cell(self):
        for archetype in archetypes():
            seen = {}
            for slot in archetype.slots:
                for col in range(slot.col, slot.col + slot.cspan):
                    for row in range(slot.row, slot.row + slot.rspan):
                        other = seen.get((col, row))
                        self.assertIsNone(other, f"{archetype.id}: {slot.name} covers "
                                                 f"cell {(col, row)} already held by {other}")
                        seen[(col, row)] = slot.name

    def test_slots_for_is_that_role_in_priority_order(self):
        for archetype in archetypes():
            for role in ("hero", "primary", "secondary", "control", "status", "caption"):
                slots = archetype.slots_for(role)
                self.assertTrue(all(s.role == role for s in slots), archetype.id)
                self.assertEqual(list(slots), sorted(slots, key=lambda s: s.priority))
            self.assertEqual(len(archetype.slots_for("hero")), 1, archetype.id)

    def test_the_board_covers_the_screen_without_overlap(self):
        """Resolved to pixels, no two slots of a board overlap."""
        for width, height in ((1024, 768), (1280, 800), (480, 272)):
            g = grid_for(width, height)
            for archetype in archetypes():
                from designer.layout.archetypes import _slot_rect
                rects = [(_slot_rect(g, slot), slot.name) for slot in archetype.slots]
                for index, (a, name_a) in enumerate(rects):
                    for b, name_b in rects[index + 1:]:
                        dx = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                        dy = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                        self.assertFalse(dx > 0 and dy > 0,
                                         f"{width}x{height} {archetype.id}: {name_a} "
                                         f"and {name_b} overlap")


class ArchetypePlacementTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_the_choice_by_count_when_the_brief_says_nothing(self):
        self.assertEqual(archetype_for("", 4).id, "hero-centre")
        self.assertEqual(archetype_for("", 8).id, "thirds")
        self.assertEqual(archetype_for("", 12).id, "header-hero-rail")
        self.assertEqual(archetype_for("", 13).id, "card-grid")
        self.assertEqual(archetype_for("a tile menu", 3).id, "card-grid")

    def test_every_archetype_keeps_every_widget_inside_the_margins(self):
        for archetype in archetypes():
            project, page = _load("ai-baseline.edsui")
            ids = sorted(w.id for w in page.widgets)
            apply_archetype(project, page, archetype, self.registry)
            self.assertEqual(sorted(w.id for w in page.widgets), ids, archetype.id)
            g = grid_for(project.screen.width, project.screen.height)
            for w in page.widgets:
                self.assertGreaterEqual(w.geometry["x"], g.margin, f"{archetype.id}/{w.id}")
                self.assertGreaterEqual(w.geometry["y"], g.margin, f"{archetype.id}/{w.id}")
                self.assertLessEqual(w.geometry["x"] + w.geometry["width"],
                                     g.width - g.margin, f"{archetype.id}/{w.id}")
                self.assertLessEqual(w.geometry["y"] + w.geometry["height"],
                                     g.height - g.margin, f"{archetype.id}/{w.id}")
            self.assertEqual(critique(project, page, self.registry).scores["overlap"], 100,
                             archetype.id)

    def test_applying_an_archetype_twice_changes_nothing(self):
        for archetype in archetypes():
            project, page = _load("ai-baseline.edsui")
            apply_archetype(project, page, archetype, self.registry)
            once = _geometry(page)
            notes = apply_archetype(project, page, archetype, self.registry)
            self.assertEqual(_geometry(page), once, archetype.id)
            self.assertIsInstance(notes, list)

    def test_the_hero_is_the_biggest_face_and_there_is_only_one(self):
        project, page = _load("ai-baseline.edsui")
        from designer.layout.archetypes import _page_roles
        roles = _page_roles(self.registry, page)
        self.assertEqual([wid for wid, role in roles.items() if role == "hero"], ["rpmGauge"])
        apply_archetype(project, page, archetypes()[0], self.registry, None)
        gauge = next(w for w in page.widgets if w.id == "rpmGauge")
        biggest = max(page.widgets, key=lambda w: w.geometry["width"] * w.geometry["height"])
        self.assertIs(biggest, gauge)
        self.assertEqual(gauge.geometry["width"], gauge.geometry["height"])

    def test_a_small_panel_still_gets_a_composition(self):
        project, page = _load("ai-baseline.edsui")
        project.screen.width, project.screen.height = 480, 272
        apply_archetype(project, page, archetypes()[0], self.registry)
        g = grid_for(480, 272)
        for w in page.widgets:
            self.assertGreaterEqual(w.geometry["x"], g.margin)
            self.assertLessEqual(w.geometry["x"] + w.geometry["width"], 480 - g.margin)
            self.assertGreaterEqual(w.geometry["width"], 1)

    def test_containers_keep_their_children(self):
        child = DesignerWidget(type="ShValueTile", id="inner",
                               geometry={"x": 10, "y": 10, "width": 100, "height": 60})
        card = DesignerWidget(type="ShCard", id="card",
                              geometry={"x": 0, "y": 0, "width": 200, "height": 120},
                              children=[child])
        gauge = DesignerWidget(type="ShClusterGauge", id="g",
                               geometry={"x": 0, "y": 0, "width": 400, "height": 400})
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main",
                                                                widgets=[card, gauge])])
        apply_archetype(project, project.pages[0], archetypes()[0], self.registry)
        self.assertEqual([c.id for c in card.children], ["inner"])
        self.assertGreater(child.geometry["width"], 0)
        self.assertLessEqual(child.geometry["x"] + child.geometry["width"],
                             card.geometry["width"] + 1)

    def test_roles_of_the_whole_catalogue_of_types(self):
        for widget_type, expected in (("ShAlarmTable", "table"), ("ShTelltale", "status"),
                                      ("Text", "caption"), ("ShSlider", "control"),
                                      ("ShValueTile", "secondary"), ("ShTape", "primary"),
                                      ("ShTrendChart", "primary"), ("Nonsense", "secondary")):
            widget = DesignerWidget(type=widget_type, id="w",
                                    geometry={"x": 0, "y": 0, "width": 100, "height": 60})
            self.assertEqual(role_for(self.registry, widget), expected, widget_type)


class StylePassTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_the_tokens_come_from_the_kit(self):
        project, _page = _load("ai-baseline.edsui")
        self.assertEqual(theme_colour(project, "destructive"), "#f31260")
        self.assertEqual(theme_colour(project, "card"), "#18181b")
        project.screen.theme = "light"
        self.assertEqual(theme_colour(project, "destructive"), "#ef4444")
        self.assertEqual(theme_colour(project, "warning"), "#f59e0b")
        self.assertRegex(theme_colour(project, "not-a-token"), r"^#[0-9a-fA-F]{6}$")

    def test_style_is_idempotent(self):
        project, page = _load("ai-baseline.edsui")
        apply_style(project, page, self.registry)
        once = ([(w.id, w.type, dict(w.properties)) for w in page.walk()], len(page.widgets))
        apply_style(project, page, self.registry)
        twice = ([(w.id, w.type, dict(w.properties)) for w in page.walk()], len(page.widgets))
        self.assertEqual(twice, once)

    def test_captions_are_added_under_the_faces_that_have_no_label(self):
        project, page = _load("ai-baseline.edsui")
        apply_archetype(project, page, archetypes()[0], self.registry)
        apply_style(project, page, self.registry)
        captions = [w for w in page.widgets if w.id.endswith("Caption")]
        self.assertTrue(captions)
        fuel = next(w for w in page.widgets if w.id == "fuelQty")
        caption = next(w for w in captions if w.id == "fuelQtyCaption")
        self.assertEqual(caption.type, "Text")
        self.assertEqual(caption.geometry["x"], fuel.geometry["x"])
        self.assertGreater(caption.geometry["y"], fuel.geometry["y"])
        self.assertEqual(caption.properties["text"], "Quantity")
        self.assertEqual(caption.properties["fontSize"], TYPE_SCALE["caption"])

    def test_the_type_scale_has_one_title_and_never_lands_between_steps(self):
        project, page = _load("ai-baseline.edsui")
        apply_style(project, page, self.registry)
        sizes = [int(w.properties["fontSize"]) for w in page.walk() if w.type == "Text"]
        self.assertTrue(sizes)
        for size in sizes:
            self.assertIn(size, set(TYPE_SCALE.values()))
        self.assertEqual(sizes.count(TYPE_SCALE["title"]), 1)

    def test_a_model_invented_hex_becomes_a_token_and_a_token_is_left_alone(self):
        widget = DesignerWidget(type="ShNumDisplay", id="n",
                                geometry={"x": 40, "y": 40, "width": 180, "height": 80},
                                properties={"faultColor": "#ff0000", "warningColor": "#f59e0b"},
                                bindings={"value": DesignerBinding(tag="a.b", critical="> 9")})
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=[widget])])
        apply_style(project, project.pages[0], self.registry)
        self.assertEqual(widget.properties["faultColor"], theme_colour(project, "destructive"))
        self.assertEqual(widget.properties["warningColor"], "#f59e0b")

    def test_style_never_touches_what_a_widget_says(self):
        project, page = _load("hand-built.edsui")
        said = {w.id: (w.properties.get("text"), w.properties.get("label"),
                       w.properties.get("title"), w.properties.get("unit"))
                for w in page.walk()}
        apply_style(project, page, self.registry)
        for widget in page.walk():
            if widget.id in said:
                self.assertEqual((widget.properties.get("text"), widget.properties.get("label"),
                                  widget.properties.get("title"), widget.properties.get("unit")),
                                 said[widget.id], widget.id)

    def test_a_group_of_one_is_not_worth_a_card(self):
        widget = DesignerWidget(type="ShValueTile", id="only",
                                geometry={"x": 40, "y": 500, "width": 200, "height": 120},
                                bindings={"value": DesignerBinding(tag="line.temp")})
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=[widget])])
        notes = group_into_cards(project, project.pages[0], self.registry)
        self.assertEqual(notes, [])
        self.assertEqual([w.type for w in project.pages[0].widgets], ["ShValueTile"])

    def test_peers_without_a_common_tag_prefix_stay_where_they_are(self):
        widgets = [DesignerWidget(type="ShValueTile", id=f"t{i}",
                                  geometry={"x": 40 + i * 220, "y": 500, "width": 200, "height": 120},
                                  bindings={"value": DesignerBinding(tag=f"line{i}.temp")})
                   for i in range(3)]
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=widgets)])
        group_into_cards(project, project.pages[0], self.registry)
        self.assertEqual([w.type for w in project.pages[0].widgets], ["ShValueTile"] * 3)

    def test_a_card_keeps_its_children_ids_and_is_not_made_twice(self):
        widgets = [DesignerWidget(type="ShValueTile", id=f"t{i}",
                                  geometry={"x": 40 + i * 220, "y": 500, "width": 200, "height": 120},
                                  bindings={"value": DesignerBinding(tag=f"line.temp{i}")})
                   for i in range(3)]
        project = DesignerProject(name="t", pages=[DesignerPage("main", "Main", widgets=widgets)])
        page = project.pages[0]
        group_into_cards(project, page, self.registry)
        card = page.widgets[0]
        self.assertEqual([c.id for c in card.children], ["t0", "t1", "t2"])
        for child in card.children:
            self.assertGreaterEqual(child.geometry["x"], 0)
            self.assertLessEqual(child.geometry["x"] + child.geometry["width"],
                                 card.geometry["width"])
        group_into_cards(project, page, self.registry)
        self.assertEqual(len([w for w in page.widgets if w.type == "ShCard"]), 1)


if __name__ == "__main__":
    unittest.main()
