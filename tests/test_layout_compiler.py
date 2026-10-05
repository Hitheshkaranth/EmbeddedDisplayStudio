"""tests/test_layout_compiler.py -- planned screens: intake and the layout compiler.

designer/layout/intake.py reads model output the way it was meant
(lenient JSON, property synonyms, kit icons); designer/layout/compiler.py
lays out a screen from its sections. The fixtures are shapes real model
replies took (vLLM Qwen / ornith, 2026-10-05).
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from designer.layout import intake  # noqa: E402
from designer.layout import compiler  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402


PLAN = {
    "name": "pump-station",
    "section": {"index": 1, "complete": True, "label": "", "next": ""},
    "pages": [{
        "id": "main", "name": "Pump Station", "title": "Pump Station Overview",
        "header": [{"type": "ShStatDot", "id": "pumpRunning", "properties": {"label": "Running"}}],
        "sections": [
            {"title": "Flow rate", "role": "hero", "widgets": [
                {"type": "ShClusterGauge", "id": "flowRate",
                 "properties": {"caption": "Flow", "minimumValue": 0, "maximumValue": 100,
                                "majorStep": 20, "redlineFrom": 90},
                 "bindings": {"value": {"tag": "ai.flow_main", "unit": "m3/h"}}}]},
            {"title": "Pressures", "role": "instruments", "widgets": [
                {"type": "ShGauge", "id": "suction",
                 "properties": {"label": "Suction", "minimumValue": 0, "maximumValue": 10, "unit": "bar"}},
                {"type": "ShGauge", "id": "discharge",
                 "properties": {"label": "Discharge", "minimumValue": 0, "maximumValue": 16, "unit": "bar"}}]},
            {"title": "Motor", "role": "readings", "widgets": [
                {"type": "ShValueTile", "id": "motorCurrent", "properties": {"label": "Current", "unit": "A"}},
                {"type": "ShValueTile", "id": "tankLevel", "properties": {"label": "Tank", "unit": "%"}}]},
            {"title": "Pump control", "role": "controls", "widgets": [
                {"type": "ShButton", "id": "startPump", "properties": {"text": "Start"},
                 "actions": {"clicked": {"kind": "write", "tag": "do.pump_start", "value": True}}},
                {"type": "ShButton", "id": "stopPump", "properties": {"text": "Stop"},
                 "actions": {"clicked": {"kind": "write", "tag": "do.pump_stop", "value": True}}}]},
            {"title": "Alarms", "role": "alarms", "widgets": [
                {"type": "ShAlarmTable", "id": "alarms", "bindings": {"alarms": {"tag": "*"}}}]},
        ],
    }],
}


def _reply(design) -> str:
    return "One sentence.\n\n```json\n" + json.dumps(design) + "\n```"


def _walk(widgets, ox=0, oy=0):
    for widget in widgets:
        x = ox + float(widget.geometry.get("x", 0))
        y = oy + float(widget.geometry.get("y", 0))
        yield widget, x, y
        yield from _walk(widget.children, x, y)


class LenientJsonTest(unittest.TestCase):
    def test_missing_closing_quote(self):
        text = '{"a": [{"critical": "> 95}, {"b": 1}]}'
        value = intake.loads_lenient(text)
        self.assertEqual(value["a"][0]["critical"], "> 95")

    def test_missing_properties_wrapper(self):
        # The model dropped `"properties": {` and closed the widget early.
        text = ('{"widgets": [{"type": "ShAutoReadout", "id": "m", "unit": "A"}, '
                '"bindings": {"value": {"tag": "ai.m"}}}, {"type": "ShButton", "id": "b"}]}')
        value = intake.loads_lenient(text)
        self.assertEqual([w["id"] for w in value["widgets"]], ["m", "b"])
        self.assertEqual(value["widgets"][0]["bindings"]["value"]["tag"], "ai.m")

    def test_dropped_brace_at_the_end(self):
        value = intake.loads_lenient('{"pages": [{"widgets": [{"id": "a"}]}]')
        self.assertEqual(value["pages"][0]["widgets"][0]["id"], "a")

    def test_comments_trailing_commas_python_literals(self):
        value = intake.loads_lenient('{"a": True, // note\n "b": [1, 2,], "c": None,}')
        self.assertEqual(value, {"a": True, "b": [1, 2], "c": None})

    def test_truncated_reply_keeps_complete_widgets(self):
        value = intake.loads_lenient('{"w": [{"id": "a"}, {"id": "b"}, {"id": "c", "ty')
        self.assertEqual([w["id"] for w in value["w"]], ["a", "b"])

    def test_not_json_raises(self):
        with self.assertRaises(ValueError):
            intake.loads_lenient("no json here")


class SynonymTest(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_gauge_range_spelled_like_the_cluster_gauge(self):
        props, notes = intake.normalise_properties(
            self.registry.get("ShGauge"), {"minimumValue": 0, "maximumValue": 16, "warningValue": 12})
        self.assertEqual(props["minimum"], 0)
        self.assertEqual(props["maximum"], 16)
        self.assertEqual(props["thresholdWarning"], 12)
        self.assertTrue(notes)

    def test_label_lands_in_title_on_a_value_tile(self):
        props, _notes = intake.normalise_properties(self.registry.get("ShValueTile"), {"label": "Current"})
        self.assertEqual(props["title"], "Current")

    def test_explicit_key_is_not_overwritten(self):
        props, _notes = intake.normalise_properties(
            self.registry.get("ShValueTile"), {"title": "Kept", "label": "Dropped"})
        self.assertEqual(props["title"], "Kept")

    def test_icons_map_onto_the_kit(self):
        if not intake.kit_icons():
            self.skipTest("kit icons not present")
        self.assertEqual(intake.kit_icon("thermometer"), "temperature")
        self.assertEqual(intake.kit_icon("mdi-water"), "droplet")
        self.assertEqual(intake.kit_icon("no-such-icon-anywhere"), "")


class CompilerTest(unittest.TestCase):
    def setUp(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        self.generator = AIDesignGenerator()
        self.registry = self.generator.registry

    def _compiled(self, design=PLAN, size=(1024, 768)):
        project = self.generator.generate(_reply(design), *size)
        self.assertIsNotNone(project)
        return project

    def test_planned_reply_is_compiled(self):
        self._compiled()
        self.assertTrue(self.generator.last_compile)
        self.assertTrue(self.generator.last_polish.archetype.startswith("compiled"))

    def test_every_model_widget_survives_once(self):
        project = self._compiled()
        ids = [w.id for w, _x, _y in _walk(project.pages[0].widgets)]
        self.assertEqual(len(ids), len(set(ids)))
        for wanted in ("flowRate", "suction", "discharge", "motorCurrent", "tankLevel",
                       "startPump", "stopPump", "alarms", "pumpRunning"):
            self.assertIn(wanted, ids)

    def test_cards_do_not_overlap_and_stay_on_the_glass(self):
        project = self._compiled()
        width, height = project.screen.width, project.screen.height
        tokens = compiler.tokens_for(width, height)
        cards = [w for w in project.pages[0].widgets if w.type == "ShCard"]
        self.assertEqual(len(cards), 5)
        rects = [(float(c.geometry["x"]), float(c.geometry["y"]),
                  float(c.geometry["width"]), float(c.geometry["height"])) for c in cards]
        for x, y, w, h in rects:
            self.assertGreaterEqual(x, tokens.margin - 1)
            self.assertGreaterEqual(y, tokens.margin - 1)
            self.assertLessEqual(x + w, width - tokens.margin + 1)
            self.assertLessEqual(y + h, height - tokens.margin + 1)
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                overlap_w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                overlap_h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                self.assertFalse(overlap_w > 0 and overlap_h > 0, (a, b))

    def test_widgets_sit_inside_their_card(self):
        project = self._compiled()
        for card in (w for w in project.pages[0].widgets if w.type == "ShCard"):
            for child in card.children:
                self.assertGreaterEqual(float(child.geometry["x"]), 0)
                self.assertGreaterEqual(float(child.geometry["y"]), 0)
                self.assertLessEqual(float(child.geometry["x"]) + float(child.geometry["width"]),
                                     float(card.geometry["width"]) + 1, child.id)
                self.assertLessEqual(float(child.geometry["y"]) + float(child.geometry["height"]),
                                     float(card.geometry["height"]) + 1, child.id)

    def test_hero_card_is_the_largest(self):
        project = self._compiled()
        cards = {c.id: float(c.geometry["width"]) * float(c.geometry["height"])
                 for c in project.pages[0].widgets if c.type == "ShCard"}
        hero = next(c for c in project.pages[0].widgets
                    if c.type == "ShCard" and any(ch.id == "flowRate" for ch in c.children))
        self.assertEqual(max(cards, key=cards.get), hero.id)

    def test_stop_is_destructive_and_the_bound_gauge_reads_live(self):
        project = self._compiled()
        widgets = {w.id: w for w, _x, _y in _walk(project.pages[0].widgets)}
        self.assertEqual(widgets["stopPump"].properties["variant"], "destructive")
        self.assertEqual(widgets["flowRate"].properties["readout"], "")
        self.assertEqual(widgets["flowRate"].properties["readoutUnit"], "m3/h")
        self.assertEqual(widgets["suction"].properties["minimum"], 0)

    def test_recompile_is_idempotent(self):
        project = self._compiled()
        page = project.pages[0]
        first = json.dumps(page.to_dict(), sort_keys=True)
        compiler.compile_page(project, page, self.registry)
        self.assertEqual(json.dumps(page.to_dict(), sort_keys=True), first)

    def test_geometry_reply_still_polishes_in_auto_mode(self):
        design = {"pages": [{"id": "main", "widgets": [
            {"type": "ShGauge", "id": "g", "geometry": {"x": 10, "y": 10, "width": 180, "height": 180}}]}]}
        self.generator.generate(_reply(design), 1024, 768)
        self.assertFalse(self.generator.last_compile)

    def test_compile_mode_lays_out_a_geometry_draft(self):
        design = {"pages": [{"id": "main", "widgets": [
            {"type": "Text", "id": "title", "geometry": {"x": 20, "y": 10, "width": 300, "height": 40},
             "properties": {"text": "Line 3"}},
            {"type": "ShGauge", "id": "a", "geometry": {"x": 0, "y": 0, "width": 400, "height": 400}},
            {"type": "ShGauge", "id": "b", "geometry": {"x": 0, "y": 0, "width": 180, "height": 180}},
            {"type": "ShButton", "id": "go", "geometry": {"x": 0, "y": 0, "width": 120, "height": 40},
             "properties": {"text": "Start"}}]}]}
        self.generator.layout_mode = "compile"
        project = self.generator.generate(_reply(design), 1024, 600)
        texts = [w.properties.get("text") for w, _x, _y in _walk(project.pages[0].widgets)
                 if w.type == "Text"]
        self.assertIn("Line 3", texts)
        self.assertTrue(any(w.type == "ShCard" for w in project.pages[0].widgets))

    def test_one_card_pages_are_merged_when_they_fit(self):
        design = copy.deepcopy(PLAN)
        page = design["pages"][0]
        extra = {"id": "trend", "name": "Trend", "title": "Trend",
                 "sections": [{"title": "Flow trend", "role": "trend", "widgets": [
                     {"type": "ShTrendChart", "id": "flowTrend", "bindings": {"data": {"tag": "ai.flow_main"}}}]}]}
        page["header"].append({"type": "ShButton", "id": "toTrend", "properties": {"text": "Trend"},
                               "actions": {"clicked": {"kind": "navigate", "page": "trend"}}})
        design["pages"].append(extra)
        project = self._compiled(design)
        self.assertEqual(len(project.pages), 1)
        ids = {w.id for w, _x, _y in _walk(project.pages[0].widgets)}
        self.assertIn("flowTrend", ids)
        self.assertNotIn("toTrend", ids)

    def test_variants_are_distinct_and_leave_the_page_alone(self):
        project = self._compiled()
        page = project.pages[0]
        before = json.dumps(page.to_dict(), sort_keys=True)
        variants = compiler.compile_candidates(project, page, self.registry, limit=3)
        self.assertGreaterEqual(len(variants), 2)
        self.assertEqual(len({name for _p, _c, name in variants}), len(variants))
        self.assertEqual(json.dumps(page.to_dict(), sort_keys=True), before)

    def test_too_many_cards_share(self):
        sections = [compiler.Section(f"R{i}", "readings", [object()]) for i in range(9)]
        merged = compiler._consolidate(sections, [])
        self.assertLessEqual(len(merged), compiler.MAX_SECTIONS)
        self.assertEqual(sum(len(s.widgets) for s in merged), 9)


if __name__ == "__main__":
    unittest.main()
