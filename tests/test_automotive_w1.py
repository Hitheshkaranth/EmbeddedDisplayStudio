"""ShClusterGauge and ShGearIndicator behave like the cluster they imitate.

The redline band is information even when the needle is far from it; the
readout falls back to the value; a shorter sweep paints a shorter arc; a
gear the list did not foresee is still shown.
"""
import copy
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
for _font_dir in ("C:/Windows/Fonts", "/usr/share/fonts"):
    if os.path.isdir(_font_dir):
        os.environ.setdefault("QT_QPA_FONTDIR", _font_dir)
        break

from PySide6.QtCore import QRectF, QUrl, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtQml import QQmlComponent  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.canvas import widget_previews  # noqa: E402
from designer.generators.qml_generator import QmlGenerator  # noqa: E402
from designer.model import DesignerWidget  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402

REDLINE = QColor("#ff2d55")
ACCENT = QColor("#22a8ff")


def _close(pixel, colour, tolerance=40):
    return (abs(pixel.red() - colour.red()) < tolerance and abs(pixel.green() - colour.green()) < tolerance
            and abs(pixel.blue() - colour.blue()) < tolerance)


def _count(image, colour):
    return sum(1 for y in range(image.height()) for x in range(image.width())
               if _close(image.pixelColor(x, y), colour))


class ClusterGaugeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.generator = QmlGenerator(cls.registry)

    def render_qml(self, widget_type, props):
        definition = self.registry.get(widget_type)
        merged = copy.deepcopy(definition.defaults)
        merged.update(props)
        view = QQuickView()
        view.engine().addImportPath(str(REPO_ROOT / "ui" / "qml"))
        body = "\n".join(self.generator._widget(DesignerWidget(
            widget_type, "w", {"x": 0, "y": 0, "width": definition.default_width,
                               "height": definition.default_height}, merged), 1))
        component = QQmlComponent(view.engine())
        component.setData(("import QtQuick 2.15\nimport Shadcn 1.0\nRectangle { width: %d; height: %d; "
                           "color: \"#0b0f16\"\n%s\n}" % (definition.default_width, definition.default_height,
                                                          body)).encode(),
                          QUrl.fromLocalFile(str(REPO_ROOT / "tests" / "w1.qml")))
        self.assertEqual([e.toString() for e in component.errors()], [])
        obj = component.create()
        view.setContent(QUrl(), component, obj)
        view.show(); QTest.qWait(100)
        image = view.grabWindow()
        root = obj.childItems()[0]
        gear_list = root.property("_list")
        facts = {"_list": gear_list.toVariant() if hasattr(gear_list, "toVariant") else gear_list,
                 "texts": [c.property("text") for c in root.childItems()
                           if c.metaObject().className().startswith("QQuickText")]}
        view.close(); view.deleteLater(); self.app.processEvents()
        return image, facts

    def render_preview(self, widget_type, props):
        definition = self.registry.get(widget_type)
        merged = copy.deepcopy(definition.defaults)
        merged.update(props)
        image = QImage(definition.default_width, definition.default_height, QImage.Format_ARGB32)
        image.fill(QColor("#0b0f16"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        widget_previews.painter_for(widget_type)(
            painter, QRectF(0, 0, definition.default_width, definition.default_height), merged, None)
        painter.end()
        return image

    def test_redline_band_is_visible_at_minimum(self):
        for render in (lambda p: self.render_qml("ShClusterGauge", p)[0],
                       lambda p: self.render_preview("ShClusterGauge", p)):
            image = render({"value": 0.0})
            self.assertGreater(_count(image, REDLINE), 30)

    def test_empty_readout_shows_the_value_with_decimals(self):
        _, facts = self.render_qml("ShClusterGauge", {"readout": "", "value": 3.456, "decimals": 1})
        self.assertIn("3.5", facts["texts"])

    def test_a_shorter_sweep_paints_less_arc(self):
        short = _count(self.render_qml("ShClusterGauge", {"sweep": 180.0, "value": 6.0})[0], ACCENT)
        long = _count(self.render_qml("ShClusterGauge", {"sweep": 300.0, "value": 6.0})[0], ACCENT)
        self.assertLess(short, long)

    def test_unknown_gear_is_still_shown(self):
        _, facts = self.render_qml("ShGearIndicator", {"gear": "X"})
        self.assertIn("X", facts["_list"])
        image, _ = self.render_qml("ShGearIndicator", {"gear": "X", "modeNumber": 0})
        self.assertGreater(sum(1 for y in range(image.height()) for x in range(image.width())
                               if image.pixelColor(x, y).lightness() > 200), 20)

    def test_mode_number_zero_draws_narrower(self):
        def ink_width(image):
            columns = [x for x in range(image.width()) for y in range(image.height())
                       if image.pixelColor(x, y).lightness() > 100]
            return max(columns) - min(columns)
        with_digit = ink_width(self.render_qml("ShGearIndicator", {"modeNumber": 4})[0])
        without = ink_width(self.render_qml("ShGearIndicator", {"modeNumber": 0})[0])
        self.assertLess(without, with_digit)
        self.assertLess(ink_width(self.render_preview("ShGearIndicator", {"modeNumber": 0})),
                        ink_width(self.render_preview("ShGearIndicator", {"modeNumber": 4})))


if __name__ == "__main__":
    unittest.main()
