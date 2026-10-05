"""Object snapping is visible, sibling-scoped, and safely bypassable."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ui import DesignerWorkspace  # noqa: E402


class SmartSnapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def workspace(self):
        bundle = tempfile.mkdtemp()
        with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "name": "snap", "version": "1.0.0",
                       "screen": {"width": 1280, "height": 800}}, handle)
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(bundle, {"name": "snap", "screen": {"width": 1280, "height": 800}})
        workspace.add_widget("Rectangle", 100, 100)
        workspace.add_widget("Rectangle", 400, 100)
        return workspace

    def test_snaps_an_edge_to_a_sibling_and_draws_a_guide(self):
        workspace = self.workspace()
        first, second = workspace.current_page.widgets
        item = workspace.scene.item_for_id(first.id)
        workspace.scene.clearSelection()
        item.setSelected(True)
        proposed = QPointF(second.geometry["x"] - item.rect().width() + 3, 100)

        position, snapped = workspace.scene.snap_item_position(item, proposed)

        self.assertTrue(snapped)
        self.assertEqual(round(position.x() + item.rect().width()), second.geometry["x"])
        self.assertTrue(workspace.scene._snap_guides)
        workspace.scene.clear_snap_guides()
        self.assertFalse(workspace.scene._snap_guides)

    def test_ctrl_style_bypass_keeps_the_proposed_position(self):
        workspace = self.workspace()
        item = workspace.scene.item_for_id(workspace.current_page.widgets[0].id)
        workspace.scene.clearSelection()
        item.setSelected(True)
        proposed = QPointF(263, 100)

        position, snapped = workspace.scene.snap_item_position(item, proposed, bypass=True)

        self.assertFalse(snapped)
        self.assertEqual(position, proposed)

    def test_multi_selection_is_not_independently_magnetised(self):
        workspace = self.workspace()
        first, second = workspace.current_page.widgets
        item = workspace.scene.item_for_id(first.id)
        workspace.scene.clearSelection()
        item.setSelected(True)
        workspace.scene.item_for_id(second.id).setSelected(True)
        proposed = QPointF(263, 100)

        position, snapped = workspace.scene.snap_item_position(item, proposed)

        self.assertFalse(snapped)
        self.assertEqual(position, proposed)


if __name__ == "__main__":
    unittest.main()
