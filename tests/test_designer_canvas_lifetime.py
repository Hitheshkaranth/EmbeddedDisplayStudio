"""Selecting a widget must not delete it from the canvas.

Qt owns a graphics item once it is in the scene -- until something asks a
top-level item for the parent it does not have. PySide reads parentItem()
returning None as "no C++ owner" and hands ownership back to Python, so an
item nothing else references is destroyed at the next collection.

Clicking a widget walks exactly that chain: the release handler asks for its
parent to decide whether the drag changed containers, and container_at() walks
each candidate's ancestors. So a single click on a freshly loaded design made
the widget -- and everything nested inside it -- disappear from the canvas,
while the model, the object tree, the preview and the deployed QML all still
had it. It came back on the next edit, because any edit reloads the page.
"""
import gc
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QApplication, QGraphicsSceneMouseEvent

from designer.ui import DesignerWorkspace

DESIGN = {
    "version": 1, "name": "demo",
    "screen": {"width": 1280, "height": 800, "background": "#101418", "theme": "dark"},
    "pages": [{"id": "main", "name": "Main", "widgets": [
        {"type": "ShCard", "id": "card1",
         "geometry": {"x": 100, "y": 100, "width": 400, "height": 300},
         "children": [{"type": "Text", "id": "inner",
                       "geometry": {"x": 20, "y": 20, "width": 140, "height": 32}}]},
        {"type": "ShButton", "id": "loner",
         "geometry": {"x": 700, "y": 600, "width": 120, "height": 40}},
    ]}]}


class ClickingAWidgetKeepsItOnTheCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def workspace(self):
        bundle = tempfile.mkdtemp()
        with open(os.path.join(bundle, "project.edsui"), "w", encoding="utf-8") as handle:
            json.dump(DESIGN, handle)
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.set_bundle(bundle, {"name": "demo", "version": "1.0.0",
                                      "screen": {"width": 1280, "height": 800}})
        return workspace

    def click(self, workspace, widget_id):
        """A press and release on the item, with no movement in between."""
        item = workspace.scene.item_for_id(widget_id)
        self.assertIsNotNone(item, f"{widget_id} is missing before the click")
        point = QPointF(item.rect().width() / 2, item.rect().height() / 2)
        for kind in (QGraphicsSceneMouseEvent.GraphicsSceneMousePress,
                     QGraphicsSceneMouseEvent.GraphicsSceneMouseRelease):
            press = kind == QGraphicsSceneMouseEvent.GraphicsSceneMousePress
            event = QGraphicsSceneMouseEvent(kind)
            event.setButton(Qt.LeftButton)
            event.setButtons(Qt.LeftButton if press else Qt.NoButton)
            event.setPos(point)
            event.setScenePos(item.mapToScene(point))
            (item.mousePressEvent if press else item.mouseReleaseEvent)(event)
        # The real application holds no reference to a canvas item, so drop
        # the local one before looking: that is what exposes a lost owner.
        del item, event
        gc.collect()

    def test_a_clicked_page_level_widget_stays_on_the_canvas(self):
        workspace = self.workspace()

        self.click(workspace, "loner")

        self.assertIsNotNone(workspace.scene.item_for_id("loner"))

    def test_a_clicked_child_keeps_its_container_on_the_canvas(self):
        workspace = self.workspace()

        self.click(workspace, "inner")

        self.assertIsNotNone(workspace.scene.item_for_id("card1"))
        self.assertIsNotNone(workspace.scene.item_for_id("inner"))

    def test_every_widget_in_the_model_still_has_an_item_after_a_click(self):
        workspace = self.workspace()

        self.click(workspace, "card1")

        for model in workspace.current_page.walk():
            with self.subTest(widget=model.id):
                self.assertIsNotNone(workspace.scene.item_for_id(model.id))


if __name__ == "__main__":
    unittest.main()
