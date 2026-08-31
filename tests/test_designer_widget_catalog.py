"""Every palette widget must survive the whole trip: inspector, canvas, QML.

The Image widget shipped with a Browse button that could not reach a project,
and ShTabs shipped with no way to name a tab. Both were invisible from the
Python side because nothing loaded the generated QML into a real engine.
"""
import copy
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtWidgets import QApplication
from designer.canvas.designer_view import DesignerItem, DesignerScene
from designer.generators import QmlGenerator
from designer.model import DesignerProject, DesignerWidget
from designer.palette import default_registry

QML_IMPORT_PATH = Path(__file__).resolve().parent.parent / "ui" / "qml"


class WidgetCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()

    def _project_with(self, definitions):
        project = DesignerProject()
        offset = 0
        for definition in definitions:
            project.pages[0].widgets.append(DesignerWidget(
                definition.type, definition.type.lower() + "Sample",
                {"x": 0, "y": offset, "width": definition.default_width,
                 "height": definition.default_height},
                copy.deepcopy(definition.defaults)))
            offset += definition.default_height + 10
        project.screen.height = max(offset, 100)
        return project

    def test_every_widget_default_loads_in_a_real_qml_engine(self):
        project = self._project_with(self.registry.definitions())
        qml = QmlGenerator(self.registry).generate(project)["Main.qml"]
        engine = QQmlEngine()
        engine.addImportPath(str(QML_IMPORT_PATH))
        component = QQmlComponent(engine)
        component.setData(qml.encode("utf-8"), QUrl.fromLocalFile("catalog.qml"))
        self.assertEqual([error.toString() for error in component.errors()], [])
        self.assertIsNotNone(component.create())

    def test_tab_container_carries_its_tab_titles(self):
        definition = self.registry.get("ShTabs")
        self.assertIn("tabs", definition.properties)
        project = self._project_with([definition])
        project.pages[0].widgets[0].properties["tabs"] = "Overview, Alarms , "
        qml = QmlGenerator(self.registry).generate(project)["Main.qml"]
        self.assertIn('model: ["Overview", "Alarms"]', qml)
        self.assertNotIn("tabs:", qml)

    def test_text_keeps_its_color_for_the_glyphs_not_the_background(self):
        scene = DesignerScene(self.registry)
        text = DesignerWidget("Text", "heading", {"x": 0, "y": 0, "width": 100, "height": 30},
                              {"text": "Power", "color": "#f4f4f5"})
        rectangle = DesignerWidget("Rectangle", "panel", {"x": 0, "y": 0, "width": 100, "height": 30},
                                   {"color": "#f4f4f5"})
        text_item = DesignerItem(text, self.registry.get("Text"), scene)
        rectangle_item = DesignerItem(rectangle, self.registry.get("Rectangle"), scene)
        self.assertEqual(text_item.fill_color().alpha(), 0)
        self.assertEqual(rectangle_item.fill_color().name(), "#f4f4f5")

    def test_canvas_labels_use_what_the_panel_will_show(self):
        scene = DesignerScene(self.registry)
        for widget_type, properties, expected in (
            ("ShGauge", {"label": "Coolant"}, "Coolant"),
            ("ShInput", {"placeholderText": "Setpoint"}, "Setpoint"),
            ("ShValueTile", {"title": "Line Voltage"}, "Line Voltage"),
            ("ShStatDot", {}, "Status Indicator"),
        ):
            with self.subTest(widget=widget_type):
                definition = self.registry.get(widget_type)
                widget = DesignerWidget(widget_type, "sample", {"x": 0, "y": 0, "width": 10, "height": 10},
                                        properties)
                self.assertEqual(DesignerItem(widget, definition, scene).label_text(), expected)


if __name__ == "__main__":
    unittest.main()
