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


if __name__ == "__main__":
    unittest.main()
