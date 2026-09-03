"""Dragging a widget onto a container must actually put it in the container.

The canvas only ever emitted a geometry edit on mouse release, so a widget
dragged onto a Card merely *looked* as though it had joined it: the model kept
it a page-level sibling and the generator emitted it outside the container.
Dragging a child back out was equally inert. Dropping from the palette worked,
which is what made the gap easy to miss.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from designer.canvas.designer_view import MIME_TYPE
from designer.ui import DesignerWorkspace


class ReparentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def workspace(self):
        # new_ui() prompts for a project name when visible, so build a fresh
        # workspace per test rather than resetting one.
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(tempfile.mkdtemp(), {"name": "qc", "version": "1.0.0"})
        return workspace

    def drop(self, workspace, widget_type, x, y):
        """A palette drop, through the view's real dropEvent."""
        mime = QMimeData()
        mime.setData(MIME_TYPE, widget_type.encode("utf-8"))
        point = workspace.view.mapFromScene(QPointF(x, y))
        workspace.view.dropEvent(QDropEvent(QPointF(point), Qt.CopyAction, mime,
                                            Qt.LeftButton, Qt.NoModifier))

    def drag(self, workspace, widget_id, scene_x, scene_y):
        """A real press / move / release on the canvas item."""
        item = workspace.scene.item_for_id(widget_id)
        press = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.GraphicsSceneMousePress)
        press.setButton(Qt.LeftButton)
        press.setButtons(Qt.LeftButton)
        press.setPos(QPointF(4, 4))
        item.mousePressEvent(press)
        item.setPos(scene_x, scene_y)
        release = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.GraphicsSceneMouseRelease)
        release.setButton(Qt.LeftButton)
        release.setButtons(Qt.NoButton)
        release.setPos(QPointF(4, 4))
        item.mouseReleaseEvent(release)

    def click(self, workspace, widget_id):
        """A press and release on the item, with nothing moved in between."""
        item = workspace.scene.item_for_id(widget_id)
        for kind in (QGraphicsSceneMouseEvent.GraphicsSceneMousePress,
                     QGraphicsSceneMouseEvent.GraphicsSceneMouseRelease):
            press = kind == QGraphicsSceneMouseEvent.GraphicsSceneMousePress
            event = QGraphicsSceneMouseEvent(kind)
            event.setButton(Qt.LeftButton)
            event.setButtons(Qt.LeftButton if press else Qt.NoButton)
            event.setPos(QPointF(item.rect().width() / 2, item.rect().height() / 2))
            (item.mousePressEvent if press else item.mouseReleaseEvent)(event)

    def _card_centre(self, workspace, card):
        item = workspace.scene.item_for_id(card.id)
        return item.mapToScene(item.boundingRect().center())

    def _card_and_loose_text(self):
        workspace = self.workspace()
        self.drop(workspace, "ShCard", 300, 80)
        card = workspace.current_page.widgets[0]
        self.drop(workspace, "Text", 40, 400)
        text = next(w for w in workspace.current_page.widgets if w.type == "Text")
        return workspace, card, text

    def test_a_widget_dragged_onto_a_container_joins_it(self):
        workspace, card, text = self._card_and_loose_text()
        centre = self._card_centre(workspace, card)

        self.drag(workspace, text.id, centre.x() - 20, centre.y() - 10)

        self.assertEqual(len(card.children), 1)
        self.assertEqual(len(workspace.current_page.widgets), 1)

    def test_the_reparented_child_is_nested_in_the_generated_qml(self):
        workspace, card, text = self._card_and_loose_text()
        centre = self._card_centre(workspace, card)

        self.drag(workspace, text.id, centre.x(), centre.y())

        qml = workspace.generator.generate(workspace.project)["Main.qml"]
        self.assertLess(qml.index("ShCard {"), qml.index("Text {"))

    def test_the_child_keeps_container_local_coordinates(self):
        workspace, card, text = self._card_and_loose_text()
        centre = self._card_centre(workspace, card)

        self.drag(workspace, text.id, centre.x(), centre.y())

        child = card.children[0]
        self.assertGreaterEqual(child.geometry["x"], 0)
        self.assertLessEqual(child.geometry["x"], card.geometry["width"])

    def test_reparenting_is_undoable_and_redoable(self):
        workspace, card, text = self._card_and_loose_text()
        centre = self._card_centre(workspace, card)
        self.drag(workspace, text.id, centre.x(), centre.y())

        workspace.undo_stack.undo()
        self.assertEqual(len(card.children), 0)
        self.assertEqual(len(workspace.current_page.widgets), 2)

        workspace.undo_stack.redo()
        self.assertEqual(len(card.children), 1)

    def test_a_child_dragged_out_returns_to_the_page(self):
        workspace = self.workspace()
        self.drop(workspace, "ShCard", 60, 60)
        card = workspace.current_page.widgets[0]
        self.drop(workspace, "Text", 120, 120)
        self.assertEqual(len(card.children), 1)

        self.drag(workspace, card.children[0].id, 600, 500)

        self.assertEqual(len(card.children), 0)
        self.assertEqual(len(workspace.current_page.widgets), 2)

    def test_a_container_cannot_be_dropped_into_itself(self):
        workspace = self.workspace()
        self.drop(workspace, "ShCard", 60, 60)
        card = workspace.current_page.widgets[0]
        centre = self._card_centre(workspace, card)

        self.drag(workspace, card.id, centre.x(), centre.y())

        self.assertEqual(len(workspace.current_page.widgets), 1)
        self.assertEqual(len(card.children), 0)

    def test_a_locked_widget_does_not_reparent(self):
        workspace, card, text = self._card_and_loose_text()
        text.locked = True
        workspace._load_page()
        centre = self._card_centre(workspace, card)

        self.drag(workspace, text.id, centre.x(), centre.y())

        self.assertEqual(len(card.children), 0)

    def test_a_palette_drop_still_nests_into_a_nested_container(self):
        workspace = self.workspace()
        self.drop(workspace, "ShCard", 40, 40)
        outer = workspace.current_page.widgets[0]
        self.drop(workspace, "Column", 80, 80)
        inner = outer.children[0]
        item = workspace.scene.item_for_id(inner.id)
        centre = item.mapToScene(item.boundingRect().center())

        self.drop(workspace, "Text", centre.x(), centre.y())

        self.assertEqual(len(inner.children), 1)
        self.assertEqual(len(workspace.current_page.widgets), 1)

    def test_clicking_a_widget_over_a_container_does_not_reparent_it(self):
        """Selecting is not dropping.

        The release handler ran its drop-target search on every release, so
        merely clicking a label that overlaps a Card moved the label into the
        Card -- a structural edit the author never asked for.
        """
        workspace, card, text = self._card_and_loose_text()
        centre = self._card_centre(workspace, card)
        text.geometry["x"], text.geometry["y"] = centre.x(), centre.y()
        workspace._load_page()
        edits = workspace.undo_stack.count()

        self.click(workspace, text.id)

        self.assertEqual(len(card.children), 0)
        self.assertEqual(workspace.undo_stack.count(), edits,
                         "selecting a widget pushed an edit onto the undo stack")

    def test_clicking_a_widget_leaves_its_off_grid_position_alone(self):
        workspace, card, text = self._card_and_loose_text()
        text.geometry["x"], text.geometry["y"] = 137, 249
        workspace._load_page()

        self.click(workspace, text.id)

        self.assertEqual(text.geometry["x"], 137)
        self.assertEqual(text.geometry["y"], 249)

    def test_clicking_a_child_leaves_it_in_its_container(self):
        workspace = self.workspace()
        self.drop(workspace, "ShCard", 60, 60)
        card = workspace.current_page.widgets[0]
        self.drop(workspace, "Text", 120, 120)
        child = card.children[0]

        self.click(workspace, child.id)

        self.assertEqual([c.id for c in card.children], [child.id])
        self.assertEqual(len(workspace.current_page.widgets), 1)


if __name__ == "__main__":
    unittest.main()
