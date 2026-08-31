"""Align, size-match, distribute and z-order all belong on the undo stack.

They used to rewrite the geometry dicts in place and never push a command. The
damage was worse than a missing undo: the toolbar sits next to Undo, so Ctrl+Z
after an align undid whatever came *before* it and left the align standing,
and from there the stack and the model disagreed about the design.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from designer.ui import DesignerWorkspace

ALIGN_MODES = ("left", "right", "top", "bottom", "hcenter", "vcenter",
               "same_width", "same_height", "distribute_h", "distribute_v")


class ArrangeUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def workspace(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        # Deliberately three different sizes: with equal ones, same_width and
        # same_height are correctly no-ops and prove nothing.
        workspace.add_widget("Rectangle", 10, 10)
        workspace.add_widget("ShGauge", 200, 150)
        workspace.add_widget("ShButton", 400, 300)
        for model in workspace.current_page.widgets:
            workspace.scene.item_for_id(model.id).setSelected(True)
        return workspace

    def geometry(self, workspace):
        return [dict(m.geometry) for m in workspace.current_page.widgets]

    def test_every_arrange_mode_changes_the_design_and_undoes_cleanly(self):
        for mode in ALIGN_MODES:
            with self.subTest(mode=mode):
                workspace = self.workspace()
                before = self.geometry(workspace)

                workspace.align(mode)
                after = self.geometry(workspace)
                self.assertNotEqual(before, after, "%s changed nothing" % mode)

                workspace.undo_stack.undo()
                self.assertEqual(self.geometry(workspace), before,
                                 "%s did not undo" % mode)

                workspace.undo_stack.redo()
                self.assertEqual(self.geometry(workspace), after,
                                 "%s did not redo" % mode)

    def test_align_does_not_consume_the_previous_command(self):
        """The bug that made this dangerous: Ctrl+Z hitting the wrong edit."""
        workspace = self.workspace()
        widgets = workspace.current_page.widgets
        added = len(widgets)

        workspace.align("left")
        aligned = self.geometry(workspace)
        workspace.undo_stack.undo()

        # One undo must take back the align, not the widget added before it.
        self.assertEqual(len(workspace.current_page.widgets), added)
        self.assertNotEqual(self.geometry(workspace), aligned)

    def test_a_no_op_arrange_pushes_nothing(self):
        """Matching widths that already match must not fill the undo stack."""
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        workspace.add_widget("Rectangle", 10, 10)
        workspace.add_widget("Rectangle", 300, 10)
        for model in workspace.current_page.widgets:
            workspace.scene.item_for_id(model.id).setSelected(True)
        depth = workspace.undo_stack.count()

        workspace.align("same_width")

        self.assertEqual(workspace.undo_stack.count(), depth)

    def test_bring_to_front_and_send_to_back_undo(self):
        for mode in ("front", "back"):
            with self.subTest(mode=mode):
                workspace = self.workspace()
                target = workspace.current_page.widgets[0]
                workspace.scene.clearSelection()
                workspace.scene.item_for_id(target.id).setSelected(True)
                before = target.z

                workspace.z_order(mode)
                self.assertNotEqual(target.z, before)

                workspace.undo_stack.undo()
                self.assertEqual(target.z, before)

                workspace.undo_stack.redo()
                self.assertNotEqual(target.z, before)

    def test_align_needs_at_least_two_widgets(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        workspace.add_widget("Rectangle", 10, 10)
        workspace.scene.item_for_id(workspace.current_page.widgets[0].id).setSelected(True)
        depth = workspace.undo_stack.count()

        workspace.align("left")

        self.assertEqual(workspace.undo_stack.count(), depth)


if __name__ == "__main__":
    unittest.main()
