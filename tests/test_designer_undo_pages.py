"""Page edits, nudges and paste are undo steps.

They used to edit the model behind the undo stack's back, so a later undo
replayed geometry or a page list the model no longer had.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402


class PageUndoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)

    def _page_ids(self):
        return [p.id for p in self.ws.project.pages]

    def test_new_duplicate_delete_page_undo_and_redo(self):
        start = self._page_ids()
        self.ws.new_page()
        self.ws.duplicate_page()
        self.assertEqual(len(self.ws.project.pages), len(start) + 2)
        self.ws.delete_page()
        self.assertEqual(len(self.ws.project.pages), len(start) + 1)
        self.ws.undo_stack.undo()
        self.assertEqual(len(self.ws.project.pages), len(start) + 2)
        self.ws.undo_stack.undo(); self.ws.undo_stack.undo()
        self.assertEqual(self._page_ids(), start)
        self.assertEqual(self.ws.current_page_index, 0)
        self.ws.undo_stack.redo()
        self.assertEqual(len(self.ws.project.pages), len(start) + 1)
        self.assertEqual(self.ws.current_page_index, len(start))

    def test_delete_page_undo_restores_position(self):
        self.ws.new_page(); self.ws.new_page()
        ids = self._page_ids()
        self.ws.change_page(1)
        self.ws.delete_page()
        self.assertEqual(self._page_ids(), [ids[0], ids[2]])
        self.ws.undo_stack.undo()
        self.assertEqual(self._page_ids(), ids)
        self.assertEqual(self.ws.current_page_index, 1)

    def test_nudges_merge_into_one_undo_step(self):
        self.ws.add_widget("ShButton", 100, 100)
        model = self.ws.scene.selected_models()[0]
        x0, y0 = model.geometry["x"], model.geometry["y"]
        count = self.ws.undo_stack.count()
        for _ in range(5): self.ws.nudge(1, 0)
        self.ws.nudge(0, 10)
        model = self.ws._find(model.id)
        self.assertEqual((model.geometry["x"], model.geometry["y"]), (x0 + 5, y0 + 10))
        self.assertEqual(self.ws.undo_stack.count(), count + 1)
        self.ws.undo_stack.undo()
        model = self.ws._find(model.id)
        self.assertEqual((model.geometry["x"], model.geometry["y"]), (x0, y0))

    def test_paste_of_several_widgets_is_one_step(self):
        self.ws.add_widget("ShButton", 10, 10)
        self.ws.add_widget("ShButton", 200, 10)
        self.ws.select_all()
        self.ws.copy()
        before = len(self.ws.current_page.widgets)
        count = self.ws.undo_stack.count()
        self.ws.paste()
        self.assertEqual(len(self.ws.current_page.widgets), before + 2)
        self.assertEqual(self.ws.undo_stack.count(), count + 1)
        self.ws.undo_stack.undo()
        self.assertEqual(len(self.ws.current_page.widgets), before)


if __name__ == "__main__":
    unittest.main()
