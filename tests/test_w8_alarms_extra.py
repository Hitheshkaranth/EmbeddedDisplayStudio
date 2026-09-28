"""Wave 1 gate for W8 (extra coverage): CONTRACT 13.3 alarm options.

Covers the edge cases the shared `test_w3_alarms.py` does not: deadband and
priority handling in `manifest_fields`, and the `AlarmExtras` round-trip with
a deadband and with a cleared message.
"""
import os
import sys
import unittest

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit, QSpinBox  # noqa: E402

from designer.model import DesignerBinding  # noqa: E402
from designer.model.alarm_options import manifest_fields, validate_alarm_options  # noqa: E402
from designer.ui.alarm_extras import AlarmExtras  # noqa: E402


class ManifestExtras(unittest.TestCase):
    def test_deadband_default_dropped_other_kept(self):
        self.assertEqual(
            manifest_fields({"priority": 3, "latch": True, "delay_ms": 5,
                             "deadband": 0, "message": "x"}),
            {"priority": 3, "latch": True, "delay_ms": 5, "message": "x"},
        )

    def test_priority_out_of_range_dropped(self):
        for bad in (0, 5, 2.5, True, "3"):
            self.assertEqual(manifest_fields({"priority": bad, "latch": True}),
                             {"latch": True}, bad)

    def test_non_numeric_deadband_dropped(self):
        self.assertEqual(manifest_fields({"deadband": "2"}), {})


class ExtrasExtras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.x = AlarmExtras()
        self.addCleanup(self.x.deleteLater)
        self.deadband = self.x.findChild(QDoubleSpinBox, "alarmDeadband")
        self.message = self.x.findChild(QLineEdit, "alarmMessage")

    def test_deadband_roundtrip(self):
        self.x.load(DesignerBinding("a.b", critical="> 1",
                                    alarm={"deadband": 2.5}))
        self.assertEqual(self.deadband.value(), 2.5)
        out = self.x.apply_to(DesignerBinding("a.b"))
        self.assertEqual(out.alarm, {"deadband": 2.5})

    def test_clearing_fields_gives_empty(self):
        self.x.load(DesignerBinding("a.b", alarm={"priority": 2, "deadband": 1,
                                                  "delay_ms": 10, "latch": True,
                                                  "message": "M"}))
        self.deadband.setValue(0.0)
        self.message.setText("")
        out = self.x.apply_to(DesignerBinding("a.b"))
        self.assertEqual(out.alarm, {"priority": 2, "delay_ms": 10, "latch": True})


class ValidateExtras(unittest.TestCase):
    def test_valid_options_no_issues(self):
        self.assertEqual(
            [i.message for i in validate_alarm_options(
                {"priority": 3, "latch": False, "delay_ms": 0,
                 "deadband": 1.0, "message": ""}, "p")],
            [],
        )


if __name__ == "__main__":
    unittest.main()