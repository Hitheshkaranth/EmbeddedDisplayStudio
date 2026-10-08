"""ShTrainConsist: the Studio canvas painter draws the consist (not the stub)
and follows its bindable door states."""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from designer.canvas.automotive_previews import _stub
from designer.canvas.rail import train_consist
from designer.palette.widget_registry import default_registry

W, H = 300, 880


def _render(props, stub=False):
    img = QImage(W, H, QImage.Format_RGB32)
    img.fill(QColor("#101318"))
    p = QPainter(img)
    if stub:
        _stub(p, QRectF(0, 0, W, H), props, "ShTrainConsist")
    else:
        train_consist.paint(p, QRectF(0, 0, W, H), props, None)
    p.end()
    return img


def _count(img, colour, tol=24):
    c = QColor(colour)
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            q = QColor(img.pixel(x, y))
            if abs(q.red() - c.red()) <= tol and abs(q.green() - c.green()) <= tol and abs(q.blue() - c.blue()) <= tol:
                n += 1
    return n


class TrainConsistPainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.defaults = dict(default_registry().get("ShTrainConsist").defaults)

    def test_differs_from_stub(self):
        self.assertNotEqual(_render(self.defaults), _render(self.defaults, stub=True))

    def test_doors_left_changes_picture(self):
        closed = _render(self.defaults)
        opened = _render(dict(self.defaults, doorsLeft="open"))
        self.assertNotEqual(closed, opened)
        self.assertGreater(_count(closed, "#4ade80"), _count(opened, "#4ade80"))
        self.assertGreater(_count(opened, "#f59e0b"), 0)
        self.assertEqual(_count(closed, "#f59e0b"), 0)

    def test_bound_bool_and_number(self):
        self.assertEqual(train_consist.door_state(True), "closed")
        self.assertEqual(train_consist.door_state(1), "closed")
        self.assertEqual(train_consist.door_state(False), "open")
        self.assertEqual(train_consist.door_state(0), "open")
        self.assertEqual(train_consist.door_state("disabled"), "disabled")
        self.assertEqual(_render(dict(self.defaults, doorsRight=True)),
                         _render(dict(self.defaults, doorsRight="closed")))

    def test_car_count_follows_cars(self):
        self.assertNotEqual(_render(self.defaults), _render(dict(self.defaults, cars="MC1,M1,M2,MC2")))
        _render(dict(self.defaults, cars=""))   # no cars: nothing to draw, no crash

    def test_caption_split(self):
        self.assertEqual(train_consist.split_caption("DOORS L: CLOSED (SECURED)"), ("DOORS L:", "CLOSED (SECURED)"))
        self.assertEqual(train_consist.split_caption("NO COLON"), ("NO COLON", ""))


if __name__ == "__main__":
    unittest.main()
