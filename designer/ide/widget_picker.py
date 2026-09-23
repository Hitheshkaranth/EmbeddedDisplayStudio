"""designer/ide/widget_picker.py -- pick a widget of the current page to see its code.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W1. See
docs/CODE_SECTION.md.

A list of the current page's widgets (nested widgets indented under their
container, in page order), each row a small preview thumbnail, the widget id
and its type. Clicking a row selects that widget in the Designer
(workspace.select_widget); the Code section's Design tab follows the
Designer's selection, so the row's code and preview appear there. The row of
the widget selected in the Designer is highlighted, so selecting on the
canvas moves the highlight here too.

Thumbnails come from the workspace's renderer, the same one the canvas and
the Design tab use: workspace.scene.qml_previews.image_for(widget, w, h,
theme) returns a QImage, or None with a render scheduled, in which case its
`ready(key)` signal fires later and the picker fills that row in (look the
thumbnails up again on ready; do not rebuild the list). The renderer may be
None, or return None forever when previews are off: the row then shows the
type's initial letter on a neutral tile. Thumbnails are fitted into
THUMB_SIZE, aspect kept, rendered at the widget's own geometry size.

The list is rebuilt on workspace.designChanged and workspace.pageChanged,
keeping the scroll position; selection highlight follows
workspace.scene.selectionIdsChanged. A filter field on top narrows rows by id
or type (case-insensitive substring).
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QLineEdit, QListWidget, QListWidgetItem, QStyledItemDelegate, QVBoxLayout,
    QWidget,
)

from designer.ide.project_files import _rgba, color

THUMB_SIZE = QSize(56, 40)

# Nesting depth of the row's widget (0 for a page-level widget).
_DEPTH_ROLE = Qt.UserRole + 1
_INDENT_PX = 16


class _IndentDelegate(QStyledItemDelegate):
    """Shifts a row right by its nesting depth; a QListWidget has no tree
    indentation of its own."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        depth = int(index.data(_DEPTH_ROLE) or 0)
        if depth:
            option.rect = option.rect.adjusted(depth * _INDENT_PX, 0, 0, 0)


