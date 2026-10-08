from PySide6.QtCore import QMimeData, QRectF, QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QMenu, QTreeWidget, QTreeWidgetItem

from designer.canvas import widget_previews
from designer.canvas.designer_view import MIME_TYPE
from ui.python.shadcn import color


class WidgetPalette(QTreeWidget):
    """Searchable visual widget catalog with persisted favorites."""

    resultsChanged = Signal(int)
    widgetActivated = Signal(str)

    def __init__(self, registry, parent=None, library=None):
        super().__init__(parent)
        self.registry = registry
        # Custom widgets (designer/palette/custom_widgets.py): a "Custom"
        # section after the kit, rebuilt whenever the library changes.
        self.library = library
        self._custom_category = None
        self._theme = "dark"
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setRootIsDecorated(False)
        self.setIndentation(8)
        self.setIconSize(QSize(46, 32))
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAccessibleName("Widget library")
        self._query = ""
        self._favorites_only = False
        self._settings = QSettings("EmbeddedDisplay", "Studio")
        saved = self._settings.value("designer/favoriteWidgets", [])
        self._favorites = set(saved if isinstance(saved, list) else [saved])
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.itemDoubleClicked.connect(self._activate_item)

        for category in registry.categories():
            category_item = QTreeWidgetItem([category])
            category_item.setFlags(category_item.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsSelectable)
            category_item.setSizeHint(0, QSize(0, 26))
            # Category rows are captions, not entries: small, letter-spaced
            # and muted, the way OpenDesign heads each inspector section.
            heading_font = category_item.font(0)
            heading_font.setWeight(QFont.DemiBold)
            heading_font.setPointSizeF(7.5)
            heading_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
            category_item.setFont(0, heading_font)
            category_item.setData(0, Qt.UserRole + 1, category)
            self.addTopLevelItem(category_item)
            for definition in registry.definitions():
                if definition.category != category:
                    continue
                item = QTreeWidgetItem([definition.display_name])
                item.setData(0, Qt.UserRole, definition.type)
                item.setSizeHint(0, QSize(0, 40))
                bindings = ", ".join(definition.bindable_properties) or "None"
                item.setToolTip(
                    0,
                    f"{definition.display_name}\n"
                    f"{definition.default_width} × {definition.default_height} px\n"
                    f"Bindable: {bindings}\n"
                    "Drag, double-click, or press Enter to add.\n"
                    "Right-click or press Ctrl+F to favorite.",
                )
                category_item.addChild(item)
            category_item.setExpanded(True)

        if self.library is not None:
            self._build_custom()
            self.library.changed.connect(self.refresh_custom)
        self.apply_theme("dark")
        self._filter()

    # -- custom widgets ---------------------------------------------------------
    def _build_custom(self):
        from designer.palette.custom_widgets import CATEGORY
        category_item = QTreeWidgetItem([CATEGORY])
        category_item.setFlags(category_item.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsSelectable)
        category_item.setSizeHint(0, QSize(0, 26))
        heading_font = category_item.font(0)
        heading_font.setWeight(QFont.DemiBold)
        heading_font.setPointSizeF(7.5)
        heading_font.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        category_item.setFont(0, heading_font)
        category_item.setData(0, Qt.UserRole + 1, CATEGORY)
        self.addTopLevelItem(category_item)
        self._custom_category = category_item
        self._fill_custom()

    def _fill_custom(self):
        category_item = self._custom_category
        category_item.takeChildren()
        for custom in self.library.items():
            item = QTreeWidgetItem([custom.name])
            item.setData(0, Qt.UserRole, custom.type)
            item.setSizeHint(0, QSize(0, 40))
            item.setToolTip(0, f"{custom.name}  ·  custom widget\n{custom.width} × {custom.height} px, "
                               f"{len(custom.widgets)} parts\nDrag or double-click to add. "
                               "Right-click to delete.")
            category_item.addChild(item)
        category_item.setExpanded(True)

    def refresh_custom(self):
        """The library changed: list it again, with fresh thumbnails."""
        if self._custom_category is None:
            return
        self._fill_custom()
        self.apply_theme(self._theme)
        self._filter()

    def _custom(self, widget_type):
        from designer.palette.custom_widgets import is_custom
        if self.library is None or not is_custom(widget_type):
            return None
        return self.library.get(widget_type)

    def _paint_custom(self, painter, custom):
        """A custom widget's thumbnail: each part drawn by its kit painter."""
        scale = min(1.0, 96 / max(1, custom.width), 68 / max(1, custom.height))
        painter.translate((104 - custom.width * scale) / 2, (76 - custom.height * scale) / 2)
        painter.scale(scale, scale)
        for data in custom.widgets:
            geometry = data.get("geometry") or {}
            preview = widget_previews.painter_for(data.get("type", ""))
            definition = self.registry.get(data.get("type", ""))
            if not preview or not definition:
                continue
            props = dict(definition.defaults)
            props.update(data.get("properties") or {})
            painter.save()
            painter.translate(float(geometry.get("x", 0)), float(geometry.get("y", 0)))
            preview(painter, QRectF(0, 0, float(geometry.get("width", definition.default_width)),
                                    float(geometry.get("height", definition.default_height))), props, None)
            painter.restore()

    def _activate_item(self, item, _column=0):
        widget_type = item.data(0, Qt.UserRole) if item else None
        if widget_type:
            self.widgetActivated.emit(widget_type)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._activate_item(self.currentItem())
            event.accept()
            return
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            item = self.currentItem()
            widget_type = item.data(0, Qt.UserRole) if item else None
            if widget_type:
                self.toggle_favorite(widget_type)
                event.accept()
                return
        super().keyPressEvent(event)

    def set_filter(self, text):
        self._query = text.strip().casefold()
        self._filter()

    def set_favorites_only(self, enabled):
        self._favorites_only = enabled
        self._filter()

    def _filter(self):
        total = 0
        for index in range(self.topLevelItemCount()):
            category_item = self.topLevelItem(index)
            category = category_item.data(0, Qt.UserRole + 1)
            count = 0
            for row in range(category_item.childCount()):
                item = category_item.child(row)
                widget_type = item.data(0, Qt.UserRole)
                definition = self.registry.get(widget_type)
                custom = None if definition else self._custom(widget_type)
                name = definition.display_name if definition else (custom.name if custom else widget_type)
                haystack = f"{name} {widget_type} {category}".casefold()
                visible = all(word in haystack for word in self._query.split()) and (
                    not self._favorites_only or widget_type in self._favorites
                )
                item.setHidden(not visible)
                item.setText(0, name + ("  ★" if widget_type in self._favorites else ""))
                count += int(visible)
            category_item.setText(0, f"{category.upper()}  ·  {count}")
            # The Custom section stays when empty, to say how to fill it.
            empty_custom = category_item is self._custom_category and not self._query \
                and not self._favorites_only
            category_item.setHidden(count == 0 and not empty_custom)
            if empty_custom and count == 0:
                category_item.setToolTip(0, "Select widgets on the canvas and choose "
                                            "Save as custom widget to add your own here.")
            if self._query:
                category_item.setExpanded(True)
            total += count
        self.resultsChanged.emit(total)

    def toggle_favorite(self, widget_type):
        if not self.registry.get(widget_type):
            return
        if widget_type in self._favorites:
            self._favorites.remove(widget_type)
        else:
            self._favorites.add(widget_type)
        self._settings.setValue("designer/favoriteWidgets", sorted(self._favorites))
        self._filter()

    def _context_menu(self, point):
        item = self.itemAt(point)
        widget_type = item.data(0, Qt.UserRole) if item else None
        if not widget_type:
            return
        if self._custom(widget_type) is not None:
            menu = QMenu(self)
            delete = menu.addAction("Delete custom widget")
            if menu.exec(self.viewport().mapToGlobal(point)) == delete:
                self.library.delete(widget_type)
            return
        menu = QMenu(self)
        label = "Remove from favorites" if widget_type in self._favorites else "Add to favorites"
        action = menu.addAction(label)
        if menu.exec(self.viewport().mapToGlobal(point)) == action:
            self.toggle_favorite(widget_type)

    def apply_theme(self, theme):
        self._theme = theme
        previous = widget_previews.theme_mode()
        widget_previews.set_theme_mode(theme)
        try:
            for index in range(self.topLevelItemCount()):
                category_item = self.topLevelItem(index)
                category_item.setForeground(0, QColor(color("mutedForeground", theme)))
                for row in range(category_item.childCount()):
                    item = category_item.child(row)
                    definition = self.registry.get(item.data(0, Qt.UserRole))
                    pixmap = QPixmap(104, 76)
                    pixmap.fill(Qt.transparent)
                    painter = QPainter(pixmap)
                    painter.setRenderHint(QPainter.Antialiasing)
                    # A rounded thumbnail well one step below the panel, so each
                    # preview reads as a tile rather than a square cut-out.
                    painter.setPen(QColor(color("border", theme)))
                    painter.setBrush(QColor(color("background", theme)))
                    painter.drawRoundedRect(QRectF(0.5, 0.5, 103, 75), 8, 8)
                    painter.save()
                    custom = None if definition else self._custom(item.data(0, Qt.UserRole))
                    preview = widget_previews.painter_for(definition.type) if definition else None
                    if custom is not None:
                        self._paint_custom(painter, custom)
                    elif preview:
                        scale = min(1.0, 96 / definition.default_width, 68 / definition.default_height)
                        painter.translate(
                            (104 - definition.default_width * scale) / 2,
                            (76 - definition.default_height * scale) / 2,
                        )
                        painter.scale(scale, scale)
                        preview(
                            painter,
                            QRectF(0, 0, definition.default_width, definition.default_height),
                            definition.defaults,
                            None,
                        )
                    else:
                        painter.setPen(QColor(color("mutedForeground", theme)))
                        painter.drawText(pixmap.rect(), Qt.AlignCenter, "preview")
                    painter.restore()
                    painter.end()
                    item.setIcon(0, QIcon(pixmap))
        finally:
            widget_previews.set_theme_mode(previous)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        widget_type = item.data(0, Qt.UserRole) if item else None
        if not widget_type:
            return
        mime = QMimeData()
        mime.setData(MIME_TYPE, widget_type.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(item.icon(0).pixmap(104, 76))
        drag.exec(Qt.CopyAction)
