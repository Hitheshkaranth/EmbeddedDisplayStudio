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
        self.assertEqual(self.registry.categories(), ("Basic", "Industrial", "Containers", "Navigation"))
        self.assertEqual(self.registry.get("ShValueTile").qml_component, "ShValueTile")
        self.assertGreaterEqual(len(self.registry.definitions()), 16)

    def test_generates_existing_control_and_bus_binding(self):
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "ShValueTile", "inputVoltage", {"x": 40, "y": 60, "width": 220, "height": 110},
            {"title": "Input Voltage", "unit": "V"}, {"value": DesignerBinding("power.input_voltage")}))
        qml = self.generator.generate(project)["Main.qml"]
        self.assertIn("ShValueTile {", qml)
        self.assertIn('label: "Input Voltage"', qml)
        self.assertIn('value: Bus.value("power.input_voltage", 0)', qml)

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
            self.assertEqual({os.path.basename(path) for path in paths}, {"DesignerTestMain.qml", "DesignerTestSettings.qml"})
        finally:
            for path in paths:
                if os.path.exists(path):
                    os.remove(path)


if __name__ == "__main__":
    unittest.main()
