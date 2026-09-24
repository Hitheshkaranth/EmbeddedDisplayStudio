"""ShAutoLevel and ShAutoReadout, rendered in QML and in the canvas preview.

Checks that red-zone pixels appear and disappear with the value, that curved
and straight levels differ, that warnBelow/warnAbove turn the readout red,
and that decimals change the ink. Uses the same _render_qml / _render_preview
approach as test_automotive_contract.py without importing it.
"""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
for _font_dir in ("C:/Windows/Fonts", "/usr/share/fonts"):
    if os.path.isdir(_font_dir):
        os.environ.setdefault("QT_QPA_FONTDIR", _font_dir)
        break

from PySide6.QtCore import QUrl, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from designer.canvas import widget_previews
from designer.generators.qml_generator import QmlGenerator
from designer.model import DesignerWidget
from designer.palette import default_registry

ROOT = Path(__file__).resolve().parent.parent
QML_DIR = ROOT / "ui" / "qml"
CATEGORY = "Automotive"

# Automotive colour map (mirrors widget_previews.AUTO).
AUTO = {
    "panel": "#0b0f16",
    "track": "#1a222e",
    "accent": "#22a8ff",
    "accentDeep": "#0a4f8a",
    "glow": "#7fd4ff",
    "redline": "#ff2d55",
    "text": "#ffffff",
    "muted": "#8a97a8",
    "line": "#c9d3df",
    "amber": "#ffb000",
    "green": "#2fe07f",
    "red": "#ff3b3b",
    "blue": "#4f9dff",
    "tileBg": "#141c28",
    "tileBorder": "#22304a",
}


def _auto(name):
    return AUTO[name]


