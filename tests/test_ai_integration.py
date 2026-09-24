"""Tests for the AI generator and connector."""
import json
import unittest
import re


class TestAIDesignGenerator(unittest.TestCase):
    """Tests for AIDesignGenerator._convert_widgets and _build_project."""

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