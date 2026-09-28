"""Wave 1 gate for W1 (FROZEN): CONTRACT 13.1 in the Designer -- model helpers,
validation, and the inspector's ActionExtras."""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit, QListWidget, QPushButton, QSpinBox  # noqa: E402

from designer.model import DesignerAction, DesignerProject, DesignerWidget  # noqa: E402
from designer.model.actions_v2 import action_tags, truthy, validate_action  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from designer.ui.action_extras import ActionExtras  # noqa: E402


def msgs(issues):
    return [i.message for i in issues]


class Truthy(unittest.TestCase):
    def test_rule(self):
        for value, want in ((True, True), (False, False), (0, False), (0.0, False), (-2, True),
                            ("", False), ("false", False), ("0", False), ("RUN", True), (None, False),
                            ([], False), ([1], True)):
            self.assertIs(truthy(value), want, value)


class Validation(unittest.TestCase):
    def check(self, action, signal="clicked"):
        return msgs(validate_action(action, signal, "p", {"main", "p2"}))

    def test_back_is_always_fine(self):
        self.assertEqual(self.check(DesignerAction("back")), [])

    def test_tag_kinds_need_a_tag(self):
        for kind in ("toggle", "increment", "decrement"):
            self.assertEqual(self.check(DesignerAction(kind, "Pump.Run")),
                             ["action tag 'Pump.Run' is not a lowercase dotted tag name"])
            self.assertEqual(self.check(DesignerAction(kind, "pump.run")), [])

    def test_step_and_range(self):
        self.assertIn("step must be a positive number", self.check(DesignerAction("increment", "a.b", step=0)))
        self.assertIn("step must be a positive number", self.check(DesignerAction("decrement", "a.b", step=float("nan"))))
        self.assertIn("min must not be greater than max",
                      self.check(DesignerAction("increment", "a.b", min=10, max=5)))
        self.assertEqual(self.check(DesignerAction("increment", "a.b", step=0.5, min=0, max=5)), [])

    def test_ack_and_shelve(self):
        self.assertEqual(self.check(DesignerAction("ack", "")),
                         ["ack and shelve need a tag unless the signal is alarmActivated"])
        self.assertEqual(self.check(DesignerAction("ack", ""), signal="alarmActivated"), [])
        self.assertEqual(self.check(DesignerAction("ack", "*")), [])
        self.assertEqual(self.check(DesignerAction("ack", "BAD")),
                         ["action tag 'BAD' is not a lowercase dotted tag name"])
        self.assertIn("shelve ms must be 1..86400000", self.check(DesignerAction("shelve", "a.b", ms=0)))
        self.assertEqual(self.check(DesignerAction("shelve", "a.b", ms=600000)), [])

    def test_legacy_kinds_are_not_its_business(self):
        self.assertEqual(self.check(DesignerAction("write", "NOT OK")), [])


class Tags(unittest.TestCase):
    def test_action_tags(self):
        self.assertEqual(action_tags(DesignerAction("toggle", "d.run")), {"d.run"})
        self.assertEqual(action_tags(DesignerAction("increment", "s.set")), {"s.set"})
        self.assertEqual(action_tags(DesignerAction("ack", "*")), set())
        self.assertEqual(action_tags(DesignerAction("ack", "")), set())
        self.assertEqual(action_tags(DesignerAction("shelve", "a.t")), {"a.t"})
        self.assertEqual(action_tags(DesignerAction("back")), set())

    def test_project_required_tags_and_validation(self):
        project = DesignerProject.from_dict({"version": 1, "pages": [{"id": "main", "widgets": [
            {"type": "ShButton", "id": "b", "geometry": {"x": 0, "y": 0, "width": 100, "height": 40},
             "actions": {"clicked": [{"kind": "write", "tag": "a.x", "value": 1},
                                     {"kind": "toggle", "tag": "d.run"},
                                     {"kind": "increment", "tag": "s.set", "step": 0}]}}]}]})
        self.assertEqual(project.required_tags(), ["a.x", "d.run", "s.set"])
        issues = project.validate(default_registry())
        self.assertIn("pages[0].b.actions.clicked[2]", [i.path for i in issues])
        self.assertIn("step must be a positive number", msgs(issues))


