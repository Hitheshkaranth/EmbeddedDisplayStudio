"""Wave 1 QC: defects found reviewing the swarm's deliveries, pinned."""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.model import DesignerAction, DesignerBinding  # noqa: E402


class ActionListKeepsEverything(unittest.TestCase):
    """ActionExtras once rebuilt list steps from their row text: a write lost
    its value, a pulse its ms, a navigate its page, every step its confirm."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_roundtrip(self):
        from designer.ui.action_extras import ActionExtras
        x = ActionExtras()
        self.addCleanup(x.deleteLater)
        steps = [DesignerAction("write", "a.x", value=3), DesignerAction("pulse", "a.y", ms=90),
                 DesignerAction("navigate", page="p2"), DesignerAction("toggle", "d.run", confirm="Sure?")]
        first = DesignerAction("write", "a.z", value=1, then=steps)
        x.set_kind("write")
        x.load(first)
        out = x.apply_to(DesignerAction("write", "a.z", value=1))
        self.assertEqual([a.to_dict() for a in out.then], [a.to_dict() for a in steps])
        self.assertEqual(x.then.item(2).text(), "navigate p2")

    def test_fields_are_laid_out(self):
        from designer.ui.action_extras import ActionExtras
        x = ActionExtras()
        self.addCleanup(x.deleteLater)
        self.assertIsNotNone(x.layout())
        x.set_kind("increment")
        x.resize(360, 400); x.show()
        self.app.processEvents()
        tops = sorted({w.geometry().top() for w in (x.step, x.min, x.max, x.confirm, x.then)})
        self.assertEqual(len(tops), 5, "fields overlap")


class AlarmExtrasHandEdited(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_junk_options_do_not_break_load(self):
        from designer.ui.alarm_extras import AlarmExtras
        x = AlarmExtras()
        self.addCleanup(x.deleteLater)
        x.load(DesignerBinding("a.b", alarm={"priority": 9, "delay_ms": "soon", "deadband": -3}))
        self.assertEqual(x.apply_to(DesignerBinding("a.b")).alarm, {})


if __name__ == "__main__":
    unittest.main()