class WidgetPicker(QWidget):
    """Signals:
        widgetPicked(str): the id of the widget the user clicked (after
        workspace.select_widget was called with it).

    Attributes tests rely on: `list` (a QListWidget; each item's
    Qt.UserRole data is the widget id), `filter_edit` (QLineEdit).
    """

    widgetPicked = Signal(str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self.setObjectName("widgetPicker")
        self._workspace = workspace
        self._theme = "dark"
        # Row id -> the fitted QImage it shows, and -> its DesignerWidget.
        self._thumbs: dict[str, QImage] = {}
        self._widgets: dict = {}
        # The renderer whose `ready` is connected; the workspace may swap it.
        self._renderer = None

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("widgetPickerFilter")
        self.filter_edit.setPlaceholderText("Filter widgets")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.list = QListWidget()
        self.list.setObjectName("widgetPickerList")
        self.list.setIconSize(THUMB_SIZE)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setItemDelegate(_IndentDelegate(self.list))
        self.list.itemClicked.connect(self._on_item_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.list, 1)

        workspace.designChanged.connect(self.rebuild)
        workspace.pageChanged.connect(self._on_page_changed)
        workspace.scene.selectionIdsChanged.connect(self._on_selection_ids)

        self.apply_theme("dark")
        self.rebuild()

    # ----------------------------------------------------------------- public

    def rebuild(self) -> None:
        """Re-reads the current page's widgets."""
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        self._thumbs.clear()
        self._widgets.clear()
        renderer = self._current_renderer()
        try:
            widgets = self._workspace.current_page.widgets
        except (AttributeError, IndexError):
            widgets = []
        for widget, depth in self._walk(widgets, 0):
            item = QListWidgetItem(f"{widget.id}\n{widget.type}")
            item.setData(Qt.UserRole, widget.id)
            item.setData(_DEPTH_ROLE, depth)
            item.setToolTip(f"{widget.id} ({widget.type})")
            self._widgets[widget.id] = widget
            image = self._fetch(widget, renderer)
            item.setIcon(QIcon(QPixmap.fromImage(image)) if image is not None
                         else self._placeholder(widget.type))
            self.list.addItem(item)
        self._apply_filter(self.filter_edit.text())
        selected = self._workspace.selected_widget()
        self._highlight(selected.id if selected is not None else "", scroll_to=False)
        # Lay the rows out now so the scroll bar has its range back.
        self.list.doItemsLayout()
        self.list.verticalScrollBar().setValue(scroll)

    def widget_ids(self) -> list[str]:
        """The ids of the rows currently shown (filter applied), top to bottom."""
        return [self.list.item(row).data(Qt.UserRole) for row in range(self.list.count())
                if not self.list.item(row).isHidden()]

    def highlighted_id(self) -> str:
        """The id of the highlighted row, or ''."""
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else ""

    def pick(self, widget_id: str) -> None:
        """What clicking the row does: workspace.select_widget(widget_id),
        highlight it, emit widgetPicked."""
        self._workspace.select_widget(widget_id)
        self._highlight(widget_id)
        self.widgetPicked.emit(widget_id)

    def thumbnail(self, widget_id: str):
        """The QImage shown for that row, or None while it has none."""
        return self._thumbs.get(widget_id)

    def set_filter(self, text: str) -> None:
        """Same as typing into filter_edit."""
        self.filter_edit.setText(text)

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = "light" if theme == "light" else "dark"
        t = self._theme
        bg, fg, border = color("background", t), color("foreground", t), color("border", t)
        primary = color("primary", t)
        self.setStyleSheet(f"""
            QWidget#widgetPicker {{ background: {bg}; }}
            QLineEdit#widgetPickerFilter {{
                background: {bg}; color: {fg}; border: none; border-bottom: 1px solid {border};
                padding: 5px 8px; font-size: 12px;
            }}
            QListWidget#widgetPickerList {{
                background: {bg}; color: {fg}; border: none; font-size: 12px; outline: 0;
            }}
            QListWidget#widgetPickerList::item {{ padding: 3px 4px; }}
            QListWidget#widgetPickerList::item:hover {{ background: {_rgba(fg, 0.06)}; }}
            QListWidget#widgetPickerList::item:selected {{
                background: {_rgba(primary, 0.16)}; color: {fg};
            }}
        """)
        # The placeholder tiles are the Studio's colours; thumbnails are the panel's.
        for row in range(self.list.count()):
            item = self.list.item(row)
            widget = self._widgets.get(item.data(Qt.UserRole))
            if widget is not None and widget.id not in self._thumbs:
                item.setIcon(self._placeholder(widget.type))

    # ---------------------------------------------------------------- private

    @classmethod
    def _walk(cls, widgets, depth):
        for widget in widgets:
            yield widget, depth
            yield from cls._walk(getattr(widget, "children", None) or [], depth + 1)

    def _current_renderer(self):
        renderer = getattr(self._workspace.scene, "qml_previews", None)
        if renderer is not self._renderer:
            if self._renderer is not None:
                try:
                    self._renderer.ready.disconnect(self._on_ready)
                except (RuntimeError, TypeError):
                    pass  # already gone with its renderer
            if renderer is not None:
                renderer.ready.connect(self._on_ready)
            self._renderer = renderer
        return renderer

    def _panel_theme(self) -> str:
        try:
            return self._workspace.project.screen.theme
        except AttributeError:
            return "dark"

    def _fetch(self, widget, renderer):
        """The fitted thumbnail (also recorded for thumbnail()), or None."""
        if renderer is None:
            return None
        geometry = widget.geometry
        image = renderer.image_for(widget, int(geometry.get("width", 0)),
                                   int(geometry.get("height", 0)), self._panel_theme())
        if image is None or image.isNull():
            return None
        fitted = image.scaled(THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._thumbs[widget.id] = fitted
        return fitted

    def _on_ready(self, _key) -> None:
        # The key is the renderer's own; asking again for every row still
        # without a picture is cheap (cache hits) and needs no key format.
        renderer = self._current_renderer()
        for row in range(self.list.count()):
            item = self.list.item(row)
            widget = self._widgets.get(item.data(Qt.UserRole))
            if widget is None or widget.id in self._thumbs:
                continue
            image = self._fetch(widget, renderer)
            if image is not None:
                item.setIcon(QIcon(QPixmap.fromImage(image)))

    def _placeholder(self, widget_type: str) -> QIcon:
        tile = QImage(THUMB_SIZE, QImage.Format_ARGB32_Premultiplied)
        tile.fill(Qt.transparent)
        painter = QPainter(tile)
        painter.setRenderHint(QPainter.Antialiasing)
        fg = QColor(color("mutedForeground", self._theme))
        fill = QColor(fg)
        fill.setAlphaF(0.14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(tile.rect().adjusted(1, 1, -1, -1), 5, 5)
        font = QFont()
        font.setPixelSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(fg)
        initial = widget_type[2:3] if widget_type.startswith("Sh") and len(widget_type) > 2 else widget_type[:1]
        painter.drawText(tile.rect(), Qt.AlignCenter, (initial or "?").upper())
        painter.end()
        return QIcon(QPixmap.fromImage(tile))

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.list.count()):
            item = self.list.item(row)
            widget = self._widgets.get(item.data(Qt.UserRole))
            shown = (not needle or widget is None or needle in widget.id.lower()
                     or needle in widget.type.lower())
            item.setHidden(not shown)

    def _highlight(self, widget_id: str, scroll_to: bool = True) -> None:
        """Selects the row of widget_id ('' or unknown: none) without the
        list's signals, so the canvas's own selection never comes back as a
        pick()."""
        self.list.blockSignals(True)
        try:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if widget_id and item.data(Qt.UserRole) == widget_id:
                    self.list.setCurrentItem(item)
                    if scroll_to:
                        self.list.scrollToItem(item)
                    return
            self.list.clearSelection()
            self.list.setCurrentRow(-1)
        finally:
            self.list.blockSignals(False)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        widget_id = item.data(Qt.UserRole)
        if widget_id:
            self.pick(widget_id)

    def _on_page_changed(self, _index: int) -> None:
        self.rebuild()

    def _on_selection_ids(self, ids: list) -> None:
        self._highlight(ids[0] if len(ids) == 1 else "")