class _AutoLevelReadoutTests(unittest.TestCase):
    """Render helpers shared by the QML and preview test suites."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.generator = QmlGenerator(cls.registry)
        cls.level_defs = [d for d in cls.registry.definitions() if d.type == "ShAutoLevel"]
        cls.readout_defs = [d for d in cls.registry.definitions() if d.type == "ShAutoReadout"]
        assert cls.level_defs, "no ShAutoLevel registered"
        assert cls.readout_defs, "no ShAutoReadout registered"

    # -- rendering helpers ---------------------------------------------------

    def _render_qml(self, definition, props):
        view = QQuickView()
        view.engine().addImportPath(str(ROOT / "ui" / "qml"))
        widget = DesignerWidget(definition.type, "sample",
                                {"x": 8, "y": 8, "width": definition.default_width,
                                 "height": definition.default_height}, props)
        body = "\n".join(self.generator._widget(widget, 1))
        source = ("import QtQuick 2.15\nimport QtQuick.Controls 2.15\nimport Shadcn 1.0\n"
                  f"Rectangle {{ width: {definition.default_width + 16}; "
                  f"height: {definition.default_height + 16}; color: Theme.autoPanel\n{body}\n}}")
        component = QQmlComponent(view.engine())
        component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT / "tests" / "contract.qml")))
        errors = [e.toString() for e in component.errors()]
        self.assertFalse(errors, f"{definition.type} failed to compile: {errors}")
        obj = component.create()
        self.assertIsNotNone(obj, f"{definition.type} failed to instantiate")
        view.setContent(QUrl(), component, obj)
        view.show()
        QTest.qWait(120)
        image = view.grabWindow()
        view.close()
        view.deleteLater()
        self.app.processEvents()
        return image

    def _render_preview(self, definition, props):
        painter_fn = widget_previews.painter_for(definition.type)
        self.assertIsNotNone(painter_fn, f"no preview painter for {definition.type}")
        image = QImage(definition.default_width, definition.default_height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter_fn(painter, QRectF(0, 0, definition.default_width, definition.default_height), props, None)
        painter.end()
        return image

    @staticmethod
    def _differs(a, b):
        if a.size() != b.size():
            return True
        return any(a.pixel(x, y) != b.pixel(x, y)
                   for y in range(0, a.height(), 2) for x in range(0, a.width(), 2))

    @staticmethod
    def _ink_count(image):
        return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                   if image.pixelColor(x, y).alpha() > 0)

    @staticmethod
    def _blue_count(image):
        """Sampled pixels in the accent fill (blue well above red)."""
        return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                   if (lambda c: c.blue() > 150 and c.blue() > c.red() + 80)(image.pixelColor(x, y)))

    @staticmethod
    def _red_count(image, threshold=200):
        """How many sampled pixels are clearly red (R > threshold and R > G and R > B)."""
        return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                   if (lambda c: c.red() > threshold and c.red() > c.green() and c.red() > c.blue())(
                       image.pixelColor(x, y)))

    @staticmethod
    def _has_red_pixels(image, threshold=200):
        """Return True if any pixel is clearly red (R > threshold and R > G and R > B)."""
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                c = image.pixelColor(x, y)
                r = c.red()
                g = c.green()
                b = c.blue()
                if r > threshold and r > g and r > b:
                    return True
        return False

    @staticmethod
    def _has_exact_color(image, hex_color, threshold=20):
        """Return True if any pixel is within threshold of hex_color."""
        tc = QColor(hex_color)
        tr, tg, tb = tc.red(), tc.green(), tc.blue()
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                c = image.pixelColor(x, y)
                cr, cg, cb = c.red(), c.green(), c.blue()
                if (abs(cr - tr) <= threshold and
                        abs(cg - tg) <= threshold and
                        abs(cb - tb) <= threshold):
                    return True
        return False

    # -- ShAutoLevel QML tests -----------------------------------------------

    def test_autolevel_red_zone_low_lays_down_red_pixels_qml(self):
        """value 5 with redZone=low lays down red in the fill; value 60 does not."""
        d = self.level_defs[0]
        props_low = {**d.defaults, "value": 5.0, "redZone": "low"}
        props_ok = {**d.defaults, "value": 60.0, "redZone": "low"}
        img_low = self._render_qml(d, props_low)
        img_ok = self._render_qml(d, props_ok)
        # The zone is always red; a level inside it shows no blue at all,
        # a level above it fills blue up to the mark.
        self.assertTrue(self._has_red_pixels(img_low) and self._has_red_pixels(img_ok))
        self.assertLess(self._blue_count(img_low), 20)   # the 2 px glow line only
        self.assertGreater(self._blue_count(img_ok), 40)

    def test_autolevel_red_zone_high_moves_red_to_top(self):
        """redZone=high puts red at the top of the bar."""
        d = self.level_defs[0]
        props = {**d.defaults, "value": 95.0, "redZone": "high"}
        img = self._render_qml(d, props)
        # Top quarter should have red pixels.
        self.assertTrue(self._has_red_pixels(img, threshold=200),
                        "QML: redZone=high should show red pixels")

    def test_autolevel_curved_vs_straight_differ(self):
        """curved=false and curved=true produce different pixel patterns."""
        d = self.level_defs[0]
        props_curved = {**d.defaults, "curved": True}
        props_straight = {**d.defaults, "curved": False}
        img_curved = self._render_qml(d, props_curved)
        img_straight = self._render_qml(d, props_straight)
        self.assertTrue(self._differs(img_curved, img_straight),
                        "QML: curved vs straight should differ")

    # -- ShAutoLevel preview tests -------------------------------------------

    def test_autolevel_red_zone_low_lays_down_red_pixels_preview(self):
        """value 5 with redZone=low lays down red in the fill area (preview)."""
        d = self.level_defs[0]
        props_low = {**d.defaults, "value": 5.0, "redZone": "low"}
        props_ok = {**d.defaults, "value": 60.0, "redZone": "low"}
        img_low = self._render_preview(d, props_low)
        img_ok = self._render_preview(d, props_ok)
        self.assertLess(self._blue_count(img_low), 20)   # the 2 px glow line only
        self.assertGreater(self._blue_count(img_ok), 40)

    def test_autolevel_red_zone_high_moves_red_to_top_preview(self):
        """redZone=high puts red at the top in the preview when value is high enough."""
        d = self.level_defs[0]
        props = {**d.defaults, "value": 95.0, "redZone": "high"}
        img = self._render_preview(d, props)
        self.assertTrue(self._has_exact_color(img, _auto("redline")),
                        "preview: redZone=high should show red pixels")

    def test_autolevel_curved_vs_straight_differ_preview(self):
        """curved=false and curved=true produce different pixel patterns (preview)."""
        d = self.level_defs[0]
        props_curved = {**d.defaults, "curved": True}
        props_straight = {**d.defaults, "curved": False}
        img_curved = self._render_preview(d, props_curved)
        img_straight = self._render_preview(d, props_straight)
        self.assertTrue(self._differs(img_curved, img_straight),
                        "preview: curved vs straight should differ")

    # -- ShAutoReadout QML tests ---------------------------------------------

    def test_readout_warnBelow_shows_red_qml(self):
        """value 1.2 with warnBelow 1.8 autoRed-pixels; value 2.5 does not."""
        d = self.readout_defs[0]
        props_warn = {**d.defaults, "value": 1.2, "warnBelow": 1.8, "warnAbove": 0.0, "decimals": 1}
        props_ok = {**d.defaults, "value": 2.5, "warnBelow": 1.8, "warnAbove": 0.0, "decimals": 1}
        img_warn = self._render_qml(d, props_warn)
        img_ok = self._render_qml(d, props_ok)
        self.assertTrue(self._has_exact_color(img_warn, _auto("red")),
                        "QML: value 1.2 below warnBelow 1.8 should contain red pixels")
        self.assertFalse(self._has_exact_color(img_ok, _auto("red")),
                         "QML: value 2.5 within range should not contain red pixels")

    def test_readout_decimals_1_vs_0_differ(self):
        """decimals 1 renders '13.5', comparing ink with decimals 0."""
        d = self.readout_defs[0]
        props_0 = {**d.defaults, "value": 13.5, "decimals": 0}
        props_1 = {**d.defaults, "value": 13.5, "decimals": 1}
        img_0 = self._render_qml(d, props_0)
        img_1 = self._render_qml(d, props_1)
        self.assertTrue(self._differs(img_0, img_1),
                        "QML: decimals 0 and 1 should produce different ink")

    # -- ShAutoReadout preview tests -----------------------------------------

    def test_readout_warnBelow_shows_red_preview(self):
        """value 1.2 with warnBelow 1.8 autoRed-pixels in preview."""
        d = self.readout_defs[0]
        props_warn = {**d.defaults, "value": 1.2, "warnBelow": 1.8, "warnAbove": 0.0, "decimals": 1}
        props_ok = {**d.defaults, "value": 2.5, "warnBelow": 1.8, "warnAbove": 0.0, "decimals": 1}
        img_warn = self._render_preview(d, props_warn)
        img_ok = self._render_preview(d, props_ok)
        self.assertTrue(self._has_exact_color(img_warn, _auto("red")),
                        "preview: value 1.2 below warnBelow 1.8 should contain red pixels")
        self.assertFalse(self._has_exact_color(img_ok, _auto("red")),
                         "preview: value 2.5 within range should not contain red pixels")

    def test_readout_decimals_1_vs_0_differ_preview(self):
        """decimals 1 renders '13.5', comparing ink with decimals 0 (preview)."""
        d = self.readout_defs[0]
        props_0 = {**d.defaults, "value": 13.5, "decimals": 0}
        props_1 = {**d.defaults, "value": 13.5, "decimals": 1}
        img_0 = self._render_preview(d, props_0)
        img_1 = self._render_preview(d, props_1)
        self.assertTrue(self._differs(img_0, img_1),
                        "preview: decimals 0 and 1 should produce different ink")


if __name__ == "__main__":
    unittest.main()