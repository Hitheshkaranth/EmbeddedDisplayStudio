"""Wave 5 B1 gate -- AI Design that cannot come back broken, and screens
whose sample values agree with each other.

* Structured output: a plan request carries the plan's JSON schema in the
  form each provider understands, so the reply cannot be malformed JSON.
* plan_shortfall: an empty or gutted reply is recognised (the tab retries).
* coherent_samples: a generated design's sample values come from the bench
  simulator at one instant, so the canvas never shows a next station the
  station line disagrees with.
* static_readings: Deploy's readiness warns about readings with no tag.
* layout families: the cab layout is one registered family among others.
FROZEN (skeleton).
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_layout_cab import PLAN as CAB_PLAN, _reply  # noqa: E402


def _generator():
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator()


class StructuredOutput(unittest.TestCase):
    def test_each_provider_gets_its_own_form(self):
        from tools.hmi_deployer.ai_design import structured_output
        from tools.hmi_deployer.ai_generator import PLAN_SCHEMA
        self.assertEqual(structured_output("vllm", PLAN_SCHEMA), {"guided_json": PLAN_SCHEMA})
        openai = structured_output("openai", PLAN_SCHEMA)
        self.assertEqual(openai["response_format"]["type"], "json_schema")
        self.assertIs(openai["response_format"]["json_schema"]["schema"], PLAN_SCHEMA)
        self.assertEqual(structured_output("ollama", PLAN_SCHEMA), {"format": PLAN_SCHEMA})
        self.assertEqual(structured_output("anthropic", PLAN_SCHEMA), {})
        self.assertEqual(structured_output("vllm", None), {})

    def test_the_schema_describes_a_plan(self):
        from tools.hmi_deployer.ai_generator import PLAN_SCHEMA
        self.assertEqual(PLAN_SCHEMA["type"], "object")
        self.assertIn("pages", PLAN_SCHEMA["required"])
        page = PLAN_SCHEMA["properties"]["pages"]["items"]
        self.assertIn("sections", page["properties"])
        self.assertIn("header", page["properties"])
        widget = page["properties"]["sections"]["items"]["properties"]["widgets"]["items"]
        self.assertIn("type", widget["required"])
        json.dumps(PLAN_SCHEMA)                                # serialisable

    def test_a_plan_request_sends_the_schema(self):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig
        from tools.hmi_deployer.ai_generator import PLAN_SCHEMA
        conn = ODConnector(mode="byok", byok=ProviderConfig(provider="vllm", model="m", baseUrl="http://x"))
        conn.response_schema = PLAN_SCHEMA
        url, headers, payload = conn.byok_request("brief")
        self.assertTrue(url.endswith("/v1/chat/completions"))
        self.assertEqual(payload["guided_json"], PLAN_SCHEMA)
        conn.response_schema = None
        _url, _headers, payload = conn.byok_request("brief")
        self.assertNotIn("guided_json", payload)


class Shortfall(unittest.TestCase):
    def test_an_empty_or_gutted_reply_is_named(self):
        from designer.model import DesignerProject
        from tools.hmi_deployer.ai_generator import plan_shortfall
        gen = _generator()
        full = gen.generate(_reply(CAB_PLAN), 1024, 768)
        self.assertEqual(plan_shortfall(full), "")
        empty = DesignerProject.from_dict({"version": 1, "name": "x", "screen": {"width": 1024, "height": 768},
                                           "pages": [{"id": "main", "name": "Main", "widgets": []}]})
        self.assertIn("no widgets", plan_shortfall(empty))
        small = copy.deepcopy(CAB_PLAN)
        small["pages"][0]["sections"] = small["pages"][0]["sections"][:1]
        thin = gen.generate(_reply(small), 1024, 768)
        reason = plan_shortfall(thin, previous=full)
        self.assertIn("dropped", reason)


class CoherentSamples(unittest.TestCase):
    def test_samples_are_one_moment_of_the_journey(self):
        from daemon import tagsim
        from designer.layout.samples import SAMPLE_T, coherent_samples
        gen = _generator()
        project = gen.generate(_reply(CAB_PLAN), 1024, 768)
        widgets = {w.id: w for p in project.pages for w in p.walk()}
        stations = [s.strip() for s in widgets["stationLine"].properties["stations"].split(",")]
        moment = tagsim.journey_at(SAMPLE_T, stations)
        # The generator already applied them ...
        self.assertEqual(widgets["nextStation"].properties["text"], moment["rail_next"])
        self.assertEqual(widgets["eta"].properties["text"], moment["rail_eta"])
        self.assertEqual(widgets["distance"].properties["text"], moment["rail_distance"])
        self.assertAlmostEqual(float(widgets["speedArc"].properties["value"]), moment["rail_speed"], places=1)
        self.assertEqual(widgets["stationLine"].properties["details"], moment["rail_details"])
        # ... and doing it again changes nothing.
        self.assertEqual(coherent_samples(project, SAMPLE_T), 0)

    def test_a_flight_gets_one_moment_of_the_flight(self):
        from designer.layout.samples import coherent_samples
        from designer.model import DesignerProject
        project = DesignerProject.from_dict({"version": 1, "name": "x", "screen": {"width": 800, "height": 480},
            "pages": [{"id": "main", "name": "Main", "widgets": [
                {"type": "ShTape", "id": "alt", "geometry": {"x": 0, "y": 0, "width": 80, "height": 300},
                 "properties": {"value": 0, "minimumValue": 0, "maximumValue": 40000},
                 "bindings": {"value": {"tag": "nav.altitude"}}}]}]})
        self.assertEqual(coherent_samples(project, 120.0), 1)
        self.assertGreater(project.pages[0].widgets[0].properties["value"], 0)


class StaticReadings(unittest.TestCase):
    def test_readings_without_a_tag_are_warned_about(self):
        from designer.model import DesignerProject
        from tools.hmi_deployer.readiness_core import audit_readiness, static_readings
        project = DesignerProject.from_dict({"version": 1, "name": "x", "screen": {"width": 800, "height": 480},
            "pages": [{"id": "main", "name": "Main", "widgets": [
                {"type": "ShGauge", "id": "bound", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
                 "properties": {"value": 5}, "bindings": {"value": {"tag": "ai.p"}}},
                {"type": "ShGauge", "id": "loose", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
                 "properties": {"value": 5}},
                {"type": "Text", "id": "label", "geometry": {"x": 0, "y": 0, "width": 100, "height": 20},
                 "properties": {"text": "Pressure"}}]}]})
        self.assertEqual(static_readings(project), ["loose"])         # a label is not a reading
        items = audit_readiness(True, {"tags_required": ["ai.p"]}, True, None, project=project)
        tags = [i for i in items if i.name == "Tags"][0]
        self.assertEqual(tags.severity, "warning")
        self.assertIn("1", tags.detail)
        self.assertEqual(len(audit_readiness(True, {"tags_required": ["ai.p"]}, True, None)), 4)


class LayoutFamilies(unittest.TestCase):
    def test_cab_is_a_registered_family_and_others_can_join(self):
        from designer.layout import families
        self.assertIn("cab display", families.names())
        calls = []

        def applies(sections, header, width, height):
            return any(w.type == "ShGauge" for s in sections for w in s.widgets) and width < 500

        def compile_(project, page, registry, sections, title, header, report, width, height):
            calls.append(title)
            report.layout = "tiny"
            page.widgets[:] = [w for s in sections for w in s.widgets]
            return report

        families.register("tiny", applies, compile_)
        self.addCleanup(families.unregister, "tiny")
        gen = _generator()
        plan = {"name": "t", "pages": [{"id": "main", "name": "Main", "title": "T", "sections": [
            {"title": "A", "role": "hero", "widgets": [{"type": "ShGauge", "id": "g", "properties": {"value": 3}}]}]}]}
        gen.generate(_reply(plan), 400, 300)
        self.assertEqual(calls, ["T"])
        self.assertEqual(gen.last_compile[0].layout, "tiny")
        gen.generate(_reply(plan), 1024, 768)                  # too wide: the search, not "tiny"
        self.assertNotEqual(gen.last_compile[0].layout, "tiny")


if __name__ == "__main__":
    unittest.main()
