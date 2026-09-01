"""The designer's toolbars must fit, and must not sit on top of each other.

Two separate faults, both only visible inside the Studio rather than in a
standalone workspace, because the designer gets a tab's width and not the
window's:

  * Twelve align actions plus the zoom cluster overflowed, and Qt answers
    overflow by hiding actions behind a chevron. At 1366 that swallowed
    Duplicate, Preview, Generate and Deploy -- the end of the workflow.
  * Each row was 38px tall while the line edits, combos and spin boxes inside
    it wanted more, so every field spilled out of its own bar and collided
    with the row beneath.

The pane widths below are what the Studio measured for the designer tab at
1366, 1600 and 1920 window widths.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel, QToolBar

from designer.ui import DesignerWorkspace
from designer.ui.designer_workspace import SpinBox

# Designer pane widths inside the Studio at 1366 / 1600 / 1920 window widths.
STUDIO_PANE_WIDTHS = (1328, 1562, 1882)


class ToolbarLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def settle(self, ms=250):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def workspace(self, width):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.resize(width, 860)
        workspace.show()
        self.settle(400)
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        self.settle()
        return workspace

    def test_no_action_is_hidden_at_any_studio_width(self):
        for width in STUDIO_PANE_WIDTHS:
            workspace = self.workspace(width)
            for bar in workspace.findChildren(QToolBar):
                for act in bar.actions():
                    if act.isSeparator():
                        continue
                    button = bar.widgetForAction(act)
                    if button is None:
                        continue
                    with self.subTest(width=width, bar=bar.objectName(), action=act.text()):
                        self.assertLessEqual(
                            button.x() + button.width(), bar.width(),
                            "%r overflows %s at pane width %d"
                            % (act.text(), bar.objectName(), width))

    def test_every_field_sits_inside_its_own_row(self):
        """A field taller than its bar bleeds into the row below it."""
        workspace = self.workspace(STUDIO_PANE_WIDTHS[0])
        fields = (workspace.project_name, workspace.pages, workspace.screen_width,
                  workspace.screen_height, workspace.screen_theme)
        for field in fields:
            bar = field.parent()
            with self.subTest(field=field.objectName() or type(field).__name__):
                self.assertGreaterEqual(field.y(), 0)
                self.assertLessEqual(field.y() + field.height(), bar.height())

    def test_labels_are_centred_on_their_fields(self):
        """A label riding above its own field is what the collision looked like."""
        workspace = self.workspace(STUDIO_PANE_WIDTHS[0])
        fields = {workspace.project_name, workspace.pages, workspace.screen_width,
                  workspace.screen_height, workspace.screen_theme}
        for bar in workspace.findChildren(QToolBar):
            centres = [c.y() + c.height() / 2
                       for c in bar.findChildren(QLabel) if c.text()]
            centres += [f.y() + f.height() / 2 for f in fields if f.parent() is bar]
            if len(centres) < 2:
                continue
            with self.subTest(bar=bar.objectName()):
                self.assertLessEqual(max(centres) - min(centres), 2,
                                     "labels and fields are not on one baseline")

    def test_undo_label_does_not_grow_with_the_last_command(self):
        """createUndoAction rewrites the text, which moved every button after it."""
        workspace = self.workspace(STUDIO_PANE_WIDTHS[0])
        undo = next(a for a in workspace.findChildren(QToolBar)[0].actions()
                    if a.text() == "Undo")

        workspace.add_widget("Rectangle")
        workspace.add_widget("ShCard")

        self.assertEqual(undo.text(), "Undo")
        self.assertIn("Add", undo.toolTip())

    def test_the_align_menu_offers_every_mode(self):
        workspace = self.workspace(STUDIO_PANE_WIDTHS[0])
        entries = [a for a in workspace.align_menu.actions() if not a.isSeparator()]
        self.assertEqual(len(entries), 10)

    def test_the_three_rows_do_not_overlap(self):
        workspace = self.workspace(STUDIO_PANE_WIDTHS[0])
        bars = sorted(workspace.findChildren(QToolBar), key=lambda b: b.y())
        for upper, lower in zip(bars, bars[1:]):
            with self.subTest(upper=upper.objectName(), lower=lower.objectName()):
                self.assertLessEqual(upper.y() + upper.height(), lower.y())


if __name__ == "__main__":
    unittest.main()


class ScrollingPastAnEditorMustNotEditIt(unittest.TestCase):
    """The wheel belongs to the panel, not to whatever it passes over.

    Qt hands a wheel event to the widget under the pointer whether or not it
    is focused, so scrolling the designer silently changed the first spin box
    or combo the pointer crossed. On the canvas bar those fields are the
    design surface: two notches over W moved a 1280 px design to 1278, the
    canvas redrew at the new size, and nothing reported it -- the kind of edit
    that is found after a deploy, on the panel, by someone else.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _workspace(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        return workspace

    def _scroll(self, widget, notches=1):
        event = QWheelEvent(
            QPointF(widget.rect().center()),
            QPointF(widget.mapToGlobal(widget.rect().center())),
            QPoint(0, 0), QPoint(0, 120 * notches),
            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
        )
        QApplication.sendEvent(widget, event)

    def test_scrolling_over_the_width_leaves_the_design_target_alone(self):
        workspace = self._workspace()
        before = workspace.project.screen.width

        for _ in range(2):
            self._scroll(workspace.screen_width)

        self.assertEqual(workspace.screen_width.value(), before)
        self.assertEqual(workspace.project.screen.width, before)

    def test_scrolling_over_the_theme_leaves_it_alone(self):
        """A silently flipped colour mode ships to the panel like any other."""
        workspace = self._workspace()
        before = workspace.screen_theme.currentText()

        self._scroll(workspace.screen_theme)

        self.assertEqual(workspace.screen_theme.currentText(), before)

    def test_a_focused_editor_still_takes_the_wheel(self):
        """The guard is about accidents, not about disabling the control."""
        # The offscreen plugin never activates a window, so real keyboard focus
        # cannot be handed out here. The guard's decision is what matters, so
        # the answer it asks for is the thing to control.
        workspace = self._workspace()
        before = workspace.screen_height.value()

        with mock.patch.object(SpinBox, "hasFocus", return_value=True):
            self._scroll(workspace.screen_height)

        self.assertNotEqual(workspace.screen_height.value(), before)
