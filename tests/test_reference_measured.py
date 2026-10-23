"""Measured references retain image coordinates across compile/save/resize."""
import copy
import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.hmi_deployer.ai_generator import AIDesignGenerator, PLAN_SCHEMA, REFERENCE_PLAN_SCHEMA
from designer.layout.compiler import compile_page
from designer.model import DesignerProject


def plan():
    return {"name": "Measured", "theme": "light", "background": "#edf4ff", "pages": [{
        "id": "main", "title": "Must not create extra title", "reference": {
            "layout": "measured", "viewport": [100, 100, 900, 900], "width": 1600, "height": 1000},
        "header": [{"type": "Text", "id": "brand", "box": [120, 120, 320, 170],
                    "properties": {"text": "Full Brand Name", "fontSize": 20}}],
        "sections": [{"region": "center", "box": [200, 300, 800, 800], "widgets": [
            {"type": "Image", "id": "art", "box": [200, 300, 600, 700],
             "crop": [200, 300, 600, 700], "properties": {"source": "assets/art.png"}},
            {"type": "ShToggle", "id": "heater", "box": [650, 400, 750, 460],
             "properties": {"checked": True}, "bindings": {"checked": {"tag": "plant.heater"}},
             "actions": {"toggled": {"kind": "write", "tag": "plant.heater", "value": True}}},
            {"type": "Rectangle", "id": "pipe", "box": [200, 720, 600, 725],
             "properties": {"color": "#0088ff"}},
        ]}]}]}


