"""Deterministic tests for measured OCR coordinates and error behavior."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

MODULE = Path(__file__).resolve().parents[1] / "tools/hmi_deployer/reference_ocr.py"
spec = importlib.util.spec_from_file_location("reference_ocr", MODULE)
ocr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr)


class ReferenceOCRTests(unittest.TestCase):
    def test_scaled_tile_coordinates_and_duplicate_suppression(self):
        full = {"lines": [{"words": [{"text": "Valve", "box": [100, 50, 140, 65]}]}]}
        tile = {"lines": [{"words": [
            {"text": "Valve", "box": [20, 20, 100, 50]},
            {"text": "OPEN", "box": [20, 60, 100, 90]},
        ]}]}
        lines = ocr._merge_passes([(full, 1, 0, 0), (tile, 2, 90, 40)], 400, 300)
        self.assertEqual([line["text"] for line in lines], ["Valve", "OPEN"])
        self.assertEqual(lines[1]["box"], [100, 70, 140, 85])
        self.assertIsNone(lines[1]["confidence"])

    def test_public_output_xywh_and_null_confidence(self):
        native = {"language": "en-US", "lines": [{"words": [{"text": "42", "box": [10, 20, 30, 35]}]}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.png"
            Image.new("RGB", (200, 100), "white").save(path)
            with patch.object(ocr, "_native_ocr", return_value=native):
                result = ocr.extract_ocr(path)
        self.assertEqual(result["box_format"], "xywh")
        self.assertEqual(result["lines"][0]["box"], [10, 20, 20, 15])
        self.assertEqual(result["lines"][0]["words"][0]["box"], [10, 20, 20, 15])
        self.assertIsNone(result["confidence"])

    def test_missing_image_is_explicit_error(self):
        with self.assertRaises(ocr.ReferenceOCRError):
            ocr.extract_ocr("missing-reference-image.png")

    def test_splits_caption_readout_and_distant_column(self):
        words = [
            {"text": "Temperature", "box": [10, 20, 90, 32]},
            {"text": "78.2", "box": [106, 20, 132, 32]},
            {"text": "C", "box": [135, 20, 143, 32]},
            {"text": "Running", "box": [200, 20, 246, 32]},
        ]
        lines = ocr._merge_passes([({"lines": [{"words": words}]}, 1, 0, 0)], 300, 100)
        self.assertEqual([line["text"] for line in lines], ["Temperature", "78.2 C", "Running"])
        self.assertEqual(lines[1]["box"], [106, 20, 143, 32])

    def test_keeps_normal_date_and_range_spacing(self):
        def word(text, left, right):
            return {"text": text, "box": [left, 0, right, 12]}
        date = [word("Thu,", 0, 20), word("23", 24, 38), word("Oct", 42, 62), word("2026", 66, 94)]
        interval = [word("40", 0, 14), word("-", 18, 22), word("80", 26, 40)]
        self.assertEqual(len(ocr._spatial_runs(date)), 1)
        self.assertEqual(len(ocr._spatial_runs(interval)), 1)


if __name__ == "__main__":
    unittest.main()
