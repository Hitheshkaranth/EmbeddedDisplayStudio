import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

spec = importlib.util.spec_from_file_location("reference_backing", Path(__file__).resolve().parents[1] / "tools/hmi_deployer/reference_backing.py")
backing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backing)


class BackingTests(unittest.TestCase):
    def test_removes_measured_dark_glyph_and_preserves_unmasked_artwork(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new("RGB", (100, 60), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 23, 29), fill="black")
            draw.rectangle((70, 10, 90, 50), fill="blue")
            source = root / "source.png"
            image.save(source)
            doc = {"width": 100, "height": 60, "box_format": "xywh", "lines": [{"text": "I", "box": [20, 20, 4, 10], "words": [{"text": "I", "box": [20, 20, 4, 10]}]}]}
            result = backing.prepare_backing(source, doc, root / "out")
            cleaned = np.asarray(Image.open(root / "out/assets/reference-artwork.png"))
            self.assertTrue((cleaned[20:30, 20:24] == 255).all())
            self.assertTrue((cleaned[15, 80] == [0, 0, 255]).all())
            self.assertEqual(result["lines"][0]["foreground"], "#000000")
            self.assertGreater(result["lines"][0]["font_size"], 0)
            self.assertEqual(result["backing"]["word_boxes_processed"], 1)
            self.assertNotIn("backing", doc)

    def test_rejects_ambiguous_box_format(self):
        with self.assertRaises(ValueError):
            backing.prepare_backing("unused.png", {"box_format": "xyxy"}, "unused")


if __name__ == "__main__":
    unittest.main()
