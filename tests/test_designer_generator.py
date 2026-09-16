import os
import unittest

from designer.generators import QmlGenerationError, QmlGenerator
from designer.model import DesignerBinding, DesignerProject, DesignerWidget
from designer.palette import default_registry


class DesignerGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)

    def test_registry_has_requested_categories_and_controls(self):
        self.assertEqual(self.registry.categories(),
                         ("Basic", "Industrial", "Avionics", "Automotive", "Containers", "Navigation"))
        self.assertEqual(self.registry.get("ShValueTile").qml_component, "ShValueTile")
        self.assertGreaterEqual(len(self.registry.definitions()), 16)

    def test_every_widget_has_individual_visibility_and_opacity_controls(self):
        for definition in self.registry.definitions():
            with self.subTest(widget=definition.type):
                self.assertIs(definition.properties["visible"], bool)
                self.assertIs(definition.properties["opacity"], float)

    def test_registry_describes_color_asset_and_choice_editors(self):
        button = self.registry.get("ShButton")
        self.assertIn("backgroundColor", button.color_properties)
        self.assertIn("textColor", button.color_properties)
        self.assertIn("variant", button.choices)
        image = self.registry.get("Image")
        self.assertEqual(image.asset_properties, ("source",))
        self.assertIn("fillMode", image.choices)

    def test_generates_widget_specific_styling(self):
        project = DesignerProject()
        project.pages[0].widgets.extend([
            DesignerWidget("ShButton", "startButton", {"x": 0, "y": 0, "width": 120, "height": 40},
                           {"text": "START", "backgroundColor": "#00875a", "textColor": "#ffffff",
                            "cornerRadius": 8}),
            DesignerWidget("Rectangle", "panel", {"x": 0, "y": 50, "width": 120, "height": 80},
                           {"color": "#101418", "borderColor": "#3b82f6", "borderWidth": 2}),
            DesignerWidget("Text", "heading", {"x": 0, "y": 140, "width": 120, "height": 30},
                           {"text": "Power", "bold": True, "wrapMode": "Text.WordWrap"}),
        ])
        qml = self.generator.generate(project)["Main.qml"]
        self.assertIn('backgroundColor: "#00875a"', qml)
        self.assertIn('textColor: "#ffffff"', qml)
        self.assertIn('border.color: "#3b82f6"', qml)
        self.assertIn("font.bold: true", qml)
        self.assertIn("wrapMode: Text.WordWrap", qml)

    def test_generates_existing_control_and_bus_binding(self):
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "ShValueTile", "inputVoltage", {"x": 40, "y": 60, "width": 220, "height": 110},
            {"title": "Input Voltage", "unit": "V"}, {"value": DesignerBinding("power.input_voltage")}))
        qml = self.generator.generate(project)["Main.qml"]
        self.assertIn("ShValueTile {", qml)
        self.assertIn('label: "Input Voltage"', qml)
        self.assertIn('value: Bus.value("power.input_voltage", 0)', qml)

    def test_select_options_and_legacy_toggle_labels_generate_valid_properties(self):
        project = DesignerProject()
        project.pages[0].widgets.extend([
            DesignerWidget(
                "ShSelect", "modeSelect",
                {"x": 0, "y": 0, "width": 200, "height": 56},
                {"options": "Auto, Manual, , Service", "currentIndex": 1},
            ),
            DesignerWidget(
                "ShToggle", "modeToggle",
                {"x": 0, "y": 64, "width": 160, "height": 40},
                {"onLabel": "RUN", "offLabel": "STOP"},
            ),
        ])
        qml = self.generator.generate(project)["Main.qml"]
        self.assertIn('model:["Auto","Manual","Service"]', qml.replace(" ", ""))
        self.assertIn('onText: "RUN"', qml)
        self.assertIn('offText: "STOP"', qml)
        self.assertNotIn("onLabel:", qml)

    def test_rejects_duplicate_ids_before_generation(self):
        project = DesignerProject()
        for kind in ("Text", "ShButton"):
            project.pages[0].widgets.append(DesignerWidget(kind, "same", {"x": 0, "y": 0, "width": 10, "height": 10}))
        with self.assertRaises(QmlGenerationError):
            self.generator.generate(project)

    def test_writes_all_pages(self):
        project = DesignerProject()
        project.pages[0].name = "DesignerTestMain"
        project.pages.append(type(project.pages[0])("settings", "DesignerTestSettings"))
        paths = []
        try:
            paths = self.generator.write(project, ".tmp")
            # A multi-page design gains a host, and it comes first because the
            # workspace makes paths[0] the manifest entry.
            self.assertEqual([os.path.basename(path) for path in paths],
                             ["App.qml", "DesignerTestMain.qml", "DesignerTestSettings.qml"])
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()


class UnknownPropertyTests(unittest.TestCase):
    """A property the registry does not declare never reaches the QML.

    An AI design shipped ``ShStatDot { color: ..., active: true }``; the
    panel answered "Cannot assign to non-existent property" and rolled the
    release back. The key is dropped at import and, for a hand-edited
    project, again at generation.
    """

    def test_generator_drops_undeclared_properties(self):
        from designer.model import DesignerProject, DesignerWidget
        from designer.palette import default_registry
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "ShStatDot", "dot", {"x": 0, "y": 0, "width": 20, "height": 20},
            {"state": "ok", "color": "#22a8ff", "active": True}))
        qml = QmlGenerator(default_registry()).generate(project)["Main.qml"]
        self.assertIn('state: "ok"', qml)
        self.assertNotIn("active:", qml)
        self.assertNotIn("color: \"#22a8ff\"", qml)

    def test_ai_import_drops_undeclared_properties(self):
        from designer.palette import default_registry
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        text = ('```json\n{"name": "x", "pages": [{"id": "main", "name": "Main", "widgets": ['
                '{"type": "StatusDot", "id": "dot", "geometry": {"x": 0, "y": 0, "width": 20, "height": 20}, '
                '"properties": {"state": "ok", "color": "#22a8ff", "active": true}}]}]}\n```')
        project = AIDesignGenerator(default_registry()).generate(text, 1280, 800)
        widget = project.pages[0].widgets[0]
        self.assertEqual(widget.type, "ShStatDot")
        self.assertEqual(set(widget.properties), {"state"})

    def test_enum_spellings_are_mapped_or_dropped(self):
        from designer.model import DesignerProject, DesignerWidget
        from designer.palette import default_registry
        from tools.hmi_deployer.ai_generator import _coerce_choices
        text = default_registry().get("Text")
        self.assertEqual(_coerce_choices(text, {"horizontalAlignment": "TextRight"}),
                         {"horizontalAlignment": "Text.AlignRight"})
        self.assertEqual(_coerce_choices(text, {"horizontalAlignment": "banana"}), {})
        # A hand-edited project with a bad enum still generates loadable QML.
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "Text", "t", {"x": 0, "y": 0, "width": 100, "height": 20},
            {"text": "x", "horizontalAlignment": "TextRight"}))
        qml = QmlGenerator(default_registry()).generate(project)["Main.qml"]
        self.assertNotIn("TextRight", qml)
