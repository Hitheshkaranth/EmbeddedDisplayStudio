"""Interactive graphics canvas backed by DesignerProject objects."""
from __future__ import annotations
import os

from PySide6.QtCore import QByteArray, QDataStream, QIODevice, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from tools.hmi_deployer.bezel import bezel_logo, paint_device_bezel, screen_bezel_geometry

MIME_TYPE = "application/x-embedded-display-widget"

# Containers that place their own children, exactly as QtQuick does at runtime.
POSITIONERS = ("Row", "Column", "Grid")


class DesignerItem(QGraphicsRectItem):
    HANDLE = 9.0

    def __init__(self, widget, definition, scene, parent=None):
        super().__init__(0, 0, widget.geometry["width"], widget.geometry["height"], parent)
        self.widget_model = widget
        self.definition = definition
        self._designer_scene = scene
        self._resizing = False
        self._before = None
        self.setPos(widget.geometry["x"], widget.geometry["y"])
        self.setZValue(widget.z)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable |
            (QGraphicsItem.ItemIsMovable if not widget.locked else QGraphicsItem.GraphicsItemFlag(0))
        )
        self.setAcceptHoverEvents(True)
        self.positioned = False
        self.setOpacity(max(0.08, min(1.0, float(widget.properties.get("opacity", 1.0)))))
        self.setToolTip(f"{definition.display_name} — {widget.id}")

    def fill_color(self):
        """Canvas fill. On a Text, ``color`` is the glyph color, not a background."""
        properties = self.widget_model.properties
        explicit = (properties.get("backgroundColor") or properties.get("background") or
                    ("" if self.widget_model.type == "Text" else properties.get("color")))
        if not explicit and self.widget_model.type == "Text":
            return QColor(Qt.transparent)
        return QColor(explicit or "#27272a")

    def label_text(self):
        """The caption each component actually shows on the panel."""
        properties = self.widget_model.properties
        if self.widget_model.type == "Image" and not properties.get("source"):
            return "Double-click to add an image"
        for key in ("title", "label", "text", "placeholderText", "tabs"):
            value = properties.get(key)
            if value:
                return str(value)
        return self.definition.display_name

    def editable_text_property(self):
        """Return the primary caption-like property authors expect to edit in place."""
        for key in ("text", "title", "label", "placeholderText", "tabs", "description"):
            if key in self.definition.properties:
                return key
        return ""

    def paint(self, painter, option, widget=None):
        selected = self.isSelected()
        color = self.fill_color()
        painter.setBrush(QBrush(color))
        border = QColor(self.widget_model.properties.get("borderColor") or "#52525b")
        border_width = max(1, int(self.widget_model.properties.get("borderWidth", 1)))
        if selected:
            painter.setPen(QPen(QColor("#3b82f6"), 2))
        elif color.alpha() == 0:
            # An unfilled element still needs an outline to be found and grabbed.
            painter.setPen(QPen(QColor(161, 161, 170, 110), 1, Qt.DashLine))
        else:
            painter.setPen(QPen(border, border_width))
        radius = float(self.widget_model.properties.get("cornerRadius",
                       self.widget_model.properties.get("radius", 5)))
        painter.drawRoundedRect(self.rect(), radius, radius)
        image_drawn = False
        if self.widget_model.type == "Image":
            source = self.widget_model.properties.get("source", "")
            path = source if source and not self._designer_scene.project_dir else ""
            if source and self._designer_scene.project_dir:
                path = source if os.path.isabs(source) else os.path.join(
                    self._designer_scene.project_dir, source.replace('/', os.sep))
            pixmap = QPixmap(path) if path else QPixmap()
            if not pixmap.isNull():
                target = self.rect().toRect()
                mode = self.widget_model.properties.get("fillMode", "Image.PreserveAspectFit")
                aspect = Qt.IgnoreAspectRatio if mode == "Image.Stretch" else Qt.KeepAspectRatio
                scaled = pixmap.scaled(target.size(), aspect, Qt.SmoothTransformation)
                painter.drawPixmap(target.center() - scaled.rect().center(), scaled)
                image_drawn = True
        is_text = self.widget_model.type == "Text"
        painter.setPen(QColor(self.widget_model.properties.get("textColor") or
                              (self.widget_model.properties.get("color") if is_text else "") or
                              ("#f4f4f5" if color.alpha() == 0 or color.lightness() < 128 else "#18181b")))
        if not image_drawn:
            font = painter.font()
            size = self.widget_model.properties.get("fontSize")
            if size:
                font.setPixelSize(max(1, int(size)))
            font.setBold(bool(self.widget_model.properties.get("bold")))
            painter.setFont(font)
            if is_text:
                wrapping = "Wrap" in str(self.widget_model.properties.get("wrapMode", ""))
                flags = Qt.AlignLeft | Qt.AlignTop
                painter.drawText(self.rect(), flags | Qt.TextWordWrap if wrapping else flags,
                                 self.label_text())
            else:
                painter.drawText(self.rect().adjusted(7, 5, -7, -5),
                                 Qt.AlignCenter | Qt.TextWordWrap, self.label_text())
        if self.widget_model.properties.get("visible") is False:
            painter.setPen(QPen(QColor("#ef4444"), 1, Qt.DashLine))
            painter.drawLine(self.rect().topLeft(), self.rect().bottomRight())
            painter.drawLine(self.rect().topRight(), self.rect().bottomLeft())
        if selected:
            painter.setBrush(QColor("#fafafa"))
            painter.setPen(QPen(QColor("#2563eb"), 1))
            for rect in self._handles():
                painter.drawRect(rect)

    def _handles(self):
        r, h = self.rect(), self.HANDLE
        return [QRectF(x - h / 2, y - h / 2, h, h) for x, y in (
            (r.left(), r.top()), (r.center().x(), r.top()), (r.right(), r.top()),
            (r.left(), r.center().y()), (r.right(), r.center().y()),
            (r.left(), r.bottom()), (r.center().x(), r.bottom()), (r.right(), r.bottom()))]

    def hoverMoveEvent(self, event):
        self.setCursor(Qt.SizeFDiagCursor if self.isSelected() and self._handles()[-1].contains(event.pos()) else Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def contextMenuEvent(self, event):
        if not self.isSelected():
            self._designer_scene.clearSelection()
            self.setSelected(True)
        self._designer_scene.contextMenuRequested.emit(self.widget_model.id, event.screenPos())
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.definition.asset_properties:
            self._designer_scene.clearSelection()
            self.setSelected(True)
            self._designer_scene.assetRequested.emit(self.widget_model.id,
                                                     self.definition.asset_properties[0])
            event.accept()
            return
        property_name = self.editable_text_property()
        if property_name:
            self._designer_scene.clearSelection()
            self.setSelected(True)
            self._designer_scene.textRequested.emit(self.widget_model.id, property_name)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        self._before = dict(self.widget_model.geometry)
        self._resizing = self.isSelected() and self._handles()[-1].contains(event.pos())
        if self._resizing:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            point = event.pos()
            step = self._designer_scene.grid_size if self._designer_scene.snap_enabled else 1
            width = max(12, round(point.x() / step) * step)
            height = max(12, round(point.y() / step) * step)
            self.setRect(0, 0, width, height)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
        else:
            super().mouseReleaseEvent(event)
        step = self._designer_scene.grid_size if self._designer_scene.snap_enabled else 1
        if not self.widget_model.locked and not self.positioned:
            self.setPos(round(self.pos().x() / step) * step, round(self.pos().y() / step) * step)
        after = {"x": self.widget_model.geometry["x"] if self.positioned else self.pos().x(),
                 "y": self.widget_model.geometry["y"] if self.positioned else self.pos().y(),
                 "width": self.rect().width(), "height": self.rect().height()}
        # Where the drag ended decides the parent. Without this a widget
        # dragged onto a Card only *looked* as though it had joined it: the
        # model kept it a page-level sibling and the generated QML emitted it
        # outside the container. Dragging one out again was equally inert.
        target = None
        if not self.widget_model.locked and not self._resizing:
            target = self._designer_scene.container_at(
                self.mapToScene(self.rect().center()), ignore=self)
        target_id = target.widget_model.id if target is not None else ""
        parent = self.parentItem()
        current_id = parent.widget_model.id if isinstance(parent, DesignerItem) else ""
        if target_id != current_id:
            # The reparent carries the new position, so it replaces the plain
            # geometry edit rather than racing it: both reload the page, and
            # the second would act on an item the first has already rebuilt.
            local = (target.mapFromScene(self.scenePos()) if target is not None
                     else self.scenePos())
            self._designer_scene.reparentRequested.emit(
                self.widget_model.id, target_id, local.x(), local.y())
        elif self._before != after:
            self._designer_scene.geometryEdited.emit(self.widget_model.id, self._before, after)
        self._before = None


class DesignerScene(QGraphicsScene):
    widgetDropped = Signal(str, float, float, str)
    geometryEdited = Signal(str, object, object)
    selectionIdsChanged = Signal(list)
    contextMenuRequested = Signal(str, object)
    assetRequested = Signal(str, str)
    textRequested = Signal(str, str)
    reparentRequested = Signal(str, str, float, float)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.grid_size = 10
        self.grid_visible = True
        self.snap_enabled = True
        self.project = None
        self.page = None
        self._bezel_logo = bezel_logo()
        self.theme = "dark"
        self.project_dir = ""
        self.setItemIndexMethod(QGraphicsScene.BspTreeIndex)
        self.selectionChanged.connect(self._emit_selection)

    def load_page(self, project, page):
        self.clear()
        self.project, self.page = project, page
        self.update_screen_rect()
        for widget in page.widgets:
            self.add_model(widget)
        self.update()

    def update_screen_rect(self):
        """Include the physical bezel in the editable scene bounds."""
        if not self.project:
            return
        bezel, margin = screen_bezel_geometry(self.project.screen.width,
                                               self.project.screen.height)
        self.bezel_rect, self.bezel_margin = bezel, margin
        self.setSceneRect(bezel.adjusted(-12, -12, 12, 12))

    def add_model(self, widget, parent_item=None):
        definition = self.registry.get(widget.type)
        if not definition:
            return None
        item = DesignerItem(widget, definition, self, parent_item)
        if parent_item is None:
            self.addItem(item)
        for child in widget.children:
            self.add_model(child, item)
        if widget.type in POSITIONERS:
            self.layout_children(item)
        return item

    def layout_children(self, item):
        """Mirror the QtQuick positioner: Row/Column/Grid own their children's places."""
        children = [child for child in item.childItems() if isinstance(child, DesignerItem)]
        if not children:
            return
        properties = item.widget_model.properties
        spacing = max(0, int(properties.get("spacing", 0) or 0))
        for child in children:
            child.positioned = True
            child.setFlag(QGraphicsItem.ItemIsMovable, False)
        if item.widget_model.type == "Row":
            offset = 0.0
            reversed_flow = properties.get("layoutDirection") == "Qt.RightToLeft"
            for child in children:
                width = child.rect().width()
                x = item.rect().width() - offset - width if reversed_flow else offset
                child.setPos(x, 0)
                offset += width + spacing
        elif item.widget_model.type == "Column":
            offset = 0.0
            for child in children:
                child.setPos(0, offset)
                offset += child.rect().height() + spacing
        else:
            cell_width = max(child.rect().width() for child in children)
            cell_height = max(child.rect().height() for child in children)
            down = properties.get("flow") == "Grid.TopToBottom"
            span = max(1, int((properties.get("rows") if down else properties.get("columns")) or 4))
            for index, child in enumerate(children):
                row, column = (index % span, index // span) if down else (index // span, index % span)
                child.setPos(column * (cell_width + spacing), row * (cell_height + spacing))

    def container_at(self, point, ignore=None):
        """The container a drop at ``point`` lands in, or None for the page itself.

        Args:
            point: scene coordinates of the drop.
            ignore: the item being dragged, when this is a move rather than a
                new drop. Neither it nor anything inside it can become its own
                parent, so both are looked straight through.
        """
        for item in self.items(point):
            if not isinstance(item, DesignerItem):
                continue
            if ignore is not None and self._within(item, ignore):
                continue
            node = item
            while node is not None:
                if node.definition.container:
                    return node
                node = node.parentItem()
            return None
        return None

    @staticmethod
    def _within(item, ancestor):
        """True when ``item`` is ``ancestor`` or sits inside it."""
        node = item
        while node is not None:
            if node is ancestor:
                return True
            node = node.parentItem()
        return False

    def contextMenuEvent(self, event):
        super().contextMenuEvent(event)
        if not event.isAccepted():
            self.contextMenuRequested.emit("", event.screenPos())
            event.accept()

    def item_for_id(self, widget_id):
        return next((item for item in self.items() if isinstance(item, DesignerItem)
                     and item.widget_model.id == widget_id), None)

    def selected_models(self):
        return [item.widget_model for item in self.selectedItems() if isinstance(item, DesignerItem)]

    def set_theme(self, theme):
        self.theme = theme if theme in ("light", "dark") else "dark"
        self.update()

    def _emit_selection(self):
        self.selectionIdsChanged.emit([model.id for model in self.selected_models()])

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, QColor("#09090b" if self.theme == "dark" else "#e4e4e7"))
        if not self.project:
            return
        width, height = self.project.screen.width, self.project.screen.height
        paint_device_bezel(painter, self.bezel_rect, self.bezel_margin,
                            self._bezel_logo, 0)
        screen = QRectF(0, 0, width, height)
        painter.setPen(QPen(QColor("#52525b"), 1))
        painter.setBrush(QColor(self.project.screen.background))
        painter.drawRect(screen)
        if not self.grid_visible:
            return
        painter.save()
        painter.setClipRect(screen)
        grid = QColor(255, 255, 255, 24) if self.theme == "dark" else QColor(24, 24, 27, 34)
        painter.setPen(QPen(grid, 0))
        for x in range(0, width + 1, self.grid_size):
            painter.drawLine(x, 0, x, height)
        for y in range(0, height + 1, self.grid_size):
            painter.drawLine(0, y, width, y)
        painter.restore()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not self.project:
            return
        painter.setPen(QColor("#a1a1aa" if self.theme == "dark" else "#52525b"))
        label_rect = QRectF(self.bezel_rect.left() + self.bezel_margin,
                            self.bezel_rect.top(), self.project.screen.width,
                            self.bezel_margin)
        painter.drawText(label_rect, Qt.AlignHCenter | Qt.AlignVCenter,
                         f"DESIGN TARGET  ·  {self.project.screen.width} × {self.project.screen.height} px")


class DesignerView(QGraphicsView):
    zoomChanged = Signal(int)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._auto_fit = True
        self.setAcceptDrops(True)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        event.acceptProposedAction() if event.mimeData().hasFormat(MIME_TYPE) else super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME_TYPE):
            return super().dropEvent(event)
        widget_type = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
        point = self.mapToScene(event.position().toPoint())
        scene = self.scene()
        point.setX(max(0, min(point.x(), scene.project.screen.width)))
        point.setY(max(0, min(point.y(), scene.project.screen.height)))
        container = scene.container_at(point)
        if container is not None:
            local = container.mapFromScene(point)
            scene.widgetDropped.emit(widget_type, local.x(), local.y(), container.widget_model.id)
        else:
            scene.widgetDropped.emit(widget_type, point.x(), point.y(), "")
        event.acceptProposedAction()

    def set_zoom(self, percent):
        percent = max(20, min(400, int(percent)))
        self._auto_fit = False
        self.resetTransform()
        self.scale(percent / 100, percent / 100)
        self.zoomChanged.emit(percent)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            current = round(self.transform().m11() * 100)
            self.set_zoom(current + (10 if event.angleDelta().y() > 0 else -10))
            event.accept()
        else:
            super().wheelEvent(event)

    def fit_canvas(self):
        self._auto_fit = True
        self.fitInView(self.scene().sceneRect().adjusted(-10, -10, 10, 10), Qt.KeepAspectRatio)
        self.zoomChanged.emit(round(self.transform().m11() * 100))

    def showEvent(self, event):
        super().showEvent(event)
        if self._auto_fit:
            self.fit_canvas()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._auto_fit and not self.scene().sceneRect().isEmpty():
            self.fit_canvas()
