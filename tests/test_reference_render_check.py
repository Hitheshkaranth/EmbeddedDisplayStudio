from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/hmi_deployer"))
from reference_render_check import compare_rendered_ocr


def document(text, box=(10, 10, 100, 20), dimensions=(200, 100)):
    return {"width": dimensions[0], "height": dimensions[1], "box_format": "xywh",
            "lines": [{"id": "line_1", "text": text, "box": list(box), "confidence": None,
                       "words": [{"id": "word_1", "text": text, "box": list(box)}]}]}


class RenderCheckTests(unittest.TestCase):
    def test_scaled_normalized_match(self):
        report = compare_rendered_ocr(document("Process-Flow"), document("PROCESS FLOW", (20, 20, 200, 40), (400, 200)), 400, 200)
        self.assertTrue(report["passed"])

    def test_clipped_label_is_detected(self):
        report = compare_rendered_ocr(document("Temperature"), document("Tempera"), 200, 100)
        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatched_ids"], ["line_1"])

    def test_wrong_numeric_value_is_detected(self):
        report = compare_rendered_ocr(document("78.2"), document("78.8"), 200, 100)
        self.assertFalse(report["passed"])
        self.assertEqual(report["numeric_mismatch_ids"], ["line_1"])

    def test_identical_text_elsewhere_does_not_count(self):
        report = compare_rendered_ocr(document("Reactor"), document("Reactor", (150, 70, 40, 20)), 200, 100)
        self.assertEqual(report["missing_ids"], ["line_1"])

    def test_centered_letterbox_mapping(self):
        rendered = document("Reactor", (10, 60, 100, 20), (200, 200))
        report = compare_rendered_ocr(document("Reactor"), rendered, 200, 200)
        self.assertTrue(report["passed"])
        self.assertEqual(report["mapping"]["offset_y"], 50)


if __name__ == "__main__":
    unittest.main()
