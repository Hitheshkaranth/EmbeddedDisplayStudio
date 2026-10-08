"""
tests/test_rail_status_card.py
Layer: Test

The ShStatusCard canvas painter (designer/canvas/rail/status_card.py): it is a
real face, not the placeholder, and its pixels follow the bindable ``state``
and the two-line title. The QML file declares exactly the registry's
properties.

Requires PySide6; skipped elsewhere.
"""
import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

W, H = 240, 180
DEFAULTS = {"icon": "snowflake", "title": "HVAC:", "status": "ACTIVE (21°C)",
            "state": "ok", "iconColor": "#38bdf8"}


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class StatusCardPainterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _render(self, paint, **props):
        image = QImage(W, H, QImage.Format_RGB32)
        image.fill(QColor("#101318"))
        painter = QPainter(image)
        paint(painter, QRectF(0, 0, W, H), dict(DEFAULTS, **props), None)
        painter.end()
        return image

    def _card(self, **props):
        from designer.canvas.rail.status_card import paint
        return self._render(paint, **props)

    def test_registered_and_not_the_stub(self):
        from designer.canvas.automotive_previews import _stub
        from designer.canvas.rail_previews import PAINTERS
        from designer.canvas.rail.status_card import paint
        self.assertIs(PAINTERS["ShStatusCard"], paint)
        stub = self._render(lambda p, r, props, c: _stub(p, r, props, "ShStatusCard"))
        self.assertNotEqual(self._card(), stub)

    def test_state_changes_dot_and_status_colour(self):
        from designer.canvas.rail.status_card import state_colours
        images = {s: self._card(state=s) for s in ("ok", "warn", "fault", "idle")}
        for a in images:
            for b in images:
                if a < b:
                    self.assertNotEqual(images[a], images[b], (a, b))
        # the dot (top-right) takes the state colour
        for state, image in images.items():
            dot, _ = state_colours(state)
            self.assertEqual(QColor(image.pixel(W - 20 - 7, 32)).name(), dot, state)
        self.assertEqual(state_colours("fault"), ("#ef4444", "#ef4444"))
        self.assertEqual(state_colours("idle")[1], "#a1a1aa")

    def test_icon_is_drawn_in_icon_colour(self):
        image = self._card(iconColor="#ff0000")
        reds = sum(1 for y in range(18, 62) for x in range(20, 64)
                   if QColor(image.pixel(x, y)).red() > 200 and QColor(image.pixel(x, y)).blue() < 80)
        self.assertGreater(reds, 30)

    def test_two_line_title_and_long_status(self):
        self.assertNotEqual(self._card(title="PEA\n(Emergency Alarm)"), self._card(title="PEA"))
        # a typed "\n" means the same as a newline
        self.assertEqual(self._card(title="PEA\\n(Emergency Alarm)"), self._card(title="PEA\n(Emergency Alarm)"))
        # a long status stays inside the card's padding
        image = self._card(status="CHECK REQUIRED IMMEDIATELY AT THE NEXT STATION", state="warn")
        for y in range(120, H):
            for x in range(W - 18, W):
                c = QColor(image.pixel(x, y))
                self.assertFalse(c.red() > 200 and c.green() > 120 and c.blue() < 60, (x, y))


class StatusCardQmlTests(unittest.TestCase):
    def test_qml_declares_the_registry_properties(self):
        text = (REPO_ROOT / "ui" / "qml" / "Shadcn" / "ShStatusCard.qml").read_text(encoding="utf-8")
        declared = dict(re.findall(r"^\s*property\s+\w+\s+(\w+)\s*:\s*(.+)$", text, re.M))
        self.assertEqual(set(declared), {"icon", "title", "status", "state", "iconColor"})
        self.assertIn("°", declared["status"])


if __name__ == "__main__":
    unittest.main()
