"""Tests for the AI generator and connector."""
import json
import unittest
import re


class TestAIDesignGenerator(unittest.TestCase):
    """Tests for AIDesignGenerator._convert_widgets and _build_project."""

    def test_malformed_geometry_from_the_model_does_not_fail_the_design(self):
        """null geometry, null/"12px"/"auto" values and non-object entries
        used to raise out of the conversion (or later out of layout)."""
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        widgets = gen._convert_widgets([
            "oops", None,
            {"type": "ShButton", "geometry": None},
            {"type": "ShButton", "geometry": {"x": None, "y": "12px", "width": 80.0, "height": "auto"}},
        ])
        self.assertEqual(len(widgets), 2)
        # Missing values take the usual cascade default for the entry's slot.
        self.assertEqual(widgets[0].geometry, {"x": 40, "y": 40, "width": 140, "height": 40})
        self.assertEqual(widgets[1].geometry, {"x": 60, "y": 12, "width": 80, "height": 40})

    def test_convert_simple_button(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator, _AI_TYPE_ALIASES
        gen = AIDesignGenerator()
        widgets = gen._convert_widgets([{"type": "Button", "geometry": {"x": 10, "y": 20, "width": 120, "height": 40}, "properties": {"text": "Start"}}])
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0].type, "ShButton")
        self.assertEqual(widgets[0].properties.get("text"), "Start")

    def test_model_written_tags_are_brought_to_contract_form(self):
        """Qwen wrote "do.pumpA.run" despite the prompt; the Designer then
        refused the design and the daemon would never answer to it."""
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        from designer.model.project import TAG_RE
        gen = AIDesignGenerator()
        widgets = gen._convert_widgets([
            {"type": "ShToggle", "id": "pumpA_runToggle",
             "geometry": {"x": 0, "y": 0, "width": 200, "height": 45},
             "actions": {"toggled": {"kind": "write", "tag": "do.pumpA.run", "value": True}}},
            {"type": "ShGauge", "id": "g",
             "geometry": {"x": 0, "y": 60, "width": 200, "height": 200},
             "bindings": {"value": {"tag": "PumpA.Flow Rate"}}},
            {"type": "ShAlarmTable", "id": "alarms",
             "geometry": {"x": 0, "y": 280, "width": 400, "height": 200},
             "bindings": {"alarms": {"tag": "*"}}},
        ])
        by_id = {w.id: w for w in widgets}
        self.assertEqual(by_id["pumpA_runToggle"].actions["toggled"].tag, "do.pumpa.run")
        self.assertEqual(by_id["g"].bindings["value"].tag, "pumpa.flow_rate")
        self.assertTrue(TAG_RE.fullmatch(by_id["g"].bindings["value"].tag))
        self.assertEqual(by_id["alarms"].bindings["alarms"].tag, "*")
        # The widget id is a QML id, not a tag: camelCase stays.
        self.assertIn("pumpA_runToggle", by_id)

    def test_a_binding_on_the_wrong_property_moves_to_the_only_one_there_is(self):
        """The model bound ShAlarmTable "data"; the table takes "alarms"."""
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        table, lamp = gen._convert_widgets([
            {"type": "ShAlarmTable", "id": "alarms",
             "geometry": {"x": 0, "y": 0, "width": 400, "height": 200},
             "bindings": {"data": {"tag": "*"}}},
            {"type": "ShAnnunciator", "id": "lamp",
             "geometry": {"x": 0, "y": 220, "width": 175, "height": 48},
             "bindings": {"value": {"tag": "di.fault", "critical": "> 3"}}},
        ])
        self.assertEqual(list(table.bindings), ["alarms"])
        # Two bindable properties (lit, severity): no single guess to make.
        # The threshold binding stays where the model put it and drives both.
        self.assertEqual(list(lamp.bindings), ["value"])

    def test_an_action_on_a_signal_the_widget_lacks_is_dropped(self):
        """ShAlert "clicked": the alert cannot fire it, and validation then
        refused the whole design at deploy."""
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        alert, button = AIDesignGenerator()._convert_widgets([
            {"type": "ShAlert", "id": "engineAlert",
             "geometry": {"x": 0, "y": 0, "width": 300, "height": 60},
             "actions": {"clicked": {"kind": "navigate", "page": "alarms"}}},
            {"type": "ShButton", "id": "start",
             "geometry": {"x": 0, "y": 80, "width": 120, "height": 48},
             "actions": {"clicked": {"kind": "write", "tag": "do.start"}}},
        ])
        self.assertEqual(alert.actions, {})
        self.assertEqual(list(button.actions), ["clicked"])

    def test_links_to_pages_the_design_never_made_are_dropped(self):
        from designer.model import DesignerAction, DesignerProject, DesignerWidget
        from tools.hmi_deployer.ai_generator import drop_dangling_navigation
        project = DesignerProject()
        project.pages[0].widgets = [
            DesignerWidget("ShButton", "toAlarms", {"x": 0, "y": 0, "width": 100, "height": 48}, {},
                           actions={"clicked": DesignerAction("navigate", page="alarms")}),
            DesignerWidget("ShButton", "toMain", {"x": 0, "y": 60, "width": 100, "height": 48}, {},
                           actions={"clicked": DesignerAction("navigate", page=project.pages[0].id)}),
        ]
        self.assertEqual(drop_dangling_navigation(project), ["toAlarms.clicked: no page 'alarms'"])
        widgets = {w.id: w for w in project.all_widgets()}
        self.assertEqual(widgets["toAlarms"].actions, {})
        self.assertEqual(list(widgets["toMain"].actions), ["clicked"])

    def test_merged_sections_are_laid_out_together(self):
        """Each section was composed alone and their heroes shared a slot."""
        import copy
        from designer.model import DesignerProject, DesignerWidget
        from tools.hmi_deployer.ai_generator import AIDesignGenerator, merge_project_section

        def section(ids):
            project = DesignerProject()
            project.screen.width, project.screen.height = 1024, 768
            project.pages[0].widgets = [
                DesignerWidget("ShGauge", wid, {"x": 312, "y": 184, "width": 400, "height": 400}, {})
                for wid in ids]
            return project

        merged = merge_project_section(section(["rpm"]), section(["coolant"]))
        merged = merge_project_section(merged, section(["oil"]))
        gen = AIDesignGenerator()
        gen.brief = "engine dashboard"
        composed = gen.compose(copy.deepcopy(merged))
        boxes = [w.geometry for w in composed.pages[0].widgets]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                overlap_x = min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])
                overlap_y = min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"])
                self.assertFalse(overlap_x > 0 and overlap_y > 0, (a, b))

    def test_the_brief_resolution_is_read_when_it_names_one(self):
        from tools.hmi_deployer.ai_generator import brief_resolution
        self.assertEqual(brief_resolution("a 1920×1080 avionics display"), (1920, 1080))
        self.assertEqual(brief_resolution("for the 1024 x 768 panel"), (1024, 768))
        self.assertIsNone(brief_resolution("ranges 0..100 x 5 steps"))
        self.assertIsNone(brief_resolution(""))

    def test_the_prompt_gives_a_page_budget_and_real_unit_ranges(self):
        from designer.palette.widget_registry import default_registry
        from tools.hmi_deployer.ai_generator import build_system_prompt, page_budget
        prompt = build_system_prompt(default_registry(), 1024, 768)
        self.assertIn(f"about {page_budget(1024, 768)} widgets", prompt)
        self.assertIn("never as a 0..1 fraction", prompt)
        self.assertNotIn("Qt/QML panels", prompt)
        self.assertGreater(page_budget(1920, 1080), page_budget(1024, 768))

    def test_a_later_section_corrects_a_widget_that_was_moved_to_another_page(self):
        """Composing moved "eng1status" to the Engine 1 page; the next section's
        eng1status was then added to the overview as a second widget with the
        same id, and validation refused the design."""
        from designer.model import DesignerPage, DesignerProject, DesignerWidget
        from tools.hmi_deployer.ai_generator import merge_project_section

        def lamp(kind):
            return DesignerWidget(kind, "eng1status", {"x": 0, "y": 0, "width": 40, "height": 40}, {})

        base = DesignerProject()
        base.pages[0].widgets = []
        base.pages.append(DesignerPage("engine1", "Engine 1", [lamp("ShTelltale")]))
        section = DesignerProject()
        section.pages[0].widgets = [lamp("ShStatDot")]
        merged = merge_project_section(base, section)
        holders = [(page.id, w.type) for page in merged.pages for w in page.widgets
                   if w.id == "eng1status"]
        self.assertEqual(holders, [("engine1", "ShStatDot")])

    def test_a_tag_that_cannot_be_repaired_is_left_for_validation_to_name(self):
        from tools.hmi_deployer.ai_generator import _coerce_tag
        self.assertEqual(_coerce_tag("Relay"), "Relay")   # no dot: not a guess to make
        self.assertEqual(_coerce_tag("DO.Relay1"), "do.relay1")

    def test_convert_unknown_type_falls_back_to_rectangle(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        widgets = gen._convert_widgets([{"type": "UnknownWidget", "geometry": {"x": 0, "y": 0, "width": 100, "height": 50}}])
        # Unknown types should fall back or be created with the aliased name
        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0].geometry["width"], 100)

    def test_parse_qml_to_widgets(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        qml = """
        ShButton {
            id: myButton
            x: 50
            y: 100
            width: 120
            height: 40
            text: "Click Me"
        }
        ShGauge {
            id: engineGauge
            x: 200
            y: 50
            width: 180
            height: 180
            label: "RPM"
        }
        """
        widgets = gen._parse_qml_to_widgets(qml)
        self.assertGreater(len(widgets), 0)
        ids = [w.id for w in widgets]
        self.assertIn("myButton", ids)
        self.assertIn("engineGauge", ids)

    def test_parse_widget_descriptions(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        text = "Create a Button with text 'Start' and add a Gauge for engine speed with value 85"
        widgets = gen._parse_widget_descriptions(text)
        self.assertGreater(len(widgets), 0)

    def test_build_project(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        from designer.model import DesignerWidget
        gen = AIDesignGenerator()
        widgets = [DesignerWidget(type="Rectangle", id="rect1", geometry={"x": 0, "y": 0, "width": 100, "height": 100})]
        project = gen._build_project(widgets, "Test Project", 800, 600)
        self.assertEqual(project.name, "Test Project")
        self.assertEqual(project.screen.width, 800)
        self.assertEqual(project.screen.height, 600)
        self.assertEqual(len(project.pages[0].widgets), 1)


class TestAIDesignAgent(unittest.TestCase):
    """Tests for AIDesignAgent workflow."""

    def test_generate_with_mock_connector(self):
        from tools.hmi_deployer.ai_generator import AIDesignAgent
        from tools.hmi_deployer.ai_design import ODConnector

        class MockConnector:
            mode = "byok"
            project_id = "test-project"
            conversation = []

            def is_running(self):
                return True

            def generate(self, brief):
                qml = 'ShButton {\n  id: myButton\n  x: 10\n  y: 20\n  width: 120\n  height: 40\n  text: Hello\n}'
                yield qml

            def get_provider_presets(self):
                return []

        connector = MockConnector()
        agent = AIDesignAgent(connector)
        results = list(agent.run("Create a hello button"))
        self.assertGreater(len(results), 0)
        project = agent.get_project()
        self.assertIsNotNone(project)
        self.assertGreater(len(project.pages[0].widgets), 0)


class TestODConnector(unittest.TestCase):
    """Tests for ODConnector."""

    def test_connector_defaults(self):
        from tools.hmi_deployer.ai_design import ODConnector, DEFAULT_DAEMON_HOST, DEFAULT_DAEMON_PORT
        conn = ODConnector()
        self.assertEqual(conn.host, DEFAULT_DAEMON_HOST)
        self.assertEqual(conn.port, DEFAULT_DAEMON_PORT)
        self.assertEqual(conn.mode, "daemon")
        self.assertIsNone(conn.project_id)
        self.assertEqual(len(conn.conversation), 0)

    def test_byok_config(self):
        from tools.hmi_deployer.ai_design import ODConnector, ProviderConfig, BYOK_PRESETS
        conn = ODConnector()
        preset = BYOK_PRESETS["ollama"]
        conn.mode = "byok"
        conn.byok = ProviderConfig.from_dict(preset)
        self.assertEqual(conn.mode, "byok")
        self.assertEqual(conn.byok.provider, "ollama")
        self.assertEqual(len(conn.byok.models), len(preset["models"]))

    def test_get_provider_presets(self):
        from tools.hmi_deployer.ai_design import ODConnector
        conn = ODConnector()
        presets = conn.get_provider_presets()
        keys = [p["key"] for p in presets]
        self.assertIn("ollama", keys)
        self.assertIn("openai", keys)
        self.assertIn("anthropic", keys)

    def test_connector_config_roundtrip(self):
        from tools.hmi_deployer.ai_design import ODConnector
        conn = ODConnector()
        conn.mode = "byok"
        conn.project_id = "proj-123"
        config = conn.get_config()
        conn2 = ODConnector()
        conn2.set_config(config)
        self.assertEqual(conn2.mode, "byok")
        self.assertEqual(conn2.project_id, "proj-123")


class TestAIGeneratorJSONParsing(unittest.TestCase):
    """Test JSON design payload parsing."""

    def test_from_json_design(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        design = {
            "name": "Dashboard",
            "pages": [{
                "widgets": [
                    {"type": "Button", "geometry": {"x": 10, "y": 20, "width": 120, "height": 40}, "properties": {"text": "Click"}},
                    {"type": "ShGauge", "geometry": {"x": 150, "y": 10, "width": 180, "height": 180}, "properties": {"label": "Speed"}}
                ]
            }]
        }
        project = gen._from_json_design(design, 800, 600)
        self.assertEqual(project.name, "Dashboard")
        self.assertEqual(len(project.pages[0].widgets), 2)
        self.assertEqual(project.pages[0].widgets[0].type, "ShButton")
        self.assertEqual(project.pages[0].widgets[1].type, "ShGauge")


if __name__ == "__main__":
    unittest.main()