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
from PySide6.QtGui import QIcon, QImage, QPainter, QFont, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QLineEdit, QLabel, QVBoxLayout, QWidget


THUMB_SIZE = QSize(56, 40)


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
        self._workspace = workspace
        self._theme = "dark"
        self._filter_text = ""
        self._thumbnail_cache = {}  # widget_id -> QImage

        # List widget for widgets
        self._list = QListWidget()
        self._list.setIconSize(THUMB_SIZE)
        self._list.setUniformItemSizes(True)
        self._list.setSortingEnabled(False)
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._list.setEditTriggers(QListWidget.EditTrigger.NoEditTriggers)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.itemClicked.connect(self._on_item_clicked)

        # Filter field
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter")
        self._filter_edit.textChanged.connect(self._on_filter_changed)

        # Empty label
        self._empty_label = QLabel("")
        self._empty_label.setAlignment(Qt.AlignCenter)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._filter_edit)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._list)

        # Internal state
        self._widgets_cache = []  # full list of DesignerWidget from current page
        self._renderer = None

        # Connect workspace signals
        self._workspace.designChanged.connect(self.rebuild)
        self._workspace.pageChanged.connect(self.rebuild)
        self._workspace.scene.selectionIdsChanged.connect(self._on_selection_ids_changed)

        # Connect renderer ready signal (lazy, set up in rebuild)
        self._old_bus = None

        self.rebuild()
        self.apply_theme("dark")

    def _get_renderer(self):
        """Get the current renderer from workspace scene."""
        try:
            return self._workspace.scene.qml_previews
        except AttributeError:
            return None

    def _connect_renderer(self):
        """Connect to the current renderer's ready signal."""
        # Disconnect old bus
        if self._old_bus is not None:
            try:
                self._old_bus.ready.disconnect(self._on_thumbnail_ready)
            except Exception:
                pass

        renderer = self._get_renderer()
        if renderer is not None:
            self._old_bus = renderer._bus
            renderer.ready.connect(self._on_thumbnail_ready)

    def _on_thumbnail_ready(self, key):
        """When a thumbnail lands, fill in the row if we don't have it yet."""
        for widget in self._widgets_cache:
            wid = widget.id
            if wid not in self._thumbnail_cache:
                renderer = self._get_renderer()
                if renderer is not None:
                    img = renderer.image_for(
                        widget,
                        widget.geometry.get("width", 100),
                        widget.geometry.get("height", 40),
                        self._theme
                    )
                    if img is not None:
                        self._thumbnail_cache[wid] = img
                        self._update_item_thumbnail(wid)
                        return

    def _on_item_clicked(self, item):
        """Handle click on a list item."""
        widget_id = str(item.data(Qt.UserRole) or "")
        if widget_id:
            self.pick(widget_id)

    def _on_filter_changed(self, text):
        """Handle filter text changes."""
        self._filter_text = text
        self._build_filtered_list()

    def _on_selection_ids_changed(self, ids):
        """When the canvas selection changes, update highlight."""
        if len(ids) == 1:
            self._select_highlighted(ids[0])

    def _select_highlighted(self, widget_id):
        """Set the current item to the widget with given id."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item:
                wid = str(item.data(Qt.UserRole) or "")
                if wid == widget_id:
                    self._list.setCurrentItem(item)
                    return
        self._list.clearSelection()

    def _get_current_selection(self):
        """Get the currently selected widget id from workspace."""
        try:
            sel = self._workspace.scene.selectionIds
            if sel and len(sel) == 1:
                return sel[0]
        except AttributeError:
            pass
        return ""

    # ----------------------------------------------------------------- public

    def rebuild(self) -> None:
        """Re-reads the current page's widgets."""
        # Save scroll position
        hpos = self._list.horizontalScrollBar().value()

        # Clear and rebuild
        self._list.clear()
        self._thumbnail_cache.clear()

        try:
            page = self._workspace.current_page
        except AttributeError:
            self._widgets_cache = []
            self._empty_label.setVisible(True)
            return

        self._widgets_cache = list(page.widgets)
        self._connect_renderer()

        self._build_filtered_list()

        # Restore scroll position
        self._list.horizontalScrollBar().setValue(hpos)

    def _build_filtered_list(self):
        """Build the list, filtered by self._filter_text."""
        self._list.clear()
        self._thumbnail_cache.clear()

        # Determine which widgets match the filter
        filter_lower = self._filter_text.lower() if self._filter_text else ""

        for widget in self._widgets_cache:
            wid = widget.id
            wtype = widget.type
            if filter_lower and filter_lower not in wid.lower() and filter_lower not in wtype.lower():
                continue

            item = QListWidgetItem()
            item.setData(Qt.UserRole, wid)
            item.setText(f"{wid} ({wtype})")

            # Determine thumbnail
            renderer = self._get_renderer()
            if renderer is not None:
                img = renderer.image_for(
                    widget,
                    widget.geometry.get("width", 100),
                    widget.geometry.get("height", 40),
                    self._theme
                )
                if img is not None:
                    scaled = self._scale_thumbnail(img)
                    item.setIcon(QIcon(scaled))
                    self._thumbnail_cache[wid] = img
                else:
                    # Thumbnail not ready yet - use placeholder
                    placeholder = self._make_placeholder_icon(wtype)
                    item.setIcon(placeholder)
            else:
                # No renderer - use placeholder
                placeholder = self._make_placeholder_icon(wtype)
                item.setIcon(placeholder)

            self._list.addItem(item)

        self._empty_label.setVisible(self._list.count() == 0)

    def widget_ids(self) -> list[str]:
        """The ids of the rows currently shown (filter applied), top to bottom."""
        ids = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item:
                wid = str(item.data(Qt.UserRole) or "")
                if wid:
                    ids.append(wid)
        return ids

    def highlighted_id(self) -> str:
        """The id of the highlighted row, or ''."""
        # Check current list selection first
        current = self._list.currentItem()
        if current is not None:
            return str(current.data(Qt.UserRole) or "")
        # Fall back to workspace selection
        return self._get_current_selection()

    def pick(self, widget_id: str) -> None:
        """What clicking the row does: workspace.select_widget(widget_id),
        highlight it, emit widgetPicked."""
        self._workspace.select_widget(widget_id)
        # Directly highlight (selectionIdsChanged may not fire synchronously)
        self._select_highlighted(widget_id)
        self.widgetPicked.emit(widget_id)

    def thumbnail(self, widget_id: str):
        """The QImage shown for that row, or None while it has none."""
        return self._thumbnail_cache.get(widget_id)

    def set_filter(self, text: str) -> None:
        """Same as typing into filter_edit."""
        self._filter_edit.blockSignals(True)
        self._filter_edit.setText(text)
        self._filter_edit.blockSignals(False)
        self._filter_text = text
        self._build_filtered_list()

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = theme
        if theme == "light":
            self.setStyleSheet("""
                QListWidget {
                    background: #ffffff;
                    color: #000000;
                    border: 1px solid #cccccc;
                    font-size: 12px;
                }
                QListWidget::item:selected {
                    background: #d0e0ff;
                    color: #000000;
                }
                QListWidget::item:hover {
                    background: #e8e8e8;
                }
                QLineEdit {
                    background: #ffffff;
                    color: #000000;
                    border: 1px solid #cccccc;
                    border-radius: 3px;
                    padding: 2px 8px;
                }
                QLabel {
                    color: #888888;
                }
            """)
        else:
            self.setStyleSheet("""
                QListWidget {
                    background: #1e1e1e;
                    color: #cccccc;
                    border: 1px solid #3c3c3c;
                    font-size: 12px;
                }
                QListWidget::item:selected {
                    background: #094771;
                    color: #ffffff;
                }
                QListWidget::item:hover {
                    background: #2a2d2e;
                }
                QLineEdit {
                    background: #3c3c3c;
                    color: #cccccc;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 2px 8px;
                }
                QLabel {
                    color: #888888;
                }
            """)

    # -------------------------------------------------------------------- private

    def _update_item_thumbnail(self, widget_id):
        """Update a list item's icon with a new thumbnail."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item:
                wid = str(item.data(Qt.UserRole) or "")
                if wid == widget_id:
                    img = self._thumbnail_cache.get(widget_id)
                    if img is not None:
                        scaled = self._scale_thumbnail(img)
                        item.setIcon(QIcon(scaled))
                    break

    def _scale_thumbnail(self, img):
        """Scale a QImage to THUMB_SIZE with aspect ratio kept, return QPixmap."""
        scaled = img.scaled(
            THUMB_SIZE.width(), THUMB_SIZE.height(),
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        return QPixmap.fromImage(scaled)

    def _make_placeholder_icon(self, widget_type):
        """Create a placeholder icon with the widget type's initial letter."""
        image = QImage(
            THUMB_SIZE.width(), THUMB_SIZE.height(),
            QImage.Format_ARGB32
        )
        if self._theme == "dark":
            image.fill(0xFF444444)
        else:
            image.fill(0xFFCCCCCC)
        painter = QPainter(image)
        painter.setPen(0xFFFFFFFF)
        font = QFont()
        font.setPointSize(16)
        font.setBold(True)
        painter.setFont(font)
        initial = widget_type[0].upper() if widget_type else "?"
        painter.drawText(image.rect(), Qt.AlignCenter, initial)
        painter.end()
        return QIcon(QPixmap.fromImage(image))

    @property
    def list(self):
        return self._list

    @property
    def filter_edit(self):
        return self._filter_edit