class Extras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.x = ActionExtras()
        self.addCleanup(self.x.deleteLater)
        self.step = self.x.findChild(QDoubleSpinBox, "extraStep")
        self.min = self.x.findChild(QLineEdit, "extraMin")
        self.max = self.x.findChild(QLineEdit, "extraMax")
        self.ms = self.x.findChild(QSpinBox, "extraMs")
        self.confirm = self.x.findChild(QLineEdit, "extraConfirm")
        self.then = self.x.findChild(QListWidget, "extraThen")
        self.add = self.x.findChild(QPushButton, "extraAddThen")
        self.clear = self.x.findChild(QPushButton, "extraClearThen")

    def test_fields_exist(self):
        for field in (self.step, self.min, self.max, self.ms, self.confirm, self.then, self.add, self.clear):
            self.assertIsNotNone(field)

    def test_visibility_follows_kind(self):
        self.x.show()
        self.x.set_kind("increment")
        self.assertTrue(self.step.isVisibleTo(self.x) and self.min.isVisibleTo(self.x))
        self.assertFalse(self.ms.isVisibleTo(self.x))
        self.x.set_kind("shelve")
        self.assertTrue(self.ms.isVisibleTo(self.x))
        self.assertFalse(self.step.isVisibleTo(self.x))
        self.x.set_kind("write")
        self.assertFalse(self.step.isVisibleTo(self.x) or self.ms.isVisibleTo(self.x))
        self.assertTrue(self.confirm.isVisibleTo(self.x))

    def test_load_and_apply(self):
        loaded = DesignerAction("increment", "s.set", step=2.5, min=0, max=None, confirm="Sure?",
                                then=[DesignerAction("pulse", "a.horn", ms=100)])
        self.x.set_kind("increment")
        self.x.load(loaded)
        self.assertEqual(self.step.value(), 2.5)
        self.assertEqual(self.min.text(), "0")                  # "%g"
        self.assertEqual(self.max.text(), "")
        self.assertEqual(self.confirm.text(), "Sure?")
        self.assertEqual(self.then.count(), 1)
        self.assertEqual(self.then.item(0).text(), "pulse a.horn")
        self.max.setText("oops")
        out = self.x.apply_to(DesignerAction("increment", "s.set"))
        self.assertEqual((out.step, out.min, out.max, out.confirm), (2.5, 0.0, None, "Sure?"))
        self.assertEqual([(a.kind, a.tag) for a in out.then], [("pulse", "a.horn")])

    def test_add_and_clear_steps(self):
        self.x.set_kind("write")
        self.x.load(DesignerAction("write", "a.x", value=1))
        self.add.click()
        out = self.x.apply_to(DesignerAction("write", "a.x", value=1))
        self.assertEqual(len(out.then), 1)
        self.assertEqual((out.then[0].kind, out.then[0].tag, out.then[0].then), ("write", "a.x", []))
        self.clear.click()
        self.assertEqual(self.x.apply_to(DesignerAction("write", "a.x")).then, [])

    def test_shelve_ms(self):
        self.x.set_kind("shelve")
        self.x.load(DesignerAction("shelve", "a.t", ms=600000))
        self.assertEqual(self.ms.value(), 600000)
        self.ms.setValue(1000)
        self.assertEqual(self.x.apply_to(DesignerAction("shelve", "a.t")).ms, 1000)

    def test_apply_does_not_modify_its_argument(self):
        self.x.set_kind("write")
        self.confirm.setText("Go?")
        original = DesignerAction("write", "a.x")
        out = self.x.apply_to(original)
        self.assertEqual(original.confirm, "")
        self.assertEqual(out.confirm, "Go?")


if __name__ == "__main__":
    unittest.main()
