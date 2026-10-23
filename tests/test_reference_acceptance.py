import copy
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage
from designer.model import DesignerProject
from tools.hmi_deployer.reference_acceptance import evaluate_reference, pixel_diagnostics


def fixture():
    ocr = {"width": 400, "height": 200, "lines": [
        {"id": "line_1", "text": "Tank 7", "box": [20, 20, 80, 20]}]}
    project = DesignerProject.from_dict({"screen": {"width": 800, "height": 400},
        "pages": [{"id": "main", "widgets": [{"id": "tank", "type": "Text",
            "geometry": {"x": 40, "y": 40, "width": 160, "height": 40},
            "properties": {"text": "Tank 7", "_ocrIds": ["line_1"]}}]}]})
    return ocr, project


class AcceptanceTests(unittest.TestCase):
    def test_pass_is_not_visual_or_runtime_certification(self):
        report = evaluate_reference(*fixture())
        self.assertTrue(report["passed"], report["issues"])
        self.assertFalse(report["visual_match_verified"])
        self.assertFalse(report["runtime_verified"])

    def test_missing_identity_and_altered_number_fail(self):
        ocr, project = fixture()
        project.pages[0].widgets[0].properties["text"] = "Tank 8"
        self.assertFalse(evaluate_reference(ocr, project)["gates"]["text"])
        project.pages[0].widgets[0].properties.pop("_ocrIds")
        self.assertFalse(evaluate_reference(ocr, project)["gates"]["coverage"])

    def test_duplicate_owner_and_unknown_identity_fail(self):
        ocr, project = fixture()
        duplicate = copy.deepcopy(project.pages[0].widgets[0])
        duplicate.id = "duplicate"
        duplicate.properties["_ocrIds"].append("invented")
        project.pages[0].widgets.append(duplicate)
        codes = {i["code"] for i in evaluate_reference(ocr, project)["issues"]}
        self.assertTrue({"unknown_ocr_id", "duplicate_ocr_owner"} <= codes)

    def test_position_scale_and_hidden_text_fail(self):
        ocr, project = fixture()
        widget = project.pages[0].widgets[0]
        widget.geometry["x"] = 400
        widget.properties["visible"] = False
        report = evaluate_reference(ocr, project)
        self.assertFalse(report["gates"]["geometry"])
        self.assertFalse(report["gates"]["coverage"])

    def test_aspect_fit_center_offset(self):
        ocr, project = fixture()
        project.screen.height = 600
        project.pages[0].widgets[0].geometry["y"] += 100
        report = evaluate_reference(ocr, project)
        self.assertTrue(report["passed"], report["issues"])

    def test_raw_screen_raster_rejected_cleaning_assertion_disclosed(self):
        ocr, project = fixture()
        from designer.model import DesignerWidget
        image = DesignerWidget("Image", "backing", {"x": 0, "y": 0, "width": 800, "height": 400}, {})
        project.pages[0].widgets.insert(0, image)
        self.assertFalse(evaluate_reference(ocr, project)["gates"]["editable_content"])
        image.properties["_referenceArtworkCleaned"] = True
        report = evaluate_reference(ocr, project)
        self.assertTrue(report["gates"]["editable_content"])
        self.assertEqual(report["raster_artwork_widgets"], ["backing"])
        self.assertFalse(report["visual_match_verified"])

    def test_empty_ocr_fails(self):
        ocr, project = fixture()
        ocr["lines"] = []
        self.assertFalse(evaluate_reference(ocr, project)["gates"]["source"])

    def test_pixels_diagnostic_only_even_exact(self):
        a = QImage(20, 10, QImage.Format_RGB32)
        a.fill("white")
        b = QImage(20, 10, QImage.Format_RGB32)
        b.fill("black")
        self.assertEqual(pixel_diagnostics(a, a)["mean_absolute_rgb_error"], 0)
        self.assertEqual(pixel_diagnostics(a, b)["mean_absolute_rgb_error"], 1)
        self.assertFalse(pixel_diagnostics(a, a)["certifies_visual_match"])

    def test_pixels_compare_centered_content_without_letterbox(self):
        from PySide6.QtGui import QPainter, QColor
        source = QImage(100, 50, QImage.Format_RGB32)
        source.fill("white")
        painter = QPainter(source)
        painter.fillRect(0, 0, 50, 50, QColor("red"))
        painter.end()
        target = QImage(200, 200, QImage.Format_RGB32)
        target.fill("black")
        painter = QPainter(target)
        painter.drawImage(0, 50, source.scaled(200, 100))
        painter.end()
        report = pixel_diagnostics(source, target)
        self.assertEqual(report["rendered_content_viewport_xywh"], [0, 50, 200, 100])
        self.assertLess(report["mean_absolute_rgb_error"], .003)
        self.assertFalse(report["certifies_visual_match"])


if __name__ == "__main__":
    unittest.main()
