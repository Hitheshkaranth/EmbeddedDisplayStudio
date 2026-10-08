"""ShTractionBar keeps its contract: the QML declares exactly the registry's
properties, and the Designer painter reacts to value (traction vs braking vs
coast) and does not paint the placeholder."""
import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
for _font_dir in ("C:/Windows/Fonts", "/usr/share/fonts"):
    if os.path.isdir(_font_dir):
        os.environ.setdefault("QT_QPA_FONTDIR", _font_dir)
        break

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from designer.canvas.automotive_previews import _stub
from designer.canvas.rail import traction_bar
from designer.palette import default_registry

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "ui" / "qml" / "Shadcn" / "ShTractionBar.qml"
W, H = 140, 640


def _render(fn, props):
    image = QImage(W, H, QImage.Format_RGB32)
    image.fill(QColor("#101318"))
    painter = QPainter(image)
    fn(painter, QRectF(0, 0, W, H), props, None)
    painter.end()
    return image


def _differ(a, b):
    return sum(1 for y in range(0, H, 2) for x in range(0, W, 2) if a.pixel(x, y) != b.pixel(x, y))


class TractionBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.definition = default_registry().get("ShTractionBar")

    def test_qml_declares_registry_properties(self):
        declared = set(re.findall(r"^\s*property\s+\w+\s+(\w+)\s*:", QML.read_text(encoding="utf-8"), re.M))
        expected = {k for k in self.definition.properties if k not in ("opacity", "visible")}
        self.assertEqual(declared, expected)

    def test_painter_is_not_the_stub(self):
        props = dict(self.definition.defaults)
        face = _render(traction_bar.paint, props)
        stub = _render(lambda p, r, pr, c: _stub(p, r, pr, "ShTractionBar"), props)
        self.assertGreater(_differ(face, stub), 500)

    def test_painter_reacts_to_value(self):
        coast = _render(traction_bar.paint, {"value": 0})
        power = _render(traction_bar.paint, {"value": 60})
        brake = _render(traction_bar.paint, {"value": -60})
        self.assertGreater(_differ(coast, power), 500)
        self.assertGreater(_differ(coast, brake), 500)
        self.assertGreater(_differ(power, brake), 500)
        # the green fill lives in the upper track, the amber one in the lower
        green = QColor(power.pixel(W // 2 + 10, int(H * 0.40)))
        amber = QColor(brake.pixel(W // 2 + 10, int(H * 0.60)))
        self.assertGreater(green.green(), green.red())
        self.assertGreater(amber.red(), amber.blue() + 60)


if __name__ == "__main__":
    unittest.main()
