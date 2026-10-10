"""A design followed from a picture takes the picture's colours
(designer/layout/palette.py), not the kit's dark theme.

The picture here is drawn in the test: a SCADA screen's dark grey glass,
lighter grey cards with a title band, near-black value boxes with green
digits, white text, and a big orange "process drawing" that is cut into the
design as a picture and must not colour the chrome.
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

RECORDED = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_furnace_ornith.json")
DRAWING = (0.0, 0.1, 0.7, 0.85)


def _scada(width=1024, height=768):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#2a2a2a"))
    p = QPainter(image)
    l, t, r, b = DRAWING
    p.fillRect(int(l * width), int(t * height), int((r - l) * width), int((b - t) * height), QColor("#f07818"))
    for i in range(4):                                         # the cards at the right
        y = 80 + i * 145
        p.fillRect(745, y, 270, 135, QColor("#3a3a3a"))
        p.fillRect(745, y, 270, 24, QColor("#505050"))        # title band
        for row in range(3):
            p.fillRect(880, y + 34 + row * 30, 70, 22, QColor("#121212"))
            p.fillRect(900, y + 40 + row * 30, 40, 10, QColor("#22e04a"))
            p.fillRect(755, y + 40 + row * 30, 90, 8, QColor("#efefef"))
    p.fillRect(8, 655, 1008, 34, QColor("#22e04a"))            # the banner
    p.end()
    return image


class Palette(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])

    def test_the_picture_gives_its_greys_green_and_text(self):
        from designer.layout.palette import _lum, _rgb, contrast, palette_from_image
        palette = palette_from_image(_scada(), exclude=[DRAWING])
        for token in ("background", "card", "header", "inset", "foreground", "success"):
            self.assertIn(token, palette)
        lum = {k: _lum(_rgb(v)) for k, v in palette.items()}
        self.assertLess(lum["inset"], lum["background"], "value boxes are darker than the glass")
        self.assertLess(lum["background"], lum["card"], "cards are lighter than the glass")
        self.assertLess(lum["card"], lum["header"], "a card's title band is lighter again")
        r, g, b = _rgb(palette["success"])
        self.assertTrue(g > 180 and g > r + 60 and g > b + 60, palette["success"])
        self.assertGreater(contrast(palette["foreground"], palette["card"]), 7)
        self.assertNotIn("primary", palette, "the drawing's orange is left out")

    def test_without_the_exclusion_the_drawing_would_colour_it(self):
        from designer.layout.palette import palette_from_image
        self.assertIn("primary", palette_from_image(_scada()))

    def test_a_light_picture_keeps_the_kits_theme(self):
        from designer.layout.palette import palette_from_image
        image = QImage(400, 300, QImage.Format_RGB32)
        image.fill(QColor("#f4f4f4"))
        self.assertEqual(palette_from_image(image), {})

    def test_the_screen_keeps_it_and_the_theme_reads_it(self):
        from designer.layout.style import theme_colour
        from designer.model import DesignerProject
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        with open(RECORDED, encoding="utf-8") as fh:
            project = AIDesignGenerator().generate(json.load(fh)["reply"], 1024, 768)
        kit_card = theme_colour(project, "card")
        project.screen.palette = {"card": "#363636"}
        self.assertEqual(theme_colour(project, "card"), "#363636")
        self.assertEqual(theme_colour(project, "border"), theme_colour(DesignerProject(), "border"))
        again = DesignerProject.from_dict(project.to_dict())
        self.assertEqual(again.screen.palette, {"card": "#363636"})
        project.screen.palette = {}
        self.assertEqual(theme_colour(project, "card"), kit_card)
        self.assertNotIn("palette", project.to_dict()["screen"])

    def test_a_reference_run_is_laid_out_in_the_pictures_colours(self):
        from designer.layout.compiler import CROP_MARK
        from designer.layout.palette import apply_reference_palette
        from tools.hmi_deployer.ai_design import encode_brief_image
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        gen = AIDesignGenerator()
        with open(RECORDED.replace(".json", "_rows.json"), encoding="utf-8") as fh:
            project = gen.generate(json.load(fh)["reply"], 1024, 768)
        palette = apply_reference_palette(project, [encode_brief_image(_scada(), "ref.png")], gen.registry)
        self.assertTrue(palette)
        self.assertEqual(project.screen.background, palette["background"])
        widgets = list(project.pages[0].walk())
        cards = [w for w in widgets if w.type == "ShCard" and w.properties.get("_compiledChrome")
                 and w.properties.get("color") not in (None, "#00000000")]
        self.assertTrue(cards)
        self.assertTrue(all(w.properties["color"] == palette["card"] for w in cards))
        rows = [w for w in widgets if w.type == "ShProcessValue"]
        self.assertTrue(rows and all(w.properties.get("boxColor") == palette["inset"] for w in rows))
        buttons = [w for w in widgets if w.type == "ShButton"]
        self.assertTrue(all(w.properties.get("backgroundColor") == palette["secondary"] for w in buttons))
        # The drawing still is a picture cut from the reference.
        self.assertTrue(any(w.properties.get(CROP_MARK) for w in widgets if w.type == "Image"))


if __name__ == "__main__":
    unittest.main()
