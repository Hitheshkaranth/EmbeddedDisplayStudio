"""designer/layout: archetypes and the style pass.
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
