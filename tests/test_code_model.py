"""designer/code/code_model.py -- code texts for a design section (W1 gate).

FROZEN: the tests below are the minimum W1 must pass; add more below them,
never change these.
"""
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from designer.code import (  # noqa: E402
    CodeError, CodeSection, page_edsui, page_qml, parse_page_edsui, parse_widget_edsui,
    section_for, widget_edsui, widget_qml,
)
from designer.generators.qml_generator import QmlGenerator  # noqa: E402
from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402


def _project():
    gauge = DesignerWidget(type="ShGauge", id="gauge1", geometry={"x": 10, "y": 20, "width": 200, "height": 200},
                           properties={"label": "RPM", "value": 137},
                           bindings={"value": DesignerBinding(tag="engine.rpm")})
    card = DesignerWidget(type="ShCard", id="card1", geometry={"x": 300, "y": 20, "width": 300, "height": 200},
                          children=[DesignerWidget(type="Text", id="text1", geometry={"x": 8, "y": 8, "width": 100, "height": 20},
                                                   properties={"text": "hello"})])
    page = DesignerPage("main", "Main", widgets=[gauge, card])
    project = DesignerProject(name="demo", pages=[page])
    return project, page, gauge, card


class WidgetQmlTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)
        self.project, self.page, self.gauge, self.card = _project()

    def test_widget_qml_is_the_generators_lines(self):
        text = widget_qml(self.generator, self.project, self.gauge)
        expected = "\n".join(self.generator._widget(self.gauge, 0)).lstrip("\n") + "\n"
        self.assertEqual(text, expected)
        self.assertIn("ShGauge {", text)
        self.assertIn("id: gauge1", text)
        self.assertIn("engine.rpm", text)          # bindings stay in

    def test_widget_qml_includes_children(self):
        text = widget_qml(self.generator, self.project, self.card)
        self.assertIn("id: card1", text)
        self.assertIn("id: text1", text)

    def test_page_qml_is_the_page_file(self):
        text = page_qml(self.generator, self.project, self.page)
        self.assertEqual(text, self.generator._page(self.project, self.page))
        self.assertIn("id: gauge1", text)
        self.assertIn("id: card1", text)


class EdsuiRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.project, self.page, self.gauge, self.card = _project()

    def test_widget_edsui_is_pretty_json_of_to_dict(self):
        text = widget_edsui(self.card)
        self.assertEqual(json.loads(text), self.card.to_dict())
        self.assertEqual(text, json.dumps(self.card.to_dict(), indent=2) + "\n")
        self.assertTrue(text.endswith("\n"))

    def test_page_edsui_round_trips(self):
        text = page_edsui(self.page)
        page = parse_page_edsui(text, self.registry, self.project, replacing="main")
        self.assertEqual(page.to_dict(), self.page.to_dict())

    def test_widget_round_trips_and_edits_apply(self):
        text = widget_edsui(self.gauge).replace('"label": "RPM"', '"label": "Engine speed"')
        widget = parse_widget_edsui(text, self.registry, self.project, replacing="gauge1")
        self.assertEqual(widget.properties["label"], "Engine speed")
        self.assertEqual(widget.bindings["value"].tag, "engine.rpm")
        self.assertEqual(widget.geometry["width"], 200)

    def test_invalid_json_names_the_line(self):
        text = widget_edsui(self.gauge).replace('"y": 20,', '"y": 20')   # drop a comma -> line 5
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(text, self.registry)
        self.assertRegex(str(ctx.exception), r"line \d+")

    def test_unknown_type_rejected(self):
        text = widget_edsui(self.gauge).replace('"ShGauge"', '"ShNope"')
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(text, self.registry)
        self.assertIn("ShNope", str(ctx.exception))

    def test_duplicate_id_against_project_rejected(self):
        text = widget_edsui(self.gauge).replace('"gauge1"', '"card1"')
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(text, self.registry, self.project, replacing="gauge1")
        self.assertIn("card1", str(ctx.exception))

    def test_bad_identifier_rejected(self):
        text = widget_edsui(self.gauge).replace('"gauge1"', '"1 gauge"')
        with self.assertRaises(CodeError):
            parse_widget_edsui(text, self.registry, self.project, replacing="gauge1")

    def test_not_an_object_rejected(self):
        with self.assertRaises(CodeError):
            parse_widget_edsui("[1, 2]", self.registry)


class SectionTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)
        self.project, self.page, self.gauge, self.card = _project()

    def test_sections(self):
        s = section_for(self.generator, self.registry, self.project, self.page, self.gauge, "widget", "qml")
        self.assertIsInstance(s, CodeSection)
        self.assertEqual((s.scope, s.fmt, s.language, s.editable), ("widget", "qml", "qml", False))
        self.assertIn("gauge1", s.title)
        self.assertEqual(s.text, widget_qml(self.generator, self.project, self.gauge))
        s = section_for(self.generator, self.registry, self.project, self.page, self.gauge, "widget", "edsui")
        self.assertEqual((s.language, s.editable), ("json", True))
        s = section_for(self.generator, self.registry, self.project, self.page, None, "page", "qml")
        self.assertIn("Main", s.title)
        self.assertEqual(s.text, page_qml(self.generator, self.project, self.page))
        s = section_for(self.generator, self.registry, self.project, self.page, None, "page", "edsui")
        self.assertEqual(s.text, page_edsui(self.page))

    def test_nothing_selected(self):
        s = section_for(self.generator, self.registry, self.project, self.page, None, "widget", "qml")
        self.assertFalse(s.editable)
        self.assertEqual(len(s.text.strip().splitlines()), 1)
        self.assertTrue(s.text.lstrip().startswith("//"))
        s = section_for(self.generator, self.registry, self.project, self.page, None, "widget", "edsui")
        self.assertFalse(s.editable)

    def test_bad_scope(self):
        with self.assertRaises(ValueError):
            section_for(self.generator, self.registry, self.project, self.page, None, "screen", "qml")


if __name__ == "__main__":
    unittest.main()
