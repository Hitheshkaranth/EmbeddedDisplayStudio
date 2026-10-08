"""ShStationLine keeps its contract: the QML declares exactly the registry's
properties, and the Designer painter reacts to current and to a long terminus
name, and does not paint the placeholder."""
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
from designer.canvas.rail import station_line
from designer.palette import default_registry

ROOT = Path(__file__).resolve().parent.parent
QML = ROOT / "ui" / "qml" / "Shadcn" / "ShStationLine.qml"
W, H = 520, 680


def _render(fn, props):
    image = QImage(W, H, QImage.Format_RGB32)
    image.fill(QColor("#101318"))
    painter = QPainter(image)
    fn(painter, QRectF(0, 0, W, H), props, None)
    painter.end()
    return image


def _differ(a, b):
    return sum(1 for y in range(0, H, 2) for x in range(0, W, 2) if a.pixel(x, y) != b.pixel(x, y))


class StationLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.definition = default_registry().get("ShStationLine")

    def test_qml_declares_registry_properties(self):
        declared = set(re.findall(r"^\s*property\s+\w+\s+(\w+)\s*:", QML.read_text(encoding="utf-8"), re.M))
        expected = {k for k in self.definition.properties if k not in ("opacity", "visible")}
        self.assertEqual(declared, expected)

    def test_painter_is_not_the_stub(self):
        props = dict(self.definition.defaults)
        face = _render(station_line.paint, props)
        stub = _render(lambda p, r, pr, c: _stub(p, r, pr, "ShStationLine"), props)
        self.assertGreater(_differ(face, stub), 500)

    def test_painter_reacts_to_current(self):
        props = dict(self.definition.defaults)
        images = [_render(station_line.paint, dict(props, current=c)) for c in (0, 1, 2, 4)]
        for a in range(len(images)):
            for b in range(a + 1, len(images)):
                self.assertGreater(_differ(images[a], images[b]), 200, (a, b))

    def test_painter_wraps_a_long_terminus(self):
        props = dict(self.definition.defaults)
        short = _render(station_line.paint, props)
        long_name = dict(props, stations="Attiguppe,Vijayanagar,Hosahalli,Magadi Road,"
                                         "Kranthivira Sangolli Rayanna (KSR) Bengaluru")
        self.assertGreater(_differ(short, _render(station_line.paint, long_name)), 200)

    def test_details_may_be_a_list(self):
        props = dict(self.definition.defaults)
        as_text = _render(station_line.paint, props)
        as_list = _render(station_line.paint, dict(props, details=props["details"].split(",")))
        self.assertEqual(_differ(as_text, as_list), 0)


if __name__ == "__main__":
    unittest.main()
