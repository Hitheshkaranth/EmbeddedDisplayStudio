"""A widget resizes from any of its eight handles, not only the bottom-right.

Each handle is pressed, dragged and released through the item's own event
handlers; the geometry the model ends up with is what the test judges.
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

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ui import DesignerWorkspace  # noqa: E402


class _Event:
    """The subset of QGraphicsSceneMouseEvent the handlers read."""

    def __init__(self, pos):
        self._pos = QPointF(*pos)
        self.accepted = False

    def pos(self):
        return self._pos

    def button(self):
        return Qt.LeftButton

    def buttons(self):
        return Qt.LeftButton

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


class ResizeHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _workspace(self):
        bundle = tempfile.mkdtemp()
        with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "name": "t", "version": "1.0.0", "entry": "generated/Main.qml",
                       "runtime": "qml", "screen": {"width": 1280, "height": 800}, "tags_required": []},
                      handle)
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(bundle, {"screen": {"width": 1280, "height": 800}})
        workspace.scene.snap_enabled = False
        workspace.add_widget("Rectangle", 100, 100)
        return workspace

    def _drag(self, workspace, handle_index, dx, dy):
        widget = workspace.current_page.widgets[0]
        item = workspace.scene.item_for_id(widget.id)
        item.setSelected(True)
        start = item._handles()[handle_index].center()
        item.mousePressEvent(_Event((start.x(), start.y())))
        self.assertEqual(item._resize_handle, handle_index)
        item.mouseMoveEvent(_Event((start.x() + dx, start.y() + dy)))
        item.mouseReleaseEvent(_Event((start.x() + dx, start.y() + dy)))
        self.app.processEvents()
        return workspace.current_page.widgets[0].geometry

    def test_every_handle_moves_only_its_own_edges(self):
        # (handle, dx, dy) -> expected (x, y, width, height) from (100, 100, 140, 90)
        cases = {
            0: ((-10, -20), (90, 80, 150, 110)),      # top-left
            1: ((0, -20), (100, 80, 140, 110)),       # top
            2: ((10, -20), (100, 80, 150, 110)),      # top-right
            3: ((-10, 0), (90, 100, 150, 90)),        # left
            4: ((10, 0), (100, 100, 150, 90)),        # right
            5: ((-10, 20), (90, 100, 150, 110)),      # bottom-left
            6: ((0, 20), (100, 100, 140, 110)),       # bottom
            7: ((10, 20), (100, 100, 150, 110)),      # bottom-right
        }
        for handle, ((dx, dy), expected) in cases.items():
            with self.subTest(handle=handle):
                workspace = self._workspace()
                geometry = self._drag(workspace, handle, dx, dy)
                got = tuple(round(geometry[k]) for k in ("x", "y", "width", "height"))
                self.assertEqual(got, expected)

    def test_dragging_a_left_edge_past_the_right_keeps_a_minimum_size(self):
        workspace = self._workspace()
        geometry = self._drag(workspace, 3, 500, 0)
        self.assertEqual(round(geometry["width"]), 12)
        self.assertEqual(round(geometry["x"] + geometry["width"]), 240)

    def test_hover_cursor_names_the_drag_direction(self):
        workspace = self._workspace()
        item = workspace.scene.item_for_id(workspace.current_page.widgets[0].id)
        item.setSelected(True)
        expectations = {0: Qt.SizeFDiagCursor, 1: Qt.SizeVerCursor, 2: Qt.SizeBDiagCursor,
                        3: Qt.SizeHorCursor, 7: Qt.SizeFDiagCursor}
        for handle, cursor in expectations.items():
            with self.subTest(handle=handle):
                self.assertEqual(item.HANDLE_CURSORS[handle], cursor)
                centre = item._handles()[handle].center()
                self.assertEqual(item._handle_at(centre), handle)

    def test_undo_restores_the_geometry(self):
        workspace = self._workspace()
        self._drag(workspace, 0, -10, -20)
        workspace.undo_stack.undo()
        geometry = workspace.current_page.widgets[0].geometry
        self.assertEqual(tuple(round(geometry[k]) for k in ("x", "y", "width", "height")),
                         (100, 100, 140, 90))


if __name__ == "__main__":
    unittest.main()
