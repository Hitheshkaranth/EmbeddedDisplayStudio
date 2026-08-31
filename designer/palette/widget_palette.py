from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from designer.canvas.designer_view import MIME_TYPE


class WidgetPalette(QTreeWidget):
    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        for category in registry.categories():
            root = QTreeWidgetItem([category])
            root.setFlags(root.flags() & ~Qt.ItemIsDragEnabled)
            self.addTopLevelItem(root)
            for definition in registry.definitions():
                if definition.category == category:
                    item = QTreeWidgetItem([definition.display_name])
                    item.setData(0, Qt.UserRole, definition.type)
                    root.addChild(item)
            root.setExpanded(True)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        widget_type = item.data(0, Qt.UserRole) if item else None
        if not widget_type:
            return
        mime = QMimeData()
        mime.setData(MIME_TYPE, widget_type.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
