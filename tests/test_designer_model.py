import json
import os
import unittest

from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget
from designer.palette import default_registry


class DesignerModelTests(unittest.TestCase):
    def _project(self):
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "ShValueTile", "inputVoltage", {"x": 40, "y": 60, "width": 220, "height": 110},
            {"title": "Input Voltage", "unit": "V", "value": 0.0},
            {"value": DesignerBinding("power.input_voltage", "%.1f")},
        ))
        return project

    def test_round_trip_human_readable_json(self):
        project = self._project()
        path = os.path.join(".tmp", "designer-model-test.edsui")
        try:
            project.save(path)
            loaded = DesignerProject.load(path)
            self.assertEqual(loaded.to_dict(), project.to_dict())
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["version"], 1)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_unique_and_invalid_widget_ids(self):
        project = self._project()
        self.assertEqual(project.unique_id("inputVoltage"), "inputVoltage2")
        project.pages[0].widgets.append(DesignerWidget(
            "ShButton", "1 bad", {"x": 0, "y": 0, "width": 10, "height": 10}))
        self.assertTrue(any("invalid QML id" in str(issue) for issue in project.validate(default_registry())))

    def test_duplicate_ids(self):
        project = self._project()
        project.pages.append(DesignerPage("other", "Other", [DesignerWidget(
            "ShButton", "inputVoltage", {"x": 0, "y": 0, "width": 20, "height": 20})]))
        self.assertTrue(any("duplicate widget id" in str(issue) for issue in project.validate(default_registry())))

    def test_required_tags_are_deduplicated(self):
        project = self._project()
        self.assertEqual(project.required_tags(), ["power.input_voltage"])

    def test_asset_path_validation(self):
        project = DesignerProject()
        project.pages[0].widgets.append(DesignerWidget(
            "Image", "logo", {"x": 0, "y": 0, "width": 20, "height": 20}, {"source": "C:/private/logo.png"}))
        self.assertTrue(any("project-relative" in str(issue) for issue in project.validate(default_registry())))


if __name__ == "__main__":
    unittest.main()
