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


# ---------------------------------------------------------------- W1 extras
# Everything below is W1's own; the frozen minimum ends above.

class ParseValidationTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.project, self.page, self.gauge, self.card = _project()

    def test_error_line_is_the_broken_line(self):
        text = widget_edsui(self.gauge).replace('"y": 20,', '"y": 20')
        broken = next(index for index, line in enumerate(text.splitlines(), 1) if '"y": 20' in line)
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(text, self.registry)
        # The missing comma is noticed on the line after it.
        self.assertRegex(str(ctx.exception), rf"^line {broken + 1}: ")

    def test_missing_type_and_id_rejected(self):
        data = self.gauge.to_dict()
        for key in ("type", "id"):
            broken = dict(data)
            del broken[key]
            with self.assertRaises(CodeError) as ctx:
                parse_widget_edsui(json.dumps(broken), self.registry)
            self.assertIn(key, str(ctx.exception))
            broken[key] = 7
            with self.assertRaises(CodeError):
                parse_widget_edsui(json.dumps(broken), self.registry)

    def test_geometry_must_be_numbers(self):
        data = self.gauge.to_dict()
        data["geometry"]["width"] = "200"
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(json.dumps(data), self.registry)
        self.assertIn("width", str(ctx.exception))
        data["geometry"]["width"] = True          # a bool is an int to Python, not to a designer
        with self.assertRaises(CodeError):
            parse_widget_edsui(json.dumps(data), self.registry)
        data["geometry"] = [1, 2, 3]
        with self.assertRaises(CodeError):
            parse_widget_edsui(json.dumps(data), self.registry)

    def test_float_geometry_accepted(self):
        data = self.gauge.to_dict()
        data["geometry"]["x"] = 10.5
        widget = parse_widget_edsui(json.dumps(data), self.registry)
        self.assertEqual(widget.geometry["x"], 10.5)

    def test_children_are_validated_and_errors_name_the_path(self):
        data = self.card.to_dict()
        data["children"][0]["type"] = "ShNope"
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(json.dumps(data), self.registry)
        self.assertIn("ShNope", str(ctx.exception))
        self.assertIn("children[0]", str(ctx.exception))
        data = self.card.to_dict()
        data["children"][0]["id"] = "card1"       # clashes with its own parent
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(json.dumps(data), self.registry)
        self.assertIn('duplicate id "card1"', str(ctx.exception))

    def test_replacing_excludes_the_old_subtree(self):
        # Re-applying card1 keeps its child's id text1: not a clash with itself.
        widget = parse_widget_edsui(widget_edsui(self.card), self.registry, self.project, replacing="card1")
        self.assertEqual([c.id for c in widget.children], ["text1"])
        # The same text applied as a *new* widget clashes on both ids.
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(widget_edsui(self.card), self.registry, self.project)
        self.assertIn("card1", str(ctx.exception))
        # A child id that lives elsewhere in the project is a clash.
        data = self.card.to_dict()
        data["children"][0]["id"] = "gauge1"
        with self.assertRaises(CodeError) as ctx:
            parse_widget_edsui(json.dumps(data), self.registry, self.project, replacing="card1")
        self.assertIn("gauge1", str(ctx.exception))

    def test_without_project_only_the_fragment_is_checked(self):
        text = widget_edsui(self.gauge).replace('"gauge1"', '"card1"')
        widget = parse_widget_edsui(text, self.registry)
        self.assertEqual(widget.id, "card1")

    def test_invalid_binding_is_a_code_error(self):
        data = self.gauge.to_dict()
        data["bindings"]["value"] = 42            # neither a tag string nor an object
        with self.assertRaises(CodeError):
            parse_widget_edsui(json.dumps(data), self.registry)
        data["bindings"]["value"] = {"tag": "engine.rpm", "multiplier": "abc"}
        with self.assertRaises(CodeError):
            parse_widget_edsui(json.dumps(data), self.registry)

    def test_actions_round_trip(self):
        data = self.gauge.to_dict()
        data["actions"] = {"clicked": {"kind": "pulse", "tag": "engine.reset", "ms": 500}}
        widget = parse_widget_edsui(json.dumps(data), self.registry, self.project, replacing="gauge1")
        self.assertEqual(widget.actions["clicked"].kind, "pulse")
        self.assertEqual(widget.actions["clicked"].ms, 500)
        self.assertEqual(json.loads(widget_edsui(widget))["actions"], data["actions"])

    def test_non_ascii_text_is_kept_readable(self):
        self.gauge.properties["label"] = "Temp °C"
        text = widget_edsui(self.gauge)
        self.assertIn("Temp °C", text)
        self.assertEqual(parse_widget_edsui(text, self.registry).properties["label"], "Temp °C")


class ParsePageTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.project, self.page, self.gauge, self.card = _project()

    def test_page_edsui_matches_the_project_file(self):
        self.assertEqual(json.loads(page_edsui(self.page)), self.project.to_dict()["pages"][0])
        self.assertEqual(list(json.loads(page_edsui(self.page))), ["id", "name", "widgets"])

    def test_page_id_and_name_must_be_strings(self):
        data = json.loads(page_edsui(self.page))
        for key in ("id", "name"):
            broken = dict(data)
            broken[key] = 3
            with self.assertRaises(CodeError) as ctx:
                parse_page_edsui(json.dumps(broken), self.registry)
            self.assertIn(key, str(ctx.exception))
            del broken[key]
            with self.assertRaises(CodeError):
                parse_page_edsui(json.dumps(broken), self.registry)

    def test_page_widgets_validated_with_path(self):
        data = json.loads(page_edsui(self.page))
        data["widgets"][1]["children"][0]["id"] = "gauge1"
        with self.assertRaises(CodeError) as ctx:
            parse_page_edsui(json.dumps(data), self.registry)
        self.assertIn('duplicate id "gauge1"', str(ctx.exception))
        self.assertIn("widgets[1].children[0]", str(ctx.exception))
        data["widgets"] = {"not": "a list"}
        with self.assertRaises(CodeError):
            parse_page_edsui(json.dumps(data), self.registry)

    def test_page_ids_checked_against_other_pages_only(self):
        other = DesignerPage("second", "Second", widgets=[
            DesignerWidget(type="Text", id="banner", geometry={"x": 0, "y": 0, "width": 50, "height": 20})])
        self.project.pages.append(other)
        # Re-applying "main" is fine: its own ids are excluded.
        page = parse_page_edsui(page_edsui(self.page), self.registry, self.project, replacing="main")
        self.assertEqual(page.id, "main")
        # An id from the other page is a clash.
        text = page_edsui(self.page).replace('"gauge1"', '"banner"')
        with self.assertRaises(CodeError) as ctx:
            parse_page_edsui(text, self.registry, self.project, replacing="main")
        self.assertIn("banner", str(ctx.exception))
        # Without `replacing` the page's own ids clash with the project's copy.
        with self.assertRaises(CodeError):
            parse_page_edsui(page_edsui(self.page), self.registry, self.project)

    def test_page_edits_apply(self):
        text = page_edsui(self.page).replace('"name": "Main"', '"name": "Overview"').replace('"text": "hello"', '"text": "bye"')
        page = parse_page_edsui(text, self.registry, self.project, replacing="main")
        self.assertEqual(page.name, "Overview")
        self.assertEqual(page.widgets[1].children[0].properties["text"], "bye")
        self.assertEqual(page.widgets[0].bindings["value"].tag, "engine.rpm")

    def test_empty_page_round_trips(self):
        empty = DesignerPage("blank", "Blank")
        page = parse_page_edsui(page_edsui(empty), self.registry, self.project)
        self.assertEqual(page.to_dict(), empty.to_dict())


class SectionDetailTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)
        self.project, self.page, self.gauge, self.card = _project()

    def test_titles(self):
        args = (self.generator, self.registry, self.project, self.page)
        self.assertEqual(section_for(*args, self.gauge, "widget", "qml").title, "gauge1 (ShGauge) -- generated QML")
        self.assertEqual(section_for(*args, self.gauge, "widget", "edsui").title, "gauge1 (ShGauge) -- design JSON")
        self.assertEqual(section_for(*args, None, "page", "qml").title, 'Page "Main" -- generated QML')
        self.assertEqual(section_for(*args, None, "page", "edsui").title, 'Page "Main" -- design JSON')

    def test_page_scope_ignores_the_selected_widget(self):
        args = (self.generator, self.registry, self.project, self.page)
        self.assertEqual(section_for(*args, self.gauge, "page", "qml").text, page_qml(self.generator, self.project, self.page))
        s = section_for(*args, self.gauge, "page", "edsui")
        self.assertEqual((s.scope, s.fmt, s.language, s.editable), ("page", "edsui", "json", True))

    def test_widget_edsui_section_is_parseable(self):
        s = section_for(self.generator, self.registry, self.project, self.page, self.card, "widget", "edsui")
        widget = parse_widget_edsui(s.text, self.registry, self.project, replacing="card1")
        self.assertEqual(widget.to_dict(), self.card.to_dict())

    def test_nothing_selected_texts(self):
        args = (self.generator, self.registry, self.project, self.page, None, "widget")
        qml = section_for(*args, "qml")
        edsui = section_for(*args, "edsui")
        self.assertEqual(qml.text, "// Select a widget on the canvas to see its code\n")
        self.assertEqual(edsui.text, "// Select a widget on the canvas to see its design JSON\n")
        self.assertEqual((qml.language, edsui.language), ("qml", "json"))
        self.assertEqual((qml.scope, qml.fmt, edsui.scope, edsui.fmt), ("widget", "qml", "widget", "edsui"))

    def test_bad_format(self):
        with self.assertRaises(ValueError):
            section_for(self.generator, self.registry, self.project, self.page, self.gauge, "widget", "yaml")

    def test_widget_qml_snippet_shape(self):
        text = widget_qml(self.generator, self.project, self.card)
        self.assertTrue(text.startswith("ShCard {\n"))     # no leading blank line, depth 0
        self.assertTrue(text.endswith("\n}\n"))
        self.assertEqual(text.count("\n\n"), 1)            # the one blank the generator puts before a child
        # The snippet is the page file's block, one indent level shallower.
        page_text = page_qml(self.generator, self.project, self.page)
        for line in text.splitlines():
            self.assertIn("    " + line if line else line, page_text.splitlines())


if __name__ == "__main__":
    unittest.main()
