"""Light screenshots must not inherit the photographed device's dark bezel."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage, QPainter
from designer.layout.palette import palette_from_image, reference_content_rect, _lum, _rgb


def screen(bezel=True):
    image = QImage(800, 500, QImage.Format_RGB32)
    image.fill(QColor("#101418" if bezel else "#e7eff9"))
    p = QPainter(image)
    if bezel:
        p.fillRect(24, 25, 752, 450, QColor("#e7eff9"))
    p.fillRect(160, 90, 580, 100, QColor("#f5f8fc"))
    p.fillRect(45, 90, 90, 35, QColor("#1688ff"))
    p.fillRect(180, 115, 120, 12, QColor("#172333"))
    p.end()
    return image


class LightViewport(unittest.TestCase):
    def test_four_sided_bezel_detected(self):
        actual = reference_content_rect(screen())
        for got, expected in zip(actual, (24, 25, 776, 475)):
            self.assertLessEqual(abs(got - expected), 5)

    def test_plain_screenshot_not_cropped(self):
        self.assertEqual(reference_content_rect(screen(False)), (0, 0, 800, 500))

    def test_device_does_not_make_light_screen_dark(self):
        palette = palette_from_image(screen())
        self.assertGreater(_lum(_rgb(palette["background"])), .55)
        self.assertLess(_lum(_rgb(palette["foreground"])), .1)
        self.assertIn("primary", palette)

    def test_dark_ui_stays_uncropped(self):
        image = QImage(800, 500, QImage.Format_RGB32)
        image.fill(QColor("#202428"))
        self.assertEqual(reference_content_rect(image), (0, 0, 800, 500))

    def test_applied_palette_sets_runtime_theme(self):
        from designer.model import DesignerProject
        from designer.layout.palette import apply_reference_palette
        from tools.hmi_deployer.ai_design import encode_brief_image
        project = DesignerProject()
        apply_reference_palette(project, [encode_brief_image(screen())])
        self.assertEqual(project.screen.theme, "light")

    def test_measured_artwork_and_values_are_not_guessed_again(self):
        from designer.model import DesignerProject
        from designer.layout.palette import trim_crops, align_spots, snap_spots
        project = DesignerProject.from_dict({"pages": [{"widgets": [
            {"id": "art", "type": "Image", "properties": {
                "_crop": [.02, .02, .98, .98], "_reference": {"layout": "measured"}}},
            {"id": "value", "type": "Text", "properties": {
                "_wbox": [.2, .2, .4, .3], "_reference": {"layout": "measured"}}}
        ]}]})
        before = project.to_dict()
        for operation in (trim_crops, align_spots, snap_spots):
            self.assertEqual(operation(screen(), project), 0)
        self.assertEqual(project.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
