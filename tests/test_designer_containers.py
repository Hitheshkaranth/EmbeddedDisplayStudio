"""Containers have to accept children, or half the palette is decoration."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from designer.canvas.designer_view import MIME_TYPE, DesignerItem
from designer.generators import QmlGenerator
from designer.ui import DesignerWorkspace


class DesignerContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _workspace(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        return workspace

    def _drop(self, workspace, widget_type, scene_x, scene_y):
        """Drop from the palette the way the view delivers it."""
        mime = QMimeData()
        mime.setData(MIME_TYPE, widget_type.encode("utf-8"))
        position = QPointF(workspace.view.mapFromScene(QPointF(scene_x, scene_y)))
        event = QDropEvent(position, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        workspace.view.dropEvent(event)

    def test_drop_on_a_card_nests_the_widget_inside_it(self):
        workspace = self._workspace()
        workspace.add_widget("ShCard", 100, 100)
        card = workspace.current_page.widgets[0]
        self._drop(workspace, "Text", 140, 150)

        self.assertEqual(len(workspace.current_page.widgets), 1)
        self.assertEqual(len(card.children), 1)
        child = card.children[0]
        # Coordinates are container-relative, exactly as QML reads them.
        self.assertEqual((child.geometry["x"], child.geometry["y"]), (40, 50))
        item = workspace.scene.item_for_id(child.id)
        self.assertIsInstance(item.parentItem(), DesignerItem)
        self.assertEqual(item.parentItem().widget_model.id, card.id)

    def test_a_nested_child_can_be_deleted_and_duplicated(self):
        workspace = self._workspace()
        workspace.add_widget("ShCard", 0, 0)
        card = workspace.current_page.widgets[0]
        self._drop(workspace, "ShButton", 30, 30)
        child = card.children[0]

        workspace.scene.clearSelection()
        workspace.scene.item_for_id(child.id).setSelected(True)
        workspace.duplicate()
        self.assertEqual(len(card.children), 2)
        self.assertEqual(len(workspace.current_page.widgets), 1)

        workspace.scene.clearSelection()
        workspace.scene.item_for_id(card.children[1].id).setSelected(True)
        workspace.delete_selected()
        self.assertEqual(len(card.children), 1)
        workspace.undo_stack.undo()
        self.assertEqual(len(card.children), 2)

    def test_nested_children_reach_the_generated_qml(self):
        workspace = self._workspace()
        workspace.add_widget("ShCard", 0, 0)
        self._drop(workspace, "Text", 20, 20)
        qml = QmlGenerator(workspace.registry).generate(workspace.project)["Main.qml"]
        card_body = qml.split("ShCard {")[1]
        self.assertIn("Text {", card_body)

    def test_a_row_places_its_children_the_way_qtquick_will(self):
        workspace = self._workspace()
        workspace.add_widget("Row", 0, 0)
        row = workspace.current_page.widgets[0]
        self._drop(workspace, "ShButton", 200, 10)
        self._drop(workspace, "ShButton", 40, 10)
        first, second = (workspace.scene.item_for_id(child.id) for child in row.children)

        self.assertTrue(first.positioned and second.positioned)
        self.assertEqual(first.pos().x(), 0)
        # 120px default button + the Row's 8px spacing.
        self.assertEqual(second.pos().x(), 128)
        qml = QmlGenerator(workspace.registry).generate(workspace.project)["Main.qml"]
        row_body = qml.split("Row {")[1]
        self.assertNotIn("x:", row_body.split("ShButton {")[1])


if __name__ == "__main__":
    unittest.main()
