"""Wave 1 gate for W5 (FROZEN): CONTRACT 13.5 screen idle in the Designer --
validation, normalisation, the editor and the undoable toolbar action."""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QLabel, QSpinBox  # noqa: E402

from designer.model import DesignerProject  # noqa: E402
from designer.model.screen_idle import normalise_idle, validate_idle  # noqa: E402
from designer.ui.screen_idle_editor import ScreenIdleEditor  # noqa: E402


def msgs(idle):
    return [i.message for i in validate_idle(idle, "screen.idle")]


class Rules(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(msgs({"dimAfterS": 60, "dimPercent": 20, "offAfterS": 300}), [])
        self.assertEqual(msgs({"offAfterS": 30}), [])
        self.assertEqual(msgs({}), [])

    def test_each_rule(self):
        self.assertEqual(msgs({"sleep": 1}), ["unknown idle setting 'sleep'"])
        for bad in (-1, 1.5, True, "10"):
            self.assertEqual(msgs({"dimAfterS": bad}), ["dimAfterS must be a whole number of seconds >= 0"], bad)
            self.assertEqual(msgs({"offAfterS": bad}), ["offAfterS must be a whole number of seconds >= 0"], bad)
        for bad in (9, 101, 50.5, False):
            self.assertEqual(msgs({"dimPercent": bad}), ["dimPercent must be 10..100"], bad)
        self.assertEqual(msgs({"dimAfterS": 60, "offAfterS": 60}), ["offAfterS must be later than dimAfterS"])
        self.assertEqual(msgs({"dimAfterS": 60, "offAfterS": 0}), [])

    def test_normalise(self):
        self.assertEqual(normalise_idle({}), {})
        self.assertEqual(normalise_idle({"dimAfterS": 0, "dimPercent": 30, "offAfterS": 0}), {})
        self.assertEqual(normalise_idle({"dimAfterS": 60, "dimPercent": 30, "junk": 1}), {"dimAfterS": 60})
        self.assertEqual(normalise_idle({"dimAfterS": 60, "dimPercent": 20, "offAfterS": 300}),
                         {"dimAfterS": 60, "dimPercent": 20, "offAfterS": 300})

    def test_project_roundtrip_and_validation(self):
        project = DesignerProject.from_dict({"version": 1, "screen": {"width": 800, "height": 480,
                                             "idle": {"dimAfterS": 60, "dimPercent": 5}},
                                             "pages": [{"id": "main", "widgets": []}]})
        self.assertEqual(project.to_dict()["screen"]["idle"], {"dimAfterS": 60, "dimPercent": 5})
        self.assertIn(("screen.idle", "dimPercent must be 10..100"),
                      [(i.path, i.message) for i in project.validate()])
        self.assertNotIn("idle", DesignerProject().to_dict()["screen"])


class Editor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.e = ScreenIdleEditor()
        self.addCleanup(self.e.deleteLater)
        self.dim = self.e.findChild(QSpinBox, "idleDim")
        self.pct = self.e.findChild(QSpinBox, "idleDimPercent")
        self.off = self.e.findChild(QSpinBox, "idleOff")
        self.problem = self.e.findChild(QLabel, "idleProblem")

    def test_fields(self):
        for f in (self.dim, self.pct, self.off, self.problem):
            self.assertIsNotNone(f)
        self.assertEqual(self.dim.specialValueText(), "never")
        self.assertEqual((self.pct.minimum(), self.pct.maximum()), (10, 100))

    def test_load_value_and_problem(self):
        changes = []
        self.e.changed.connect(lambda: changes.append(1))
        self.e.load({"dimAfterS": 60, "offAfterS": 300})
        self.assertEqual((self.dim.value(), self.pct.value(), self.off.value()), (60, 30, 300))
        self.assertEqual(self.e.value(), {"dimAfterS": 60, "offAfterS": 300})
        self.off.setValue(30)
        self.assertTrue(changes)
        self.assertEqual(self.problem.text(), "offAfterS must be later than dimAfterS")
        self.off.setValue(0)
        self.assertEqual(self.problem.text(), "")
        self.e.load({})
        self.assertEqual(self.e.value(), {})


class WorkspaceAction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_undoable(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        ws = DesignerWorkspace()
        self.addCleanup(ws.close)

        def accept(dialog):
            editor = dialog.findChild(ScreenIdleEditor)
            editor.findChild(QSpinBox, "idleDim").setValue(45)
            return QDialog.DialogCode.Accepted

        self.assertTrue(ws.edit_screen_idle(dialog_exec=accept))
        self.assertEqual(ws.project.screen.idle, {"dimAfterS": 45})
        ws.undo_stack.undo()
        self.assertEqual(ws.project.screen.idle, {})
        ws.undo_stack.redo()
        self.assertEqual(ws.project.screen.idle, {"dimAfterS": 45})
        self.assertFalse(ws.edit_screen_idle(dialog_exec=lambda d: QDialog.DialogCode.Rejected))


if __name__ == "__main__":
    unittest.main()
