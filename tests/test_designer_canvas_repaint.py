"""A canvas item must claim every pixel it paints.

Qt repaints only the area an item reports as its boundingRect. DesignerItem is
a QGraphicsRectItem, which measures itself by its rect and its own pen -- but
paint() draws eight resize handles centred on the rect's corners and edge
midpoints, so half of each handle lands outside, and it strokes the selection
border with a 2px pen set on the painter rather than on the item.

Dragging a selected widget therefore left the outer half of every handle
painted at each position it passed through: a ghost trail of the widget that
nothing erased until the view scrolled or the page reloaded.
"""
import json
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


class BoundingRectCoversWhatIsPainted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _item(self, widget_type="Rectangle"):
        bundle = tempfile.mkdtemp()
        with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "schema": 1, "name": "t", "version": "1.0.0",
                "entry": "generated/Main.qml", "runtime": "qml",
                "screen": {"width": 1280, "height": 800}, "tags_required": [],
            }, handle)
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(bundle, {"screen": {"width": 1280, "height": 800}})
        workspace.add_widget(widget_type, 40, 40)
        item = workspace.scene.item_for_id(workspace.current_page.widgets[0].id)
        return item

    def test_every_resize_handle_is_inside_the_bounding_rect(self):
        item = self._item()
        item.setSelected(True)

        bounds = item.boundingRect()

        for index, handle in enumerate(item._handles()):
            with self.subTest(handle=index):
                self.assertTrue(
                    bounds.contains(handle),
                    f"handle {handle} is painted outside {bounds}; Qt will not "
                    f"erase it when the item moves",
                )

    def test_the_bounding_rect_is_wider_than_the_rect_itself(self):
        """The margin is the point: a rect-sized bound is the bug."""
        item = self._item()

        bounds, rect = item.boundingRect(), item.rect()

        self.assertLess(bounds.left(), rect.left())
        self.assertLess(bounds.top(), rect.top())
        self.assertGreater(bounds.right(), rect.right())
        self.assertGreater(bounds.bottom(), rect.bottom())

    def test_it_holds_for_a_resized_widget_too(self):
        """setRect must not leave the margin behind."""
        item = self._item()
        item.setSelected(True)
        item.setRect(0, 0, 320, 40)

        bounds = item.boundingRect()

        self.assertTrue(all(bounds.contains(h) for h in item._handles()))


if __name__ == "__main__":
    unittest.main()
