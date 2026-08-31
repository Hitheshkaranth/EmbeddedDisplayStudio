"""Interactive graphics canvas backed by DesignerProject objects."""
from __future__ import annotations
import os

from PySide6.QtCore import QByteArray, QDataStream, QIODevice, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QDrag, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView

from tools.hmi_deployer.bezel import bezel_logo, paint_device_bezel, screen_bezel_geometry

MIME_TYPE = "application/x-embedded-display-widget"


class DesignerItem(QGraphicsRectItem):
    HANDLE = 9.0

    def __init__(self, widget, definition, scene):
        super().__init__(0, 0, widget.geometry["width"], widget.geometry["height"])
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
        self.setOpacity(max(0.08, min(1.0, float(widget.properties.get("opacity", 1.0)))))
        self.setToolTip(f"{definition.display_name} — {widget.id}")

    def paint(self, painter, option, widget=None):
        selected = self.isSelected()
        color = QColor(self.widget_model.properties.get("backgroundColor") or
                       self.widget_model.properties.get("color") or
                       self.widget_model.properties.get("background") or "#27272a")
        painter.setBrush(QBrush(color))
        border = QColor(self.widget_model.properties.get("borderColor") or "#52525b")
        border_width = max(1, int(self.widget_model.properties.get("borderWidth", 1)))
        painter.setPen(QPen(QColor("#3b82f6") if selected else border, 2 if selected else border_width))
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
        painter.setPen(QColor(self.widget_model.properties.get("textColor") or
                              ("#f4f4f5" if color.lightness() < 128 else "#18181b")))
        label = (self.widget_model.properties.get("title") or
                 self.widget_model.properties.get("text") or self.definition.display_name)
        if not image_drawn:
            painter.drawText(self.rect().adjusted(7, 5, -7, -5), Qt.AlignCenter | Qt.TextWordWrap, str(label))
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
        if not self.widget_model.locked:
            self.setPos(round(self.pos().x() / step) * step, round(self.pos().y() / step) * step)
        after = {"x": self.pos().x(), "y": self.pos().y(),
                 "width": self.rect().width(), "height": self.rect().height()}
        if self._before != after:
            self._designer_scene.geometryEdited.emit(self.widget_model.id, self._before, after)
        self._before = None


class DesignerScene(QGraphicsScene):
    widgetDropped = Signal(str, float, float)
    geometryEdited = Signal(str, object, object)
    selectionIdsChanged = Signal(list)

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

    def add_model(self, widget):
        definition = self.registry.get(widget.type)
        if definition:
            self.addItem(DesignerItem(widget, definition, self))

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
        scene.widgetDropped.emit(widget_type, point.x(), point.y())
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
