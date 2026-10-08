"""ShSpeedArc keeps its contract: the QML declares exactly the registry's
properties, and the Designer painter follows value and target and does not
paint the placeholder."""
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
from designer.canvas.rail import speed_arc
from designer.palette import default_registry

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "ui" / "qml" / "Shadcn" / "ShSpeedArc.qml"
W, H = 420, 420


def _render(fn, props, size=(W, H)):
    image = QImage(size[0], size[1], QImage.Format_RGB32)
    image.fill(QColor("#16161c"))
    painter = QPainter(image)
    fn(painter, QRectF(0, 0, size[0], size[1]), props, None)
    painter.end()
    return image


def _differ(a, b):
    return sum(1 for y in range(0, a.height(), 2) for x in range(0, a.width(), 2)
               if a.pixel(x, y) != b.pixel(x, y))


class SpeedArcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.definition = default_registry().get("ShSpeedArc")

    def test_qml_declares_registry_properties(self):
        declared = set(re.findall(r"^\s*property\s+\w+\s+(\w+)\s*:", QML.read_text(encoding="utf-8"), re.M))
        expected = {k for k in self.definition.properties if k not in ("opacity", "visible")}
        self.assertEqual(declared, expected)

    def test_painter_is_not_the_stub(self):
        props = dict(self.definition.defaults)
        face = _render(speed_arc.paint, props)
        stub = _render(lambda p, r, pr, c: _stub(p, r, pr, "ShSpeedArc"), props)
        self.assertGreater(_differ(face, stub), 2000)

    def test_painter_follows_value(self):
        props = dict(self.definition.defaults)
        slow = _render(speed_arc.paint, {**props, "value": 10})
        fast = _render(speed_arc.paint, {**props, "value": 90})
        self.assertGreater(_differ(slow, fast), 1000)

    def test_value_clamps_to_the_scale(self):
        props = dict(self.definition.defaults)
        top = _render(speed_arc.paint, {**props, "value": 100})
        over = _render(speed_arc.paint, {**props, "value": 250})
        self.assertEqual(_differ(top, over), 0)
        bottom = _render(speed_arc.paint, {**props, "value": 0})
        under = _render(speed_arc.paint, {**props, "value": -20})
        self.assertEqual(_differ(bottom, under), 0)

    def test_target_moves_and_hides(self):
        props = dict(self.definition.defaults)
        base = _render(speed_arc.paint, props)
        moved = _render(speed_arc.paint, {**props, "target": 20})
        hidden = _render(speed_arc.paint, {**props, "showTarget": False})
        self.assertGreater(_differ(base, moved), 200)
        self.assertGreater(_differ(base, hidden), 200)

    def test_small_and_empty_props_paint(self):
        _render(speed_arc.paint, {}, size=(60, 40))
        _render(speed_arc.paint, {"unit": "", "targetLabel": "", "decimals": 2}, size=(240, 200))


if __name__ == "__main__":
    unittest.main()
