"""Wave 1 gate for W3 (FROZEN): CONTRACT 13.3 in the Designer and the shared
manifest validator -- alarm options, manifest entries, AlarmExtras."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox  # noqa: E402

from designer.model import DesignerBinding, DesignerProject  # noqa: E402
from designer.model.alarm_options import manifest_fields, validate_alarm_options  # noqa: E402
from designer.ui.alarm_extras import AlarmExtras  # noqa: E402
from schema.manifest import validate_bundle  # noqa: E402


def msgs(options):
    return [i.message for i in validate_alarm_options(options, "p")]


class Options(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(msgs({"priority": 2, "latch": True, "delay_ms": 1500, "deadband": 0.5,
                               "message": "Coolant hot"}), [])
        self.assertEqual(msgs({}), [])

    def test_each_rule(self):
        self.assertEqual(msgs({"colour": "red"}), ["unknown alarm option 'colour'"])
        for bad in (0, 5, 2.5, True, "1"):
            self.assertEqual(msgs({"priority": bad}), ["priority must be 1..4"], bad)
        self.assertEqual(msgs({"latch": 1}), ["latch must be true or false"])
        for bad in (-1, 600001, 1.5, False):
            self.assertEqual(msgs({"delay_ms": bad}), ["delay_ms must be 0..600000"], bad)
        for bad in (-0.1, "2", True, float("nan")):
            self.assertEqual(msgs({"deadband": bad}), ["deadband must be a number >= 0"], bad)
        self.assertEqual(msgs({"message": 3}), ["message must be text"])

    def test_manifest_fields(self):
        self.assertEqual(manifest_fields({}), {})
        self.assertEqual(manifest_fields({"priority": 2}), {"priority": 2})
        self.assertEqual(manifest_fields({"latch": False, "delay_ms": 0, "deadband": 0, "message": ""}), {})
        got = manifest_fields({"message": "M", "deadband": 1, "latch": True, "priority": 4,
                               "delay_ms": 10, "bogus": 1, })
        self.assertEqual(list(got), ["priority", "latch", "delay_ms", "deadband", "message"])
        self.assertEqual(manifest_fields({"priority": 9, "latch": True}), {"latch": True})


class ProjectAlarms(unittest.TestCase):
    def test_merged_into_the_manifest_entry(self):
        project = DesignerProject.from_dict({"version": 1, "pages": [{"id": "main", "widgets": [
            {"type": "ShGauge", "id": "g", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
             "properties": {"label": "EGT"},
             "bindings": {"value": {"tag": "eng.egt", "critical": "> 900",
                                    "alarm": {"priority": 1, "latch": True, "delay_ms": 2000}}}}]}]})
        (entry,) = project.alarms()
        self.assertEqual(entry["tag"], "eng.egt")
        self.assertEqual((entry["priority"], entry["latch"], entry["delay_ms"]), (1, True, 2000))
        self.assertEqual(entry["critical"], {"op": ">", "value": 900.0})
        # round-trips on disk, and a binding without options saves as before
        saved = project.to_dict()["pages"][0]["widgets"][0]["bindings"]["value"]
        self.assertEqual(saved["alarm"], {"priority": 1, "latch": True, "delay_ms": 2000})
        self.assertNotIn("alarm", DesignerBinding("a.b").to_dict())

    def test_project_validation_reports_options(self):
        project = DesignerProject.from_dict({"version": 1, "pages": [{"id": "main", "widgets": [
            {"type": "ShGauge", "id": "g", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
             "bindings": {"value": {"tag": "eng.egt", "critical": "> 900", "alarm": {"priority": 7}}}}]}]})
        issues = project.validate()
        self.assertIn(("pages[0].g.bindings.value.alarm", "priority must be 1..4"),
                      [(i.path, i.message) for i in issues])


class ManifestValidator(unittest.TestCase):
    def verdict(self, alarm):
        with tempfile.TemporaryDirectory() as d:
            manifest = {"schema": 1, "name": "m", "version": "1.0.0", "entry": "project.edsui",
                        "runtime": "edsui", "alarms": [alarm]}
            Path(d, "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            Path(d, "project.edsui").write_text('{"version":1,"pages":[{"id":"main","widgets":[]}]}',
                                                encoding="utf-8")
            return validate_bundle(d)

    def test_new_keys_accepted(self):
        ok, messages = self.verdict({"tag": "a.b", "critical": {"op": ">", "value": 1},
                                     "priority": 2, "latch": True, "delay_ms": 100,
                                     "deadband": 1.5, "message": "Hot"})
        self.assertTrue(ok, messages)

    def test_new_keys_checked(self):
        for key, bad, word in (("priority", 0, "priority"), ("latch", "yes", "latch"),
                               ("delay_ms", 700000, "delay_ms"), ("deadband", -1, "deadband"),
                               ("message", 5, "message")):
            ok, messages = self.verdict({"tag": "a.b", "critical": {"op": ">", "value": 1}, key: bad})
            self.assertFalse(ok, key)
            self.assertTrue(any("alarms[0]" in m and word in m for m in messages), messages)


class Extras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.x = AlarmExtras()
        self.addCleanup(self.x.deleteLater)
        self.priority = self.x.findChild(QComboBox, "alarmPriority")
        self.latch = self.x.findChild(QCheckBox, "alarmLatch")
        self.delay = self.x.findChild(QSpinBox, "alarmDelay")
        self.deadband = self.x.findChild(QDoubleSpinBox, "alarmDeadband")
        self.message = self.x.findChild(QLineEdit, "alarmMessage")

    def test_fields(self):
        for field in (self.priority, self.latch, self.delay, self.deadband, self.message):
            self.assertIsNotNone(field)
        self.assertEqual([self.priority.itemText(i) for i in range(self.priority.count())],
                         ["Auto", "1", "2", "3", "4"])
        self.assertEqual((self.delay.minimum(), self.delay.maximum()), (0, 600000))

    def test_roundtrip(self):
        self.x.load(DesignerBinding("a.b", critical="> 1",
                                    alarm={"priority": 2, "latch": True, "delay_ms": 500, "message": "M"}))
        self.assertEqual(self.priority.currentText(), "2")
        self.assertTrue(self.latch.isChecked())
        self.assertEqual(self.delay.value(), 500)
        self.assertEqual(self.message.text(), "M")
        out = self.x.apply_to(DesignerBinding("a.b"))
        self.assertEqual(out.alarm, {"priority": 2, "latch": True, "delay_ms": 500, "message": "M"})

    def test_defaults_give_empty_dict(self):
        self.x.load(DesignerBinding("a.b"))
        self.assertEqual(self.priority.currentText(), "Auto")
        self.assertEqual(self.x.apply_to(DesignerBinding("a.b", alarm={"latch": True})).alarm, {})

    def test_argument_not_modified(self):
        original = DesignerBinding("a.b")
        self.x.load(original)
        self.latch.setChecked(True)
        out = self.x.apply_to(original)
        self.assertEqual(original.alarm, {})
        self.assertEqual(out.alarm, {"latch": True})


if __name__ == "__main__":
    unittest.main()