class MeasuredReference(unittest.TestCase):
    def test_reference_decoding_requires_measurements_without_changing_legacy_schema(self):
        self.assertEqual(set(REFERENCE_PLAN_SCHEMA["required"]), {"theme", "pages"})
        page = REFERENCE_PLAN_SCHEMA["properties"]["pages"]["items"]
        self.assertIn("reference", page["required"])
        self.assertEqual(set(page["properties"]["reference"]["required"]),
                         {"layout", "viewport", "width", "height"})
        section = page["properties"]["sections"]["items"]
        for widget in (page["properties"]["header"]["items"], section["properties"]["widgets"]["items"]):
            self.assertEqual(set(widget["required"]), {"id", "type", "box"})
            box = widget["properties"]["box"]
            self.assertEqual((box["minItems"], box["maxItems"]), (4, 4))
            self.assertEqual((box["items"]["minimum"], box["items"]["maximum"]), (0, 1000))
        legacy_page = PLAN_SCHEMA["properties"]["pages"]["items"]
        self.assertNotIn("reference", legacy_page["required"])
        self.assertEqual(legacy_page["properties"]["header"]["items"]["required"], ["type"])

    def generate(self, value=None):
        return AIDesignGenerator().generate(json.dumps(value or plan()), 1024, 768)

    def test_uniform_fit_excludes_bezel_and_keeps_header_and_art(self):
        project = self.generate()
        widgets = {w.id: w for w in project.pages[0].walk()}
        self.assertEqual(set(widgets), {"brand", "art", "heater", "pipe"})
        # Content 1280x800 -> 1024x640, centered vertically at y=64.
        self.assertEqual(widgets["art"].geometry, {"x": 128, "y": 224, "width": 512, "height": 320})
        self.assertEqual(widgets["brand"].geometry["x"], 26)
        self.assertEqual(widgets["pipe"].geometry["height"], 4)
        self.assertEqual(project.screen.theme, "light")
        self.assertEqual(project.screen.background, "#edf4ff")
        self.assertEqual(widgets["brand"].properties["fontSize"], 16)
        self.assertEqual(widgets["heater"].actions["toggled"].tag, "plant.heater")

    def test_round_trip_recompile_and_resize(self):
        project = self.generate()
        original = project.to_dict()
        restored = DesignerProject.from_dict(copy.deepcopy(original))
        compile_page(restored, restored.pages[0], AIDesignGenerator().registry)
        self.assertEqual(restored.to_dict(), original)
        restored.screen.width, restored.screen.height = 1280, 800
        compile_page(restored, restored.pages[0], AIDesignGenerator().registry)
        art = next(w for w in restored.pages[0].walk() if w.id == "art")
        self.assertEqual(art.geometry, {"x": 160, "y": 200, "width": 640, "height": 400})
        brand = next(w for w in restored.pages[0].walk() if w.id == "brand")
        self.assertEqual(brand.properties["fontSize"], 20)

    def test_nested_visual_containers_keep_absolute_child_boxes(self):
        value = plan()
        value["pages"][0]["sections"][0]["widgets"] = [{
            "type": "Rectangle", "id": "card", "box": [200, 300, 800, 800],
            "properties": {"color": "#ffffff"}, "children": [{
                "type": "Text", "id": "reading", "box": [250, 350, 450, 400],
                "properties": {"text": "78.2 C", "fontSize": 20}}]}]
        project = self.generate(value)
        widgets = {w.id: w for w in project.pages[0].walk()}
        self.assertEqual(widgets["reading"].geometry["x"], 192)
        self.assertEqual(widgets["reading"].geometry["y"], 264)
        self.assertEqual(widgets["card"].children, [])

    def test_readout_colour_follows_theme_only_when_not_explicit(self):
        value = plan()
        value["pages"][0]["sections"][0]["widgets"] = [
            {"type": "ShDataField", "id": "defaultReading", "box": [200, 300, 400, 400],
             "properties": {"value": "78.2"}},
            {"type": "ShDataField", "id": "greenReading", "box": [400, 300, 600, 400],
             "properties": {"value": "72", "valueColor": "#00aa44"}}]
        project = self.generate(value)
        fields = {w.id: w for w in project.pages[0].walk()}
        from designer.layout.style import theme_colour
        self.assertEqual(fields["defaultReading"].properties["valueColor"], theme_colour(project, "foreground"))
        self.assertEqual(fields["greenReading"].properties["valueColor"], "#00aa44")

    def test_measured_readouts_never_invent_avionics_samples(self):
        value = plan()
        value["pages"][0]["sections"][0]["widgets"] = [
            {"type": "ShDataField", "id": "missing", "box": [200, 300, 400, 400],
             "bindings": {"value": {"tag": "plant.temperature"}}},
            {"type": "ShDataField", "id": "explicit", "box": [400, 300, 600, 400],
             "label": "Speed", "value": "0", "units": "KTS"}]
        fields = {w.id: w for w in self.generate(value).pages[0].walk()}
        self.assertEqual([fields["missing"].properties[k] for k in ("label", "value", "units")],
                         ["", "—", ""])
        self.assertEqual(fields["missing"].bindings["value"].tag, "plant.temperature")
        self.assertEqual([fields["explicit"].properties[k] for k in ("label", "value", "units")],
                         ["Speed", "0", "KTS"])
        from designer.layout.compiler import sections_from_plan
        legacy = {"sections": [{"widgets": [{"type": "ShDataField", "id": "legacy"}]}]}
        _, sections, _ = sections_from_plan(legacy, AIDesignGenerator()._convert_widgets)
        self.assertNotEqual(sections[0].widgets[0].properties.get("value"), "—")

    def test_navigation_pages_are_not_merged(self):
        value = plan()
        other = copy.deepcopy(value["pages"][0])
        other["id"] = "detail"
        value["pages"].append(other)
        self.assertEqual([p.id for p in self.generate(value).pages], ["main", "detail"])

    def test_percent_page_matches_thousand_coordinates_and_records_inference(self):
        value = plan()
        for index in range(4):
            value["pages"][0]["sections"][0]["widgets"].append({
                "id": f"extra{index}", "type": "Text", "box": [700, 700, 800, 800],
                "properties": {"text": str(index)}})
        percent = copy.deepcopy(value)
        def divide(item):
            if isinstance(item, dict):
                for key, val in item.items():
                    if key in ("box", "crop"):
                        item[key] = [v / 10 for v in val]
                    else:
                        divide(val)
            elif isinstance(item, list):
                for child in item:
                    divide(child)
        divide(percent)
        normal = self.generate(value)
        generator = AIDesignGenerator()
        inferred = generator.generate(json.dumps(percent), 1024, 768)
        self.assertEqual({w.id: w.geometry for w in normal.pages[0].walk()},
                         {w.id: w.geometry for w in inferred.pages[0].walk()})
        art = next(w for w in inferred.pages[0].walk() if w.id == "art")
        self.assertEqual(art.properties["_crop"], [.2, .3, .6, .7])
        self.assertIn("percent", art.properties["_reference"]["coordinateScaleInference"])
        self.assertTrue(any("percent" in n for n in generator.last_compile[0].notes))

    def test_partial_page_does_not_guess_percent_and_explicit_scale_wins(self):
        from designer.layout.compiler import measured_coordinate_scale
        page = plan()["pages"][0]
        for section in page["sections"]:
            section["box"] = [v / 10 for v in section["box"]]
            for widget in section["widgets"]:
                widget["box"] = [v / 10 for v in widget["box"]]
        self.assertEqual(measured_coordinate_scale(page), ((1000., 1000.), ""))
        page["reference"]["coordinateScale"] = 100
        self.assertEqual(measured_coordinate_scale(page), ((100., 100.), ""))

    def test_actual_mixed_percent_reply_keeps_nested_crops(self):
        from designer.layout.compiler import measured_coordinate_scale
        fixture = Path(__file__).parent / "fixtures" / "ai" / "reference_measured_percent.json"
        value = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(measured_coordinate_scale(value["pages"][0])[0], (100., 100.))
        project = self.generate(value)
        widgets = list(project.pages[0].walk())
        crops = [w.properties["_crop"] for w in widgets if "_crop" in w.properties]
        self.assertTrue(crops, "nested properties.crop must survive")
        self.assertIn([0., 0., 1., 1.], crops, "full screenshot crop must remain detectable")
        self.assertGreater(max(w.geometry["x"] + w.geometry["width"] for w in widgets), 800)
        self.assertGreater(max(w.geometry["y"] + w.geometry["height"] for w in widgets), 500)

if __name__ == "__main__":
    unittest.main()
