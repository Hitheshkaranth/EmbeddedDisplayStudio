"""Integrated visual designer workspace composed only from ordinary PySide6 APIs."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import tempfile

import shiboken6
from PySide6.QtCore import SIGNAL, QEvent, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QFrame, QGraphicsDropShadowEffect, QHeaderView, QPlainTextEdit, QScrollArea, QSizePolicy,
    QSplitter, QTabWidget, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from designer.canvas import widget_previews
from designer.canvas.designer_view import POSITIONERS, DesignerScene, DesignerView
from designer.canvas.qml_previews import QmlPreviewRenderer
from designer.commands import CallbackCommand, NudgeCommand
from designer.generators import QmlGenerationError, QmlGenerator
from designer.layout.selection import arrange as arrange_selection
from designer.model import DesignerAction, DesignerBinding, DesignerPage, DesignerProject, DesignerWidget
from designer.model.project import ACTION_KINDS, drop_unrunnable_actions, ensure_unique_ids
from designer.ui.action_extras import ActionExtras
from designer.ui.alarm_extras import AlarmExtras
from designer.ui.binding_extras import BindingExtras
from designer.ui.screen_idle_editor import ScreenIdleEditor
from designer.palette.widget_palette import WidgetPalette
from designer.palette.widget_registry import clamp_property, property_minimum
from designer.palette.widget_registry import default_registry
from schema.manifest import NAME_RE, deployable_name, theme_of

UNDO_LIMIT = 200

try:
    from ui.python.shadcn import color, icon
except ImportError:
    from PySide6.QtGui import QIcon
    def icon(_name): return QIcon()
    def color(_name, theme="dark"): return "#18181b"


class _WheelGuard:
    """Ignore wheel events unless the widget has keyboard focus.

    Qt delivers a wheel event to whichever widget the pointer happens to be
    over, focused or not. Every value editor in this workspace lives inside a
    scrolling panel, so scrolling one silently edited whatever the pointer
    crossed on the way past -- and on the canvas bar that is the design
    surface itself. Two notches over W retargets the design to a screen nobody
    chose, the canvas quietly redraws at the new size, and nothing says so
    until the layout reaches a panel it no longer fits.

    Ignoring the event lets it through to the scroll area, which is what the
    scroll was for. A focused editor still takes the wheel, so deliberate
    adjustment is unchanged.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Wheel focus is what let an unfocused editor consume the event at all.
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class SpinBox(_WheelGuard, QSpinBox):
    """A QSpinBox that cannot be changed by scrolling past it."""


class DoubleSpinBox(_WheelGuard, QDoubleSpinBox):
    """A QDoubleSpinBox that cannot be changed by scrolling past it."""


class ComboBox(_WheelGuard, QComboBox):
    """A QComboBox whose selection cannot be changed by scrolling past it."""


def _rgba(hex_color: str, alpha: float) -> str:
    """``#rrggbb`` token + alpha -> ``rgba(r,g,b,a)`` for QSS tints."""
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})"


def _icon_file(name: str, size: int, color_hex: str) -> str:
    """Render a Tabler icon to a PNG on disk and return a QSS-safe path.

    ``QComboBox::down-arrow`` and tree branch indicators only take
    ``image: url(...)``, so the glyph has to exist as a file; one per
    (name, size, colour) is cached in the temp dir. Forward slashes: QSS
    chokes on Windows backslashes.
    """
    key = color_hex.lstrip("#").replace("(", "").replace(")", "").replace(",", "_").replace(".", "")
    path = os.path.join(tempfile.gettempdir(), f"eds-designer-{name}-{size}-{key}.png")
    if not os.path.exists(path):
        icon(name, size, color_hex).pixmap(size, size).save(path, "PNG")
    return path.replace("\\", "/")


def _trim_transparent_margins(source: str, destination: str) -> bool:
    """Write *source* to *destination* cropped to its non-transparent pixels.

    Returns False, writing nothing, when there is nothing to trim (no alpha
    channel, fully transparent, or already tight) so the caller copies the
    file as it is.
    """
    from PySide6.QtGui import QImage
    image = QImage(source)
    if image.isNull() or not image.hasAlphaChannel():
        return False
    alpha = image.convertToFormat(QImage.Format_Alpha8)
    width, height, stride = alpha.width(), alpha.height(), alpha.bytesPerLine()
    data = bytes(alpha.constBits())[:stride * height]
    top = bottom = None
    left, right = width, -1
    for y in range(height):
        row = data[y * stride:y * stride + width]
        rest = row.lstrip(b"\0")
        if not rest:
            continue
        top = y if top is None else top
        bottom = y
        left = min(left, width - len(rest))
        right = max(right, len(row.rstrip(b"\0")) - 1)
    if top is None or (left, top, right, bottom) == (0, 0, width - 1, height - 1):
        return False
    return image.copy(left, top, right - left + 1, bottom - top + 1).save(destination)


def _field_label(text: str) -> QLabel:
    """The muted left-hand caption of an inspector row."""
    label = QLabel(text)
    label.setObjectName("propLabel")
    return label


def _mark(widget, name: str) -> None:
    """Give an inspector editor the shared field skin."""
    widget.setObjectName(name)
    widget.setFixedHeight(30)


class _EmptyState(QFrame):
    """A quiet, centred hint for a panel with nothing to show yet.

    Mirrors the AI Design tab's empty canvas state: an icon disc, a short
    title and one line of body copy, rather than a bare sentence in a form.
    """

    def __init__(self, icon_name: str, title: str, body: str, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 28, 16, 28)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.icon = QLabel()
        self.icon.setObjectName("emptyStateIcon")
        self.icon.setFixedSize(40, 40)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon_name = icon_name
        layout.addWidget(self.icon, 0, Qt.AlignHCenter)
        heading = QLabel(title)
        heading.setObjectName("emptyStateTitle")
        heading.setAlignment(Qt.AlignHCenter)
        layout.addWidget(heading)
        text = QLabel(body)
        text.setObjectName("emptyStateBody")
        text.setAlignment(Qt.AlignHCenter)
        text.setWordWrap(True)
        layout.addWidget(text)

    def retheme(self, theme: str) -> None:
        self.icon.setPixmap(icon(self.icon_name, 18, color("primary", theme)).pixmap(18, 18))


class PropertyEditor(QWidget):
    propertyEdited = Signal(str, object)
    geometryEdited = Signal(str, object)
    assetRequested = Signal(str)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.setObjectName("propertyEditor")
        # The scroll area sizes this to its viewport; a form that insists on
        # its own minimum width is clipped on the right instead of squeezed.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.registry, self.widget_model = registry, None
        self.theme = "dark"
        self.form = QFormLayout(self)
        self.form.setContentsMargins(12, 10, 12, 12)
        self.form.setHorizontalSpacing(12)
        self.form.setVerticalSpacing(6)
        self.form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.form.setFormAlignment(Qt.AlignTop)
        self.form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

    def _clear_form(self):
        """Empty the form without deleting an editor that is still talking.

        QFormLayout.removeRow deletes the row's widgets there and then. Every
        editor here reports edits through propertyEdited, and handling one
        rebuilds this panel -- so typing in the font size spin box asked Qt
        to destroy that spin box in the middle of its own valueChanged, and
        the process died in Qt6Widgets the moment the signal returned into
        the freed object. Taking the rows and deferring the delete lets the
        editor finish speaking before it goes.
        """
        while self.form.rowCount():
            row = self.form.takeRow(0)
            for item in (row.labelItem, row.fieldItem):
                widget = item.widget() if item is not None else None
                if widget is not None:
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()

    def set_widget(self, widget, positioned=False):
        self.widget_model = widget
        self.setMinimumHeight(0)
        self._clear_form()
        if widget is None:
            empty = _EmptyState("pointer", "Nothing selected",
                                "Click a widget on the canvas, or pick one in Layers, to edit it here.")
            empty.retheme(self.theme)
            self.form.addRow(empty)
            self._sync_form_height()
            return
        definition = self.registry.get(widget.type)
        self.form.addRow(self._heading(definition.display_name if definition else widget.type, widget))
        identifier = QLineEdit(widget.id)
        _mark(identifier, "propField")
        identifier.editingFinished.connect(lambda e=identifier: self.propertyEdited.emit("id", e.text()))
        self.form.addRow(_field_label("ID"), identifier)
        locked = QCheckBox("Fixed on canvas")
        locked.setObjectName("propSwitch")
        locked.setChecked(widget.locked)
        locked.toggled.connect(lambda value: self.propertyEdited.emit("locked", value))
        self.form.addRow(_field_label("Locked"), locked)
        # Position and size read as two pairs, the way every design tool
        # shows them, rather than four stacked rows fighting for height.
        self.form.addRow(_field_label("Position"), self._pair(widget, ("x", "y"), positioned))
        self.form.addRow(_field_label("Size"), self._pair(widget, ("width", "height"), False))
        if not definition:
            self._sync_form_height()
            return
        if definition.properties:
            self.form.addRow(self._divider(definition.display_name))
        for name, value_type in definition.properties.items():
            value = widget.properties.get(name, definition.defaults.get(name))
            editor = self._editor(definition, name, value_type, value)
            self.form.addRow(_field_label(name), editor)
        self._sync_form_height()

    def _heading(self, title, widget):
        head = QWidget()
        head.setObjectName("inspectorHeading")
        row = QHBoxLayout(head); row.setContentsMargins(0, 0, 0, 4); row.setSpacing(8)
        name = QLabel(title); name.setObjectName("inspectorTitle")
        row.addWidget(name)
        if widget.type != title:
            kind = QLabel(widget.type); kind.setObjectName("chip")
            row.addWidget(kind, 0, Qt.AlignVCenter)
        row.addStretch()
        return head

    def _divider(self, text):
        label = QLabel(text.upper())
        label.setObjectName("inspectorSection")
        return label

    def _pair(self, widget, keys, positioned):
        pair = QWidget()
        row = QHBoxLayout(pair); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
        for key in keys:
            cell = QFrame(); cell.setObjectName("pairField"); cell.setFixedHeight(30)
            inner = QHBoxLayout(cell); inner.setContentsMargins(8, 0, 4, 0); inner.setSpacing(4)
            tag = QLabel(key[0].upper()); tag.setObjectName("pairTag")
            editor = SpinBox(); editor.setObjectName("pairValue")
            editor.setButtonSymbols(QSpinBox.NoButtons)
            editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            editor.setRange(-100000 if key in ("x", "y") else 1, 100000)
            editor.setValue(round(widget.geometry[key]))
            if positioned and key in ("x", "y"):
                cell.setEnabled(False)
                cell.setToolTip("The parent Row, Column or Grid places this widget.")
            else:
                editor.valueChanged.connect(lambda value, name=key: self.geometryEdited.emit(name, value))
            inner.addWidget(tag); inner.addWidget(editor, 1)
            row.addWidget(cell, 1)
        return pair

    def _sync_form_height(self):
        """Expose dynamic rows to the containing inspector scroll area."""
        QTimer.singleShot(0, self._apply_form_height)

    def _apply_form_height(self):
        self.form.invalidate()
        self.form.activate()
        self.setMinimumHeight(self.form.sizeHint().height() + 12)

    def _editor(self, definition, name, value_type, value):
        if name in definition.choices:
            editor = ComboBox()
            _mark(editor, "propField")
            editor.addItems(definition.choices[name])
            editor.setCurrentText(str(value or ""))
            editor.currentTextChanged.connect(lambda v: self.propertyEdited.emit(name, v))
        elif name in definition.color_properties:
            editor = QWidget()
            row = QHBoxLayout(editor); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
            text = QLineEdit(str(value or "")); text.setPlaceholderText("Theme default or #RRGGBB")
            _mark(text, "propField")
            swatch = QToolButton(); swatch.setObjectName("swatch"); swatch.setFixedSize(30, 30)
            swatch.setCursor(Qt.PointingHandCursor); swatch.setToolTip(f"Choose {name}")
            def paint_swatch():
                chosen = QColor(text.text())
                fill = chosen.name() if chosen.isValid() else "transparent"
                swatch.setStyleSheet(f"QToolButton#swatch {{ background: {fill}; }}")
            paint_swatch()
            text.textChanged.connect(lambda _t: paint_swatch())
            text.editingFinished.connect(lambda e=text: self.propertyEdited.emit(name, e.text().strip()))
            def pick_color():
                initial = QColor(text.text()) if QColor(text.text()).isValid() else QColor("#3b82f6")
                selected = QColorDialog.getColor(initial, self, f"Choose {name}")
                if selected.isValid():
                    text.setText(selected.name(QColor.HexArgb) if selected.alpha() < 255 else selected.name())
                    self.propertyEdited.emit(name, text.text())
            swatch.clicked.connect(pick_color)
            row.addWidget(swatch); row.addWidget(text, 1)
        elif name in definition.asset_properties:
            editor = QWidget()
            row = QHBoxLayout(editor); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6)
            text = QLineEdit(str(value or "")); text.setPlaceholderText("assets/image.png")
            _mark(text, "propField")
            browse = QPushButton("Browse"); browse.setObjectName("secondaryAction")
            browse.setToolTip("Select and copy an image into project assets")
            browse.setFixedHeight(30); browse.setCursor(Qt.PointingHandCursor)
            text.editingFinished.connect(lambda e=text: self.propertyEdited.emit(name, e.text().strip()))
            browse.clicked.connect(lambda: self.assetRequested.emit(name))
            row.addWidget(text, 1); row.addWidget(browse)
        elif value_type is bool:
            editor = QCheckBox(); editor.setObjectName("propSwitch"); editor.setChecked(bool(value))
            editor.toggled.connect(lambda v: self.propertyEdited.emit(name, v))
        elif value_type is int:
            editor = SpinBox(); _mark(editor, "propField"); editor.setButtonSymbols(QSpinBox.NoButtons)
            floor = property_minimum(name, definition.type)
            editor.setRange(int(-100000 if floor is None else floor), 100000); editor.setValue(int(value or 0))
            editor.valueChanged.connect(lambda v: self.propertyEdited.emit(name, v))
        elif value_type is float:
            try:
                floor = property_minimum(name, definition.type)
                editor = DoubleSpinBox(); editor.setRange(float(-1e9 if floor is None else floor), 1e9); editor.setDecimals(4); editor.setValue(float(value or 0))
            except (ValueError, TypeError):
                editor = QLineEdit(str(value or ""))
                editor.editingFinished.connect(lambda e=editor: self.propertyEdited.emit(name, e.text()))
                editor.setPlaceholderText("Numeric value or binding expression")
            else:
                editor.setButtonSymbols(QDoubleSpinBox.NoButtons)
                editor.valueChanged.connect(lambda v: self.propertyEdited.emit(name, v))
            _mark(editor, "propField")
        else:
            # A text property may hold a number (ShProcessValue's value 0):
            # 0 is shown as "0", not as an empty field.
            editor = QLineEdit("" if value is None else str(value))
            _mark(editor, "propField")
            editor.editingFinished.connect(lambda e=editor: self.propertyEdited.emit(name, e.text()))
            if name in ("color", "background"):
                editor.setPlaceholderText("#RRGGBB")
        return editor


class BindingEditor(QWidget):
    bindingEdited = Signal(str, object)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.setObjectName("bindingEditor")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.registry, self.widget_model, self.tags = registry, None, []
        form = QFormLayout(self)
        form.setContentsMargins(12, 10, 12, 12)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.property = ComboBox(); self.tag = ComboBox(); self.tag.setEditable(True)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search tags")
        self.search.setClearButtonEnabled(True)
        self.format = QLineEdit(); self.format.setPlaceholderText("e.g. {:.1f}")
        self.multiplier = DoubleSpinBox(); self.offset = DoubleSpinBox()
        self.multiplier.setRange(-1e9, 1e9); self.multiplier.setValue(1.0)
        self.offset.setRange(-1e9, 1e9)
        self.unit = QLineEdit(); self.warning = QLineEdit(); self.critical = QLineEdit()
        self.unit.setPlaceholderText("V, °C, rpm"); self.warning.setPlaceholderText("threshold")
        self.critical.setPlaceholderText("threshold")
        for label, editor in (("Property", self.property), ("Search", self.search), ("Tag", self.tag),
                              ("Format", self.format), ("Multiplier", self.multiplier), ("Offset", self.offset),
                              ("Unit", self.unit), ("Warning", self.warning), ("Critical", self.critical)):
            _mark(editor, "propField")
            if isinstance(editor, QDoubleSpinBox):
                editor.setButtonSymbols(QDoubleSpinBox.NoButtons)
            form.addRow(_field_label(label), editor)
        # CONTRACT 13.2 / 13.3 fields (wave 1): their own widgets, laid out
        # under the classic ones.
        self.definition = None
        self.extras = BindingExtras(); self.alarm_extras = AlarmExtras()
        form.addRow(self.extras); form.addRow(self.alarm_extras)
        actions = QHBoxLayout(); actions.setContentsMargins(0, 6, 0, 0); actions.setSpacing(6)
        bind = QPushButton("Apply binding"); bind.setObjectName("primaryAction")
        remove = QPushButton("Remove"); remove.setObjectName("secondaryAction")
        for button in (bind, remove):
            button.setFixedHeight(30); button.setCursor(Qt.PointingHandCursor)
        actions.addWidget(bind, 1); actions.addWidget(remove); form.addRow(actions)
        self.search.textChanged.connect(self._filter)
        self.property.currentTextChanged.connect(self._load_binding)
        bind.clicked.connect(self._apply); remove.clicked.connect(self._remove)

    def set_tags(self, tags):
        self.tags = sorted(set(tags or [])); self._filter(self.search.text())

    def set_widget(self, widget):
        self.widget_model = widget; self.property.clear()
        definition = self.registry.get(widget.type) if widget else None
        self.definition = definition
        if definition:
            self.property.addItems(definition.bindable_properties)
        self.setEnabled(bool(definition and definition.bindable_properties))

    def _filter(self, text):
        current = self.tag.currentText(); needle = text.lower()
        self.tag.clear(); self.tag.addItems([tag for tag in self.tags if needle in tag.lower()])
        self.tag.setCurrentText(current)

    def _load_binding(self, prop):
        binding = self.widget_model.bindings.get(prop) if self.widget_model else None
        self.extras.load(binding, self.definition); self.alarm_extras.load(binding)
        if binding:
            self.tag.setCurrentText(binding.tag); self.format.setText(binding.format)
            self.multiplier.setValue(binding.multiplier); self.offset.setValue(binding.offset)
            self.unit.setText(binding.unit); self.warning.setText(binding.warning); self.critical.setText(binding.critical)

    def _apply(self):
        prop, tag = self.property.currentText(), self.tag.currentText().strip()
        binding = DesignerBinding(tag, self.format.text(), self.multiplier.value(),
            self.offset.value(), self.unit.text(), self.warning.text(), self.critical.text())
        binding = self.alarm_extras.apply_to(self.extras.apply_to(binding))
        if prop and (tag or binding.expr):     # 13.2: an expression needs no tag
            self.bindingEdited.emit(prop, binding)

    def _remove(self):
        if self.property.currentText(): self.bindingEdited.emit(self.property.currentText(), None)


class ActionEditor(QWidget):
    """Attach a write / pulse / navigate action to one of a widget's signals.

    Mirrors BindingEditor: the signal list comes from the registry's
    ``action_signals`` for the selected widget, the tag list is shared with
    the binding inspector, and Apply / Remove emit ``actionEdited(signal,
    DesignerAction | None)`` for the workspace to turn into an undoable
    command.
    """
    actionEdited = Signal(str, object)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.setObjectName("actionEditor")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.registry, self.widget_model, self.tags, self.page_ids = registry, None, [], []
        form = QFormLayout(self)
        form.setContentsMargins(12, 10, 12, 12)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(6)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setRowWrapPolicy(QFormLayout.DontWrapRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.signal = ComboBox(); self.kind = ComboBox(); self.kind.addItems(list(ACTION_KINDS))
        self.tag = ComboBox(); self.tag.setEditable(True)
        self.value = QLineEdit(); self.value.setPlaceholderText("empty = the control's own state")
        self.ms = SpinBox(); self.ms.setRange(1, 10000); self.ms.setValue(250); self.ms.setSuffix(" ms")
        self.page = ComboBox()
        for label, editor in (("Signal", self.signal), ("Action", self.kind), ("Tag", self.tag),
                              ("Value", self.value), ("Pulse", self.ms), ("Page", self.page)):
            _mark(editor, "propField")
            if isinstance(editor, QSpinBox):
                editor.setButtonSymbols(QSpinBox.NoButtons)
            form.addRow(_field_label(label), editor)
        self.extras = ActionExtras(); form.addRow(self.extras)   # CONTRACT 13.1 (wave 1)
        actions = QHBoxLayout(); actions.setContentsMargins(0, 6, 0, 0); actions.setSpacing(6)
        apply_button = QPushButton("Apply action"); apply_button.setObjectName("primaryAction")
        remove = QPushButton("Remove"); remove.setObjectName("secondaryAction")
        for button in (apply_button, remove):
            button.setFixedHeight(30); button.setCursor(Qt.PointingHandCursor)
        actions.addWidget(apply_button, 1); actions.addWidget(remove); form.addRow(actions)
        self.signal.currentTextChanged.connect(self._load_action)
        self.kind.currentTextChanged.connect(self._sync_fields)
        apply_button.clicked.connect(self._apply); remove.clicked.connect(self._remove)
        self._sync_fields(self.kind.currentText())

    def set_tags(self, tags):
        current = self.tag.currentText()
        self.tags = sorted(set(tags or [])); self.tag.clear(); self.tag.addItems(self.tags)
        self.tag.setCurrentText(current)

    def set_pages(self, pages):
        """Offer every page by name; the action stores the page id."""
        current = self.page.currentData()
        self.page_ids = [page.id for page in pages]
        self.page.clear()
        for page in pages:
            self.page.addItem(page.name or page.id, page.id)
        if current in self.page_ids:
            self.page.setCurrentIndex(self.page_ids.index(current))

    def set_widget(self, widget):
        self.widget_model = widget; self.signal.clear()
        definition = self.registry.get(widget.type) if widget else None
        signals = tuple(definition.action_signals) if definition else ()
        self.signal.addItems(signals)
        self.setEnabled(bool(signals))
        self._load_action(self.signal.currentText())

    def _sync_fields(self, kind):
        self.tag.setEnabled(kind not in ("navigate", "back")); self.value.setEnabled(kind == "write")
        self.ms.setEnabled(kind == "pulse"); self.page.setEnabled(kind == "navigate")
        if hasattr(self, "extras"):
            self.extras.set_kind(kind)

    def _load_action(self, signal):
        action = self.widget_model.actions.get(signal) if self.widget_model else None
        self.extras.load(action)
        if not action:
            return
        self.kind.setCurrentText(action.kind); self.tag.setCurrentText(action.tag)
        self.value.setText("" if action.value is None else json.dumps(action.value))
        self.ms.setValue(int(action.ms) if action.kind == "pulse" else 250)
        if action.page in self.page_ids:
            self.page.setCurrentIndex(self.page_ids.index(action.page))

    @staticmethod
    def _parse_value(text):
        """A JSON scalar if the text is one, else the text itself; None if empty."""
        text = text.strip()
        if not text:
            return None
        try:
            value = json.loads(text)
        except ValueError:
            return text
        return value if isinstance(value, (bool, int, float, str)) else text

    def _apply(self):
        signal, kind = self.signal.currentText(), self.kind.currentText()
        if not signal:
            return
        if kind == "navigate":
            action = DesignerAction("navigate", page=self.page.currentData() or "")
        elif kind == "pulse":
            action = DesignerAction("pulse", self.tag.currentText().strip(), ms=self.ms.value())
        elif kind == "write":
            action = DesignerAction("write", self.tag.currentText().strip(), value=self._parse_value(self.value.text()))
        elif kind == "back":
            action = DesignerAction("back")
        else:                                   # 13.1 kinds that name a tag
            action = DesignerAction(kind, self.tag.currentText().strip())
        self.actionEdited.emit(signal, self.extras.apply_to(action))

    def _remove(self):
        if self.signal.currentText(): self.actionEdited.emit(self.signal.currentText(), None)


class DesignerWorkspace(QWidget):
    previewRequested = Signal(str)
    deployRequested = Signal(str)
    message = Signal(str)
    # Emitted after any change to the design the Code window should re-read
    # -- an undo stack index change, a page switch/add/delete, a bundle load,
    # a replace_widget/replace_page. Never emitted for selection changes
    # (those are scene.selectionIdsChanged).
    designChanged = Signal()
    # The current page's index changed (page switch/add/delete/load).
    pageChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # The Designer contains several rich panes, but it must yield vertical
        # space to the Studio chrome/footer on scaled or smaller desktops.
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)
        self.project = DesignerProject()
        # The connected panel's real geometry, once the Studio has probed it.
        # Held here rather than only applied on arrival, because a design
        # opened later has to be retargeted to the same glass.
        self.target_resolution = None
        self.bundle_dir = ""
        self.file_path = ""
        # Where a design that was never given a bundle (AI Design hand-over,
        # a fresh Studio) is provisioned when Preview/Deploy first needs one.
        self.projects_root = ""
        self.current_page_index = 0
        self.undo_stack = QUndoStack(self)
        # Each command closes over a copy of the widgets it touched; a
        # long session would otherwise keep every edit's snapshot alive.
        self.undo_stack.setUndoLimit(UNDO_LIMIT)
        # Every undoable edit moves the stack index, after the command's redo
        # has already touched the model, so this is the one place that sees
        # them all. Connected before the first _load_page so nothing is
        # missed. Loads and page operations do not push commands and emit
        # for themselves.
        self.undo_stack.indexChanged.connect(self._announce_design_change)
        self.clipboard = []
        # The Code window is built on first use and kept: it is a second
        # top-level window the author positions once and reopens.
        self._code_window = None
        self._code_activate = None
        self._designer_icon_names = {}
        self._build_ui(); self._shortcuts(); self._load_page()

    @property
    def current_page(self):
        return self.project.pages[self.current_page_index]

    def _announce_design_change(self, _index=0):
        # The stack outlives the workspace on teardown and keeps emitting (see
        # _pin in _build_ui); a signal on a deleted widget raises from inside
        # Qt's delivery.
        if shiboken6.isValid(self) and not getattr(self, "_clearing_undo", False):
            self.designChanged.emit()

    def _clear_undo(self):
        # Every caller loads a new design and announces that itself; the
        # stack's own index change on clear() would announce it twice.
        self._clearing_undo = True
        try: self.undo_stack.clear()
        finally: self._clearing_undo = False

    def _build_ui(self):
        self.setObjectName("designerWorkspace")
        # This workspace already lives inside the Studio page's padded content
        # area. A second inset made the command rows look detached and
        # needlessly reduced the working canvas. Rows and panes touch, and a
        # hairline between them is the only chrome -- the same surface
        # language as the AI Design tab.
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        primary = QToolBar("Designer actions")
        # One row since Studio 2; the name the row-building code used for the
        # second row now means the same bar.
        canvas_bar = primary
        primary.setObjectName("designerPrimaryToolbar")
        for bar, height in ((primary, 44),):
            bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            bar.setMovable(False)
            bar.setFloatable(False)
            bar.setIconSize(QSize(16, 16))
            bar.setFixedHeight(height)
            # Toolbars pack their children edge to edge by default, which ran
            # one group of controls straight into the next.
            bar.layout().setSpacing(2)
            # The stylesheet owns toolbar padding. A layout inset here adds a
            # second, platform-dependent gutter around every row.
            bar.layout().setContentsMargins(0, 0, 0, 0)
        self._designer_toolbutton_icons = {}
        self._designer_empty_states = []

        def action(bar, text, slot, icon_name="adjustments", shortcut=None, checkable=False, compact=False):
            item = bar.addAction(icon(icon_name), text); item.triggered.connect(slot); item.setCheckable(checkable)
            self._designer_icon_names[item] = icon_name
            item.setToolTip(text + (f"  {shortcut}" if shortcut else ""))
            if shortcut: item.setShortcut(QKeySequence(shortcut))
            button = bar.widgetForAction(item)
            if button is not None:
                button.setCursor(Qt.PointingHandCursor)
                if compact:
                    # Icon-only, square, the label lives in the tooltip. This
                    # is how OpenDesign's viewer toolbar keeps a dozen tools
                    # in one quiet row.
                    button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                    button.setProperty("compact", True)
                    button.setFixedSize(28, 28)
            return item

        def caption(bar, text, tooltip=""):
            label = QLabel(text.upper())
            label.setObjectName("barCaption")
            label.setContentsMargins(8, 0, 6, 0)
            label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            if tooltip:
                label.setToolTip(tooltip)
            bar.addWidget(label)
            return label

        def field(bar, text, widget, width=0, tooltip=""):
            """A captioned input, spaced away from whatever precedes it."""
            caption(bar, text, tooltip)
            if tooltip:
                widget.setToolTip(tooltip)
            widget.setObjectName("barField")
            if width:
                widget.setFixedWidth(width)
            # Match the buttons exactly: a field even a few pixels taller than
            # its bar spills into the next row.
            widget.setFixedHeight(26)
            bar.addWidget(widget)
            return widget

        def spacer(bar):
            gap = QWidget(); gap.setObjectName("barSpacer")
            gap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            bar.addWidget(gap)

        # -- one row: file, editing, view, arrange, then what leaves the Studio --
        # Studio 2: the page, the screen size and the project name moved to the
        # Pages tab beside Layers, New/Open/Save into the File menu, and the
        # two rows became one, so the canvas starts 40 px higher.
        file_button = QToolButton()
        file_button.setText("File")
        file_button.setObjectName("fileMenuButton")
        file_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        file_button.setPopupMode(QToolButton.InstantPopup)
        file_button.setCursor(Qt.PointingHandCursor)
        file_button.setFixedHeight(28)
        file_button.setToolTip("New, open or save the design")
        self.file_menu = QMenu(self)
        for text, slot, icon_name, shortcut in (("New design", self.new_ui, "file-plus", None),
                                                ("Open design...", self.open_ui, "folder-open", None),
                                                ("Save", self.save, "device-floppy", "Ctrl+S")):
            item = self.file_menu.addAction(icon(icon_name), text)
            item.triggered.connect(slot)
            self._designer_icon_names[item] = icon_name
            if shortcut:
                item.setShortcut(QKeySequence(shortcut))
                # Active while the Designer shows, as the toolbar action was.
                self.addAction(item)
        file_button.setMenu(self.file_menu)
        self._designer_toolbutton_icons[file_button] = ("folder-open", "foreground")
        primary.addWidget(file_button)
        primary.addSeparator()
        undo = self.undo_stack.createUndoAction(self, "Undo"); undo.setIcon(icon("arrow-back-up")); self._designer_icon_names[undo] = "arrow-back-up"; primary.addAction(undo)
        redo = self.undo_stack.createRedoAction(self, "Redo"); redo.setIcon(icon("arrow-forward-up")); self._designer_icon_names[redo] = "arrow-forward-up"; primary.addAction(redo)
        # createUndoAction keeps rewriting the label to "Undo <last command>",
        # so the row's width depended on the last edit -- "Undo Reparent Text"
        # is wide enough to push Deploy into the overflow menu, and the button
        # positions shifted after every action. Fixed label, detail in the tip.
        def _pin(item, verb, text):
            # The stack outlives the actions when the workspace is torn down,
            # and it keeps emitting into them; touching a deleted QAction from
            # here raises out of Qt's own signal delivery.
            if not shiboken6.isValid(item):
                return
            item.setText(verb)
            item.setToolTip(f"{verb} {text}" if text else verb)
        self.undo_stack.undoTextChanged.connect(lambda t: _pin(undo, "Undo", t))
        self.undo_stack.redoTextChanged.connect(lambda t: _pin(redo, "Redo", t))
        _pin(undo, "Undo", self.undo_stack.undoText())
        _pin(redo, "Redo", self.undo_stack.redoText())
        for item in (undo, redo):
            button = primary.widgetForAction(item)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                button.setProperty("compact", True)
                button.setFixedSize(28, 28)
                button.setCursor(Qt.PointingHandCursor)
        primary.addSeparator()
        action(primary, "Cut", self.cut, "scissors", "Ctrl+X", compact=True)
        action(primary, "Copy", self.copy, "copy", "Ctrl+C", compact=True)
        action(primary, "Paste", self.paste, "clipboard", "Ctrl+V", compact=True)
        action(primary, "Duplicate", self.duplicate, "layout-grid", "Ctrl+D", compact=True)
        self.save_custom_action = action(primary, "Save as custom widget", self.save_selection_as_custom,
                                         "components", compact=True)
        self.save_custom_action.setToolTip("Save the selected widgets as a custom widget in the palette")
        # Keep deletion explicit. A global Delete QAction shortcut can repeat
        # while focus moves through the object tree, removing each newly
        # selected row in turn. The toolbar button and context menu remain.
        action(primary, "Delete", self.delete_selected, "trash", compact=True)
        canvas_bar.addSeparator()
        self.grid_action = action(canvas_bar, "Grid", self.toggle_grid, "grid-dots", checkable=True, compact=True); self.grid_action.setChecked(True)
        self.snap_action = action(canvas_bar, "Snap", self.toggle_snap, "magnet", checkable=True, compact=True); self.snap_action.setChecked(True)
        self.object_snap_action = action(canvas_bar, "Object snap", self.toggle_object_snap,
                                         "layout-align-center", checkable=True, compact=True)
        self.object_snap_action.setChecked(True)
        self.object_snap_action.setToolTip("Snap to sibling and parent edges; hold Ctrl while dragging to bypass")
        self.live_action = action(canvas_bar, "Live preview", self.toggle_live_previews, "eye", checkable=True, compact=True); self.live_action.setChecked(True)
        canvas_bar.addSeparator()
        # Ten align actions as separate buttons is more than any row can hold
        # at the width this pane actually gets inside the Studio, and Qt hides
        # the overflow behind a chevron most people never find. One menu, and
        # every mode stays reachable at every window size.
        self.align_menu = QMenu(self)
        for label, mode in (("Align Left", "left"), ("Align Right", "right"),
                            ("Align Top", "top"), ("Align Bottom", "bottom"),
                            ("Centre Horizontally", "hcenter"),
                            ("Centre Vertically", "vcenter"), (None, None),
                            ("Same Width", "same_width"), ("Same Height", "same_height"),
                            (None, None),
                            ("Distribute Horizontally", "distribute_h"),
                            ("Distribute Vertically", "distribute_v")):
            if label is None:
                self.align_menu.addSeparator()
                continue
            item = self.align_menu.addAction(label)
            item.triggered.connect(lambda _checked=False, m=mode: self.align(m))
        self.align_button = QToolButton()
        self.align_button.setText("Align")
        self.align_button.setIcon(icon("layout-align-center"))
        self._designer_toolbutton_icons[self.align_button] = ("layout-align-center", "foreground")
        self.align_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.align_button.setPopupMode(QToolButton.InstantPopup)
        self.align_button.setMenu(self.align_menu)
        self.align_button.setCursor(Qt.PointingHandCursor)
        self.align_button.setFixedHeight(28)
        self.align_button.setToolTip("Align, match size or distribute the selection")
        canvas_bar.addWidget(self.align_button)
        # Text alignment, one click each. It is also a property in the
        # inspector, but setting how a caption sits in its box is a formatting
        # decision made while looking at the canvas, not while reading a list
        # of property names.
        self._text_align_actions = {}
        for label, value, icon_name in (
            ("Align Left", "Text.AlignLeft", "align-left"),
            ("Centre Text", "Text.AlignHCenter", "align-center"),
            ("Align Right", "Text.AlignRight", "align-right"),
        ):
            item = action(canvas_bar, label,
                          lambda _checked=False, v=value: self.set_text_alignment(v),
                          icon_name, compact=True)
            item.setCheckable(True)
            self._text_align_actions[value] = item
        canvas_bar.addSeparator()
        # Align tidies a selection; this tidies the page: a planned page is
        # compiled again, a hand-drawn one composed by the polish pass.
        action(canvas_bar, "Tidy up", self.tidy_up, "layout-grid", compact=True)
        action(canvas_bar, "Screen idle", self.edit_screen_idle, "moon", compact=True)
        action(canvas_bar, "Bring to Front", lambda: self.z_order("front"), "arrow-bar-to-up", compact=True)
        action(canvas_bar, "Send to Back", lambda: self.z_order("back"), "arrow-bar-to-down", compact=True)
        spacer(canvas_bar)
        action(canvas_bar, "Zoom out", lambda: self.view.set_zoom(round(self.view.transform().m11()*100)-10), "zoom-out", compact=True)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        self.zoom_label.setContentsMargins(2, 0, 2, 0)
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        canvas_bar.addWidget(self.zoom_label)
        action(canvas_bar, "Zoom in", lambda: self.view.set_zoom(round(self.view.transform().m11()*100)+10), "zoom-in", compact=True)
        action(canvas_bar, "Fit to view", self.view_fit, "maximize", compact=True)
        primary.addSeparator()
        # The actions that leave the Studio end the row.
        # The shortcut lives in _shortcuts with the other workspace keys, so
        # the tooltip carries it by hand rather than through the helper.
        self.code_action = action(primary, "Code", self.open_code_window, "terminal-2", compact=True)
        self.code_action.setToolTip("Show the QML and design JSON of the selection  Ctrl+Shift+K")
        action(primary, "Preview", self.preview, "eye")
        action(primary, "Generate", self.generate, "file-code")
        self.deploy_button = QPushButton("Deploy")
        self.deploy_button.setObjectName("primaryAction")
        self.deploy_button.setCursor(Qt.PointingHandCursor)
        self.deploy_button.setFixedHeight(30)
        self.deploy_button.setToolTip("Generate, package and install this design on the connected panel")
        self.deploy_button.clicked.connect(self.deploy)
        self._designer_toolbutton_icons[self.deploy_button] = ("rocket", "primaryForeground")
        primary.addWidget(self.deploy_button)

        # -- the page and screen settings (shown in the Pages tab) -------------
        self.pages = ComboBox(); self.pages.currentIndexChanged.connect(self.change_page)
        self.screen_width = SpinBox(); self.screen_width.setRange(64, 16384); self.screen_width.setValue(1280)
        self.screen_width.setButtonSymbols(QSpinBox.NoButtons)
        self.screen_height = SpinBox(); self.screen_height.setRange(64, 16384); self.screen_height.setValue(800)
        self.screen_height.setButtonSymbols(QSpinBox.NoButtons)
        self.screen_theme = ComboBox(); self.screen_theme.addItems(["dark", "light"])
        self.screen_theme.setToolTip("Shadcn colour mode this design targets; written to the manifest "
                                     "and applied by the panel shell before the app loads")
        self.screen_width.valueChanged.connect(self._screen_changed); self.screen_height.valueChanged.connect(self._screen_changed)
        self.screen_theme.currentTextChanged.connect(self._screen_changed)
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("deployment-name")
        self.project_name.setToolTip("Project name used for deployment and release files")
        self.project_name.editingFinished.connect(self._project_name_edited)
        for widget in (self.pages, self.screen_width, self.screen_height, self.screen_theme, self.project_name):
            widget.setObjectName("barField")
            widget.setFixedHeight(26)
        self.screen_width.setFixedWidth(78); self.screen_height.setFixedWidth(78)

        layout.addWidget(primary)
        split = QSplitter(Qt.Horizontal); split.setObjectName("designerMainSplitter"); split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        # -- left: Layers, Widgets and Pages, one tab each ---------------------
        sidebar = QFrame(); sidebar.setObjectName("designerSidebar")
        sidebar_layout = QVBoxLayout(sidebar); sidebar_layout.setContentsMargins(0, 0, 0, 0); sidebar_layout.setSpacing(0)
        self.side_tabs = QTabWidget(); self.side_tabs.setObjectName("designerSideTabs")
        self.side_tabs.setDocumentMode(True)
        self._compact_tabs(self.side_tabs)
        sidebar_layout.addWidget(self.side_tabs)
        from designer.palette.custom_widgets import CustomWidgetLibrary
        self.custom_library = CustomWidgetLibrary(parent=self)
        self.palette = WidgetPalette(self.registry, library=self.custom_library); self.palette.setObjectName("designerPalette")
        library = QWidget(); library.setObjectName("panelBody"); library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(0, 0, 0, 0); library_layout.setSpacing(0)
        search_row = QWidget(); search_row.setObjectName("panelBody")
        search_layout = QHBoxLayout(search_row); search_layout.setContentsMargins(10, 8, 10, 8); search_layout.setSpacing(6)
        self.palette_search = QLineEdit()
        self.palette_search.setObjectName("panelSearch")
        self.palette_search.setPlaceholderText("Search widgets…")
        self.palette_search.setClearButtonEnabled(True)
        self.palette_search.setFixedHeight(30)
        self.palette_search.setAccessibleName("Search widgets by name or category")
        self.palette_search.setToolTip("Ctrl+L focuses search · Enter adds the selected widget · Ctrl+F toggles favorite")
        self.palette_search.textChanged.connect(self.palette.set_filter)
        self._palette_search_icon = self.palette_search.addAction(icon("search", 14), QLineEdit.LeadingPosition)
        search_layout.addWidget(self.palette_search, 1)
        self.palette_favorites = QToolButton()
        self.palette_favorites.setObjectName("iconToggle")
        self.palette_favorites.setCheckable(True)
        self.palette_favorites.setFixedSize(30, 30)
        self.palette_favorites.setCursor(Qt.PointingHandCursor)
        self.palette_favorites.setToolTip("Show favorites only. Right-click a widget or press Ctrl+F to favorite it.")
        self.palette_favorites.toggled.connect(self.palette.set_favorites_only)
        self._designer_toolbutton_icons[self.palette_favorites] = ("star", "mutedForeground")
        search_layout.addWidget(self.palette_favorites)
        library_layout.addWidget(search_row)
        self.palette_count = QLabel(f"{len(self.registry.definitions())} widgets")
        self.palette_count.setObjectName("panelMeta")
        self.palette_count.setContentsMargins(12, 0, 12, 4)
        library_layout.addWidget(self.palette_count)
        self.palette_empty = QLabel("No matching widgets.\nTry another search or turn off Favorites.")
        self.palette_empty.setObjectName("panelHint")
        self.palette_empty.setAlignment(Qt.AlignCenter)
        self.palette_empty.setContentsMargins(12, 18, 12, 18)
        self.palette_empty.setWordWrap(True); self.palette_empty.hide()
        library_layout.addWidget(self.palette_empty)
        library_layout.addWidget(self.palette, 1)
        def palette_results(count):
            self.palette_count.setText(f"{count} widget{'s' if count != 1 else ''}")
            self.palette_empty.setVisible(count == 0)
        self.palette.resultsChanged.connect(palette_results)
        self.palette.widgetActivated.connect(self.add_widget)
        self._palette_search_shortcut = QShortcut(QKeySequence("Ctrl+L"), library)
        self._palette_search_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self._palette_search_shortcut.activated.connect(self.palette_search.setFocus)
        # Layers: what a designer calls each thing (a card's title, a gauge's
        # label), with the tag it shows beside it; the QML id is the tooltip
        # and the Properties field. Two columns: name, bound tag.
        self.tree = QTreeWidget(); self.tree.setObjectName("designerObjectTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layers = QWidget(); layers.setObjectName("panelBody")
        layers_layout = QVBoxLayout(layers); layers_layout.setContentsMargins(0, 4, 0, 0); layers_layout.setSpacing(0)
        layers_layout.addWidget(self.tree, 1)
        self.side_tabs.addTab(layers, "Layers")
        self.side_tabs.addTab(library, "Widgets")
        self.side_tabs.addTab(self._build_pages_tab(), "Pages")
        split.addWidget(sidebar)

        # -- centre: the canvas, with the AI composer floating over it ---------
        self.scene = DesignerScene(self.registry); self.view = DesignerView(self.scene); self.view.setObjectName("designerCanvas")
        self.scene.workspace = self
        # The scene's renderer is designer.preview.NativeRenderer (the panel's
        # own hmi-ui, headless) when designer.preview.find_hmi_ui() finds a
        # binary, else this Qt/QML fallback; `preview_renderer_name` says which
        # ("hmi-ui" / "qml"). Its `background` follows the design's screen.
        self.preview_renderer_name = "qml"
        self.scene.qml_previews = self._make_preview_renderer()
        self.scene.qml_previews.ready.connect(lambda _key: self.scene.update())
        # The toggle's tooltip names the renderer, which is only known now.
        self.live_action.setToolTip("Rendered by hmi-ui (the panel's own renderer)"
                                    if self.preview_renderer_name == "hmi-ui"
                                    else "Rendered by Qt/QML (hmi-ui not found)")
        self.view.setFrameShape(QFrame.NoFrame)
        split.addWidget(self.view)
        self._build_composer()

        # -- right: what is selected, then Design / Data / Actions -------------
        inspector = QFrame(); inspector.setObjectName("designerInspector")
        inspector_layout = QVBoxLayout(inspector); inspector_layout.setContentsMargins(0, 0, 0, 0); inspector_layout.setSpacing(0)
        self.properties = PropertyEditor(self.registry); self.bindings = BindingEditor(self.registry)
        self.actions = ActionEditor(self.registry)
        head = QFrame(); head.setObjectName("inspectorHead")
        head_layout = QVBoxLayout(head); head_layout.setContentsMargins(14, 10, 14, 10); head_layout.setSpacing(2)
        self.selection_title = QLabel("Nothing selected"); self.selection_title.setObjectName("inspectorTitle")
        self.selection_chip = QLabel("None"); self.selection_chip.setObjectName("panelMeta")
        head_layout.addWidget(self.selection_title); head_layout.addWidget(self.selection_chip)
        inspector_layout.addWidget(head)
        self.inspector_tabs = QTabWidget(); self.inspector_tabs.setObjectName("designerInspectorTabs")
        self.inspector_tabs.setDocumentMode(True)
        self._compact_tabs(self.inspector_tabs)
        design_tab = QWidget(); design_tab.setObjectName("panelBody")
        design_layout = QVBoxLayout(design_tab); design_layout.setContentsMargins(0, 0, 0, 0); design_layout.setSpacing(0)
        design_layout.addWidget(self._build_size_row())
        design_layout.addWidget(self._scroll_panel(self.properties), 1)
        self.inspector_tabs.addTab(design_tab, "Design")
        self.inspector_tabs.addTab(self._scroll_panel(self.bindings), "Data")
        self.inspector_tabs.addTab(self._scroll_panel(self.actions), "Actions")
        inspector_layout.addWidget(self.inspector_tabs, 1)
        split.addWidget(inspector)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        sidebar.setMinimumWidth(220); inspector.setMinimumWidth(260)
        split.setSizes([250, 700, 300]); layout.addWidget(split, 1)
        self.scene.widgetDropped.connect(self.add_widget); self.scene.selectionIdsChanged.connect(self._selection_changed)
        self.scene.geometryEdited.connect(self._geometry_command); self.tree.itemSelectionChanged.connect(self._tree_selection)
        self.tree.itemChanged.connect(self._tree_renamed); self.properties.propertyEdited.connect(self._property_command)
        self.properties.geometryEdited.connect(self._single_geometry_command); self.bindings.bindingEdited.connect(self._binding_command)
        self.actions.actionEdited.connect(self._action_command)
        self.properties.assetRequested.connect(self._choose_property_asset)
        self.scene.assetRequested.connect(self._asset_requested)
        self.scene.textRequested.connect(self._text_requested)
        self.scene.reparentRequested.connect(self._reparent_requested)
        self.scene.contextMenuRequested.connect(self._show_context_menu)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.view.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%"))
        # Nothing is selected yet; say so, rather than leaving a blank panel
        # whose purpose only becomes clear after the first click.
        self.properties.set_widget(None)
        self.bindings.set_widget(None)

    def _make_preview_renderer(self):
        """The panel's own renderer when its binary is at hand, else Qt/QML.

        Looked up here, not at import: the Studio must open without the
        binary (a checkout that never built it, a Windows build without the
        port), and a broken lookup must never stop the Designer opening.
        """
        binary = None
        try:
            from designer.preview import NativeRenderer, find_hmi_ui
            binary = find_hmi_ui()
        except Exception:      # noqa: BLE001 -- no renderer is worth the Designer
            binary = None
        if binary:
            renderer = NativeRenderer(binary, parent=self)
            self.preview_renderer_name = "hmi-ui"
        else:
            renderer = QmlPreviewRenderer(self.generator, self)
            self.preview_renderer_name = "qml"
        return renderer

    def _sync_preview_background(self):
        """The design's screen colour is what hmi-ui draws behind a widget;
        the QML renderer draws on transparency and has no such setting. A
        widget's cache key does not carry the background, so a change
        drops the renders made over the old one."""
        renderer = self.scene.qml_previews
        if self.preview_renderer_name != "hmi-ui" or renderer is None:
            return
        if getattr(renderer, "background", None) != self.project.screen.background:
            renderer.background = self.project.screen.background
            renderer.clear()

    def apply_theme(self, theme: str) -> None:
        """Re-render Designer icons and chrome for the active theme.

        The vocabulary is the AI Design tab's, which in turn mirrors
        OpenDesign: one panel surface a step above the page, hairline borders
        between regions instead of boxed groups, muted 28px icon tools that
        light up on hover, uppercase captions, and the primary colour spent
        only on the one action that leaves the Studio.
        """
        self.theme = theme
        self.properties.theme = theme
        for action, name in self._designer_icon_names.items():
            action.setIcon(icon(name, 16, color("foreground", theme)))
        for button, (name, token) in getattr(self, "_designer_toolbutton_icons", {}).items():
            button.setIcon(icon(name, 16, color(token, theme)))
            button.setIconSize(QSize(16, 16))
        self._palette_search_icon.setIcon(icon("search", 14, color("mutedForeground", theme)))
        for name, label in getattr(self, "_panel_icons", {}).items():
            label.setPixmap(icon(name, 14, color("mutedForeground", theme)).pixmap(14, 14))
        self._send_button.setIcon(icon("send", 14, color("primaryForeground", theme)))
        self._composer_icon.setPixmap(icon("sparkles", 16, color("primary", theme)).pixmap(16, 16))
        for empty in self.findChildren(_EmptyState):
            empty.retheme(theme)
        # The canvas previews read Shadcn's own tokens, which have a light and
        # a dark column. Point them at the same one the rest of the Studio is
        # showing, or a component previews in the palette it will not ship in.
        widget_previews.set_theme_mode(theme)
        self.palette.apply_theme(theme)
        self.scene.set_theme(theme)
        if self._code_window is not None:
            self._code_window.apply_theme(theme)
        t = lambda name: color(name, theme)
        bg, card, border = t("background"), t("card"), t("border")
        fg, muted_fg = t("foreground"), t("mutedForeground")
        primary, primary_fg, info = t("primary"), t("primaryForeground"), t("info")
        tint = _rgba
        dark = theme == "dark"
        # Surfaces: panels sit one step above the page so the canvas well
        # reads as the deepest layer; fields step up again inside them.
        surface = card if dark else bg
        raised = tint(fg, 0.035) if dark else tint(fg, 0.025)
        hover = tint(fg, 0.06)
        mono = '"Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
        arrow = _icon_file("chevron-down", 12, muted_fg)
        closed = _icon_file("chevron-right", 12, muted_fg)
        opened = _icon_file("chevron-down", 12, muted_fg)
        check = _icon_file("check", 11, primary_fg)
        primary_grad = (f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {primary}, "
                        f"stop:1 {tint(info, 0.95)})")
        self.setStyleSheet(f"""
            QWidget#designerWorkspace {{ background: {bg}; }}
            QWidget#designerWorkspace QWidget {{ font-size: 12px; }}
            QSplitter#designerMainSplitter::handle,
            QSplitter#designerSideSplitter::handle {{ background: {border}; }}
            QFrame#designerSidebar, QFrame#designerInspector,
            QFrame#designerPanel, QWidget#panelBody {{ background: {surface}; border: none; }}
            QFrame#panelHead {{ background: {surface}; border-bottom: 1px solid {border}; }}
            QLabel#panelIcon, QLabel#panelCaption, QLabel#panelMeta, QLabel#barCaption,
            QLabel#zoomLabel, QLabel#panelHint, QLabel#inspectorTitle, QLabel#inspectorSection,
            QLabel#propLabel, QLabel#pairTag, QLabel#emptyStateTitle, QLabel#emptyStateBody,
            QWidget#inspectorHeading, QFrame#emptyState, QWidget#barSpacer {{ background: transparent; }}
            QLabel#panelCaption {{ color: {muted_fg}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#panelMeta {{ color: {muted_fg}; font-size: 11px; font-family: {mono}; }}
            QLabel#panelHint {{ color: {muted_fg}; font-size: 12px; }}

            /* -- toolbars ---------------------------------------------------- */
            QToolBar#designerPrimaryToolbar, QToolBar#designerCanvasToolbar {{
                background: {surface}; border: none; border-bottom: 1px solid {border};
                padding: 0 10px; spacing: 2px;
            }}
            QToolBar#designerPrimaryToolbar::separator, QToolBar#designerCanvasToolbar::separator {{
                background: {border}; width: 1px; margin: 9px 6px;
            }}
            QToolBar#designerCanvasToolbar::separator {{ margin: 7px 6px; }}
            QToolBar QToolButton {{
                background: transparent; color: {fg}; border: 1px solid transparent;
                border-radius: 6px; padding: 0 8px; min-height: 28px; max-height: 28px;
            }}
            QToolBar QToolButton[compact="true"] {{ padding: 0; min-width: 28px; max-width: 28px; }}
            QToolBar QToolButton:hover {{ background: {hover}; }}
            QToolBar QToolButton:pressed {{ background: {tint(primary, 0.15)}; }}
            QToolBar QToolButton:checked {{ background: {tint(primary, 0.14)}; border-color: {tint(primary, 0.35)}; }}
            QToolBar QToolButton:disabled {{ color: {tint(fg, 0.35)}; }}
            QToolBar QToolButton::menu-indicator {{ image: none; width: 0px; }}
            QLabel#barCaption {{ color: {muted_fg}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
            QLabel#zoomLabel {{ color: {muted_fg}; font-size: 11px; font-family: {mono}; }}
            /* `height` too: the app-wide QComboBox/QLineEdit rule sets height:
               36px, which Qt applies as a hard minimum unless overridden. */
            QLineEdit#barField, QComboBox#barField, QSpinBox#barField {{
                background: {raised}; color: {fg}; border: 1px solid {border}; border-radius: 6px;
                padding: 0 8px; height: 26px; min-height: 24px; max-height: 26px; font-size: 12px;
            }}
            QSpinBox#barField {{ font-family: {mono}; padding-right: 6px; }}
            QLineEdit#barField:hover, QComboBox#barField:hover, QSpinBox#barField:hover {{
                border-color: {tint(primary, 0.55)}; }}
            QLineEdit#barField:focus, QComboBox#barField:focus, QSpinBox#barField:focus,
            QComboBox#barField:on {{ border: 1px solid {primary}; background: {tint(primary, 0.06)}; }}
            QPushButton#primaryAction {{
                background: {primary_grad}; color: {primary_fg}; border: none; border-radius: 7px;
                padding: 0 14px; font-size: 12px; font-weight: 600;
                min-height: 30px; max-height: 30px; height: 30px;
            }}
            QPushButton#primaryAction:hover {{ background: {tint(primary, 0.85)}; }}
            QPushButton#primaryAction:pressed {{ background: {tint(primary, 0.7)}; }}
            QPushButton#primaryAction:disabled {{ background: {tint(fg, 0.12)}; color: {tint(fg, 0.4)}; }}
            QPushButton#secondaryAction {{
                background: transparent; color: {fg}; border: 1px solid {border};
                border-radius: 7px; padding: 0 12px; font-size: 12px; font-weight: 500;
                min-height: 28px; max-height: 30px; height: 30px;
            }}
            QPushButton#secondaryAction:hover {{ background: {hover}; border-color: {tint(primary, 0.55)}; }}
            QPushButton#secondaryAction:pressed {{ background: {tint(primary, 0.15)}; }}
            QPushButton#secondaryAction:disabled {{ color: {tint(fg, 0.35)}; border-color: {tint(fg, 0.08)}; }}
            /* The Data tab's rule buttons: the app-wide button size swamps the inspector. */
            QPushButton#extraAddRule, QPushButton#extraRemoveRule {{
                background: transparent; color: {fg}; border: 1px solid {border};
                border-radius: 7px; padding: 0 12px; font-size: 12px; font-weight: 500;
                min-height: 28px; max-height: 30px; height: 30px;
            }}
            QPushButton#extraAddRule:hover, QPushButton#extraRemoveRule:hover {{
                background: {hover}; border-color: {tint(primary, 0.55)}; }}
            QTableWidget#extraRules {{ min-height: 84px; }}

            /* -- combos everywhere in the workspace --------------------------- */
            QWidget#designerWorkspace QComboBox::drop-down {{
                border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
            QWidget#designerWorkspace QComboBox::down-arrow {{ image: url("{arrow}"); width: 12px; height: 12px; }}
            QWidget#designerWorkspace QComboBox QAbstractItemView {{
                background: {card}; color: {fg}; border: 1px solid {border}; border-radius: 8px;
                padding: 4px; outline: 0; selection-background-color: {tint(primary, 0.18)}; selection-color: {fg}; }}
            QWidget#designerWorkspace QComboBox QLineEdit {{
                background: transparent; border: none; padding: 0; color: {fg}; min-height: 0; }}

            /* -- widget library / layers -------------------------------------- */
            QLineEdit#panelSearch {{
                background: {raised}; color: {fg}; border: 1px solid {border}; border-radius: 8px;
                padding: 0 8px 0 4px; min-height: 30px; max-height: 30px; font-size: 12px;
            }}
            QLineEdit#panelSearch:hover {{ border-color: {tint(primary, 0.55)}; }}
            QLineEdit#panelSearch:focus {{ border: 1px solid {primary}; background: {tint(primary, 0.06)}; }}
            QToolButton#iconToggle {{ background: {raised}; border: 1px solid {border}; border-radius: 8px; padding: 0; }}
            QToolButton#iconToggle:hover {{ background: {hover}; border-color: {tint(primary, 0.55)}; }}
            QToolButton#iconToggle:checked {{ background: {tint(primary, 0.14)}; border-color: {tint(primary, 0.5)}; }}
            QTreeWidget#designerPalette, QTreeWidget#designerObjectTree {{
                background: {surface}; border: none; border-radius: 0; padding: 4px 6px;
                outline: 0; show-decoration-selected: 0;
            }}
            QTreeWidget#designerPalette::item {{ padding: 2px 4px; border-radius: 6px; color: {fg}; }}
            QTreeWidget#designerObjectTree::item {{ padding: 0 4px; min-height: 26px; border-radius: 6px; color: {fg}; }}
            QTreeWidget#designerPalette::item:hover, QTreeWidget#designerObjectTree::item:hover {{ background: {hover}; }}
            QTreeWidget#designerPalette::item:selected, QTreeWidget#designerObjectTree::item:selected {{
                background: {tint(primary, 0.16)}; color: {fg}; }}
            QTreeWidget#designerPalette::item:has-children {{ color: {muted_fg}; background: transparent; }}
            QTreeWidget#designerPalette::branch {{ image: none; border-image: none; background: transparent; }}
            /* Opaque, not transparent: the native style still paints its
               connector lines and the row highlight into the branch gutter,
               and only a solid fill covers them. */
            QTreeWidget#designerObjectTree::branch,
            QTreeWidget#designerObjectTree::branch:selected,
            QTreeWidget#designerObjectTree::branch:hover,
            QTreeWidget#designerObjectTree::branch:has-siblings:!adjoins-item,
            QTreeWidget#designerObjectTree::branch:has-siblings:adjoins-item,
            QTreeWidget#designerObjectTree::branch:!has-children:!has-siblings:adjoins-item {{
                background: {surface}; border-image: none; image: none; }}
            QTreeWidget#designerObjectTree::branch:has-children:!has-siblings:closed,
            QTreeWidget#designerObjectTree::branch:closed:has-children:has-siblings {{
                image: url("{closed}"); border-image: none; }}
            QTreeWidget#designerObjectTree::branch:open:has-children:!has-siblings,
            QTreeWidget#designerObjectTree::branch:open:has-children:has-siblings {{
                image: url("{opened}"); border-image: none; }}

            /* -- inspector ----------------------------------------------------- */
            QScrollArea#designerInspectorScroll,
            QScrollArea#designerInspectorScroll > QWidget > QWidget,
            QWidget#propertyEditor, QWidget#bindingEditor {{ background: {surface}; border: none; }}
            QLabel#inspectorTitle {{ color: {fg}; font-size: 13px; font-weight: 600; }}
            QLabel#inspectorSection {{ color: {muted_fg}; font-size: 10px; font-weight: 600; letter-spacing: 1px;
                                       padding-top: 8px; padding-bottom: 2px; }}
            QLabel#propLabel {{ color: {muted_fg}; font-size: 12px; font-weight: 500; }}
            QLabel#propLabel:disabled {{ color: {tint(fg, 0.3)}; }}
            QLineEdit#propField, QComboBox#propField, QSpinBox#propField, QDoubleSpinBox#propField {{
                background: {raised}; color: {fg}; border: 1px solid {border}; border-radius: 7px;
                padding: 0 8px; min-height: 28px; max-height: 30px; font-size: 12px;
            }}
            QSpinBox#propField, QDoubleSpinBox#propField {{ font-family: {mono}; }}
            QLineEdit#propField:hover, QComboBox#propField:hover, QSpinBox#propField:hover,
            QDoubleSpinBox#propField:hover {{ border-color: {tint(primary, 0.55)}; }}
            QLineEdit#propField:focus, QComboBox#propField:focus, QComboBox#propField:on,
            QSpinBox#propField:focus, QDoubleSpinBox#propField:focus {{
                border: 1px solid {primary}; background: {tint(primary, 0.06)}; }}
            QLineEdit#propField:disabled, QComboBox#propField:disabled, QSpinBox#propField:disabled,
            QDoubleSpinBox#propField:disabled {{ color: {tint(fg, 0.4)}; }}
            QFrame#pairField {{ background: {raised}; border: 1px solid {border}; border-radius: 7px; }}
            QFrame#pairField:hover {{ border-color: {tint(primary, 0.55)}; }}
            QFrame#pairField:disabled {{ border-color: {tint(fg, 0.08)}; }}
            QLabel#pairTag {{ color: {muted_fg}; font-size: 10px; font-weight: 600; }}
            QSpinBox#pairValue {{ background: transparent; border: none; color: {fg}; padding: 0;
                                  font-family: {mono}; font-size: 12px; min-height: 0; }}
            QSpinBox#pairValue:disabled {{ color: {tint(fg, 0.4)}; }}
            QToolButton#swatch {{ border: 1px solid {border}; border-radius: 7px; }}
            QToolButton#swatch:hover {{ border-color: {tint(primary, 0.7)}; }}
            QCheckBox#propSwitch {{ color: {muted_fg}; font-size: 12px; spacing: 8px; background: transparent; }}
            QCheckBox#propSwitch:hover {{ color: {fg}; }}
            QCheckBox#propSwitch::indicator {{ width: 15px; height: 15px; border-radius: 5px;
                                               border: 1px solid {border}; background: {raised}; }}
            QCheckBox#propSwitch::indicator:hover {{ border-color: {tint(primary, 0.6)}; }}
            QCheckBox#propSwitch::indicator:checked {{ background: {primary}; border-color: {primary};
                                                       image: url("{check}"); }}
            QLabel#chip {{ background: {raised}; color: {muted_fg}; border-radius: 10px; border: 1px solid {border};
                           padding: 1px 8px; font-size: 10px; font-family: {mono}; min-height: 16px; }}
            QLabel#emptyStateIcon {{ background: {tint(primary, 0.12)}; border: 1px solid {tint(primary, 0.35)};
                                     border-radius: 20px; }}
            QLabel#emptyStateTitle {{ color: {fg}; font-size: 13px; font-weight: 600; }}
            QLabel#emptyStateBody {{ color: {muted_fg}; font-size: 12px; }}

            /* -- Studio 2: side and inspector tabs ------------------------------ */
            QTabWidget#designerSideTabs::pane, QTabWidget#designerInspectorTabs::pane {{
                border: none; border-top: 1px solid {border}; background: {surface}; top: -1px; }}
            QTabWidget#designerSideTabs QTabBar, QTabWidget#designerInspectorTabs QTabBar {{
                background: {surface}; qproperty-drawBase: 0; }}
            QTabWidget#designerSideTabs QTabBar::tab, QTabWidget#designerInspectorTabs QTabBar::tab {{
                background: transparent; color: {muted_fg}; border: none; border-radius: 6px;
                padding: 5px 12px; margin: 6px 2px 6px 0; font-size: 12px; font-weight: 500;
                /* The Studio's workspaceTabs rule (min-width 96px) reaches
                   these nested bars too and pushed the third tab off. */
                min-width: 0px; }}
            QTabWidget#designerSideTabs QTabBar::tab:first, QTabWidget#designerInspectorTabs QTabBar::tab:first {{
                margin-left: 8px; }}
            QTabWidget#designerSideTabs QTabBar::tab:hover:!selected,
            QTabWidget#designerInspectorTabs QTabBar::tab:hover:!selected {{ background: {hover}; color: {fg}; }}
            QTabWidget#designerSideTabs QTabBar::tab:selected,
            QTabWidget#designerInspectorTabs QTabBar::tab:selected {{ background: {tint(fg, 0.09)}; color: {fg}; }}
            QFrame#inspectorHead, QFrame#sizeRow {{ background: {surface}; border: none; }}
            QFrame#inspectorHead {{ border-bottom: 1px solid {border}; }}
            QFrame#sizeSegment {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}
            QToolButton#sizeOption {{ background: transparent; color: {muted_fg}; border: none; border-radius: 6px;
                                      font-size: 12px; padding: 0 6px; }}
            QToolButton#sizeOption:hover {{ color: {fg}; background: {hover}; }}
            QToolButton#sizeOption:checked {{ background: {tint(fg, 0.10)}; color: {fg}; }}
            QFrame#sizeRow:disabled QToolButton#sizeOption {{ color: {tint(fg, 0.3)}; }}
            QToolButton#pageButton, QToolButton#fileMenuButton {{ background: transparent; border: 1px solid transparent;
                                       border-radius: 6px; color: {fg}; padding: 0 6px; }}
            QToolButton#pageButton:hover, QToolButton#fileMenuButton:hover {{ background: {hover}; }}
            QToolButton#fileMenuButton::menu-indicator {{ image: none; width: 0px; }}

            /* -- the AI composer over the canvas -------------------------------- */
            QFrame#aiComposer {{ background: transparent; border: none; }}
            QLabel#composerReply {{ background: {card}; color: {fg}; border: 1px solid {border}; border-radius: 10px;
                                    padding: 7px 12px; margin-bottom: 6px; font-size: 12px; }}
            QLabel#composerReply[busy="true"] {{ color: {primary}; border-color: {tint(primary, 0.45)}; }}

            /* -- design chat --------------------------------------------------- */
            QPlainTextEdit#chatHistory {{
                background: {surface}; color: {tint(fg, 0.88)}; border: none; border-radius: 0;
                padding: 6px 8px; font-family: {mono}; font-size: 11px;
                selection-background-color: {tint(primary, 0.35)};
            }}
            QFrame#composerCard {{ background: {card}; border: 1px solid {tint(primary, 0.35)}; border-radius: 14px; }}
            QFrame#composerCard[focused="true"] {{ border: 1px solid {primary}; background: {tint(primary, 0.07)}; }}
            QLineEdit#chatInput {{ background: transparent; border: none; color: {fg}; font-size: 12px;
                                   padding: 0; min-height: 0; selection-background-color: {tint(primary, 0.35)}; }}
            QToolButton#sendButton {{ background: {primary_grad}; border: none; border-radius: 14px; padding: 0; }}
            QToolButton#sendButton:hover {{ background: {tint(primary, 0.85)}; }}
            QToolButton#sendButton:pressed {{ background: {tint(primary, 0.7)}; }}
            QLabel#kbdHint {{ color: {muted_fg}; font-size: 10px; font-family: {mono};
                              border: 1px solid {border}; border-radius: 5px; padding: 1px 5px; background: transparent; }}
        """)

    # -- Studio 2: the AI composer over the canvas -----------------------------
    # One field for every change in words. The small vocabulary ("add Value
    # Tile", "set gauge1 label=Flow", "bind gauge1 value=ai.flow") applies
    # here, offline and undoable; anything else is a request for the AI, which
    # the Studio routes to the AI Design view with the page and the selection
    # as context (aiRequested). Replaces the "Design chat" panel.
    def _build_composer(self):
        self.composer = QFrame(self.view); self.composer.setObjectName("aiComposer")
        shadow = QGraphicsDropShadowEffect(self.composer)
        shadow.setBlurRadius(28); shadow.setOffset(0, 8); shadow.setColor(QColor(0, 0, 0, 110))
        self.composer.setGraphicsEffect(shadow)
        outer = QVBoxLayout(self.composer); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        self.chat_reply = QLabel(""); self.chat_reply.setObjectName("composerReply")
        self.chat_reply.setWordWrap(True); self.chat_reply.hide()
        outer.addWidget(self.chat_reply)
        self.composer_card = QFrame(); self.composer_card.setObjectName("composerCard")
        self.composer_card.setProperty("focused", False)
        row = QHBoxLayout(self.composer_card); row.setContentsMargins(12, 5, 5, 5); row.setSpacing(8)
        self._composer_icon = QLabel(); self._composer_icon.setFixedSize(16, 16)
        self.chat_input = QLineEdit(); self.chat_input.setObjectName("chatInput")
        self.chat_input.setPlaceholderText("Ask AI to change this design · or: add Value Tile, set …, bind …")
        self.chat_input.setAccessibleName("Ask AI to change the design")
        self.chat_input.installEventFilter(self)
        self.composer_scope = QLabel("Whole page"); self.composer_scope.setObjectName("kbdHint")
        self._send_button = QToolButton(); self._send_button.setObjectName("sendButton")
        self._send_button.setFixedSize(28, 28); self._send_button.setCursor(Qt.PointingHandCursor)
        self._send_button.setToolTip("Send (Enter)")
        row.addWidget(self._composer_icon); row.addWidget(self.chat_input, 1)
        row.addWidget(self.composer_scope); row.addWidget(self._send_button)
        outer.addWidget(self.composer_card)
        self._send_button.clicked.connect(self._apply_chat); self.chat_input.returnPressed.connect(self._apply_chat)
        # The text-command log, kept for the record (and code that reads it);
        # the composer shows only the latest reply.
        self.chat_history = QPlainTextEdit(self); self.chat_history.setReadOnly(True); self.chat_history.hide()
        self._reply_timer = QTimer(self); self._reply_timer.setSingleShot(True)
        self._reply_timer.timeout.connect(self.chat_reply.hide)
        self.view.viewport().installEventFilter(self)
        self._place_composer()

    def _place_composer(self):
        """Bottom centre of the canvas, at most 560 px wide."""
        if not hasattr(self, "composer"):
            return
        area = self.view.viewport().geometry()
        width = max(260, min(560, area.width() - 48))
        self.composer.setFixedWidth(width)
        self.composer.adjustSize()
        self.composer.move(area.x() + (area.width() - width) // 2,
                           area.y() + area.height() - self.composer.height() - 18)
        self.composer.raise_()

    def show_composer_reply(self, text: str, busy: bool = False):
        """A line above the composer: the last command's result, or the AI's
        progress. Busy replies stay until replaced; others fade after 8 s."""
        self.chat_reply.setText(text)
        self.chat_reply.setProperty("busy", busy)
        self.chat_reply.style().unpolish(self.chat_reply); self.chat_reply.style().polish(self.chat_reply)
        self.chat_reply.setVisible(bool(text))
        self._send_button.setEnabled(not busy)
        if busy:
            self._reply_timer.stop()
        else:
            self._reply_timer.start(8000)
        self._place_composer()

    aiRequested = Signal(str)

    def ai_context(self) -> str:
        """The page and the selection, in the words a planned design uses:
        what the AI is asked to change."""
        page = self.current_page
        lines = [f"Current design: page \"{page.name}\" on a "
                 f"{self.project.screen.width}x{self.project.screen.height} screen."]
        try:
            from designer.layout.compiler import infer_sections
            title, sections, header, _notes = infer_sections(copy.deepcopy(page), self.registry)
        except Exception:
            title, sections, header = "", [], []
        if title:
            lines.append(f"Title: {title}")
        for section in sections:
            parts = []
            for widget in section.widgets:
                tag = next((b.tag for b in widget.bindings.values() if getattr(b, "tag", "")), "")
                parts.append(f"{self._display_name(widget)} ({widget.type}" + (f", {tag}" if tag else "") + ")")
            lines.append(f"- {section.title or section.role} [{section.role}]: " + "; ".join(parts))
        if header:
            # A logo keeps its picture only while the request names its file.
            def named(w):
                source = w.properties.get("source") if w.type == "Image" else ""
                return f"{self._display_name(w)} (Image, {source})" if source else self._display_name(w)
            lines.append("Header: " + "; ".join(named(w) for w in header))
        selected = self.scene.selected_models()
        if selected:
            lines.append("Selected: " + ", ".join(f"{self._display_name(m)} ({m.type}, id {m.id})" for m in selected))
        return "\n".join(lines)

    def eventFilter(self, watched, event):
        # The composer card, not the borderless line edit inside it, is what
        # shows focus; QSS has no :focus-within, so relay it by hand.
        if watched is getattr(self, "chat_input", None) and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.composer_card.setProperty("focused", event.type() == QEvent.FocusIn)
            self.composer_card.style().unpolish(self.composer_card)
            self.composer_card.style().polish(self.composer_card)
        if hasattr(self, "view") and watched is self.view.viewport() and event.type() in (QEvent.Resize, QEvent.Show):
            self._place_composer()
        return super().eventFilter(watched, event)

    def _apply_chat(self):
        """Apply the small text vocabulary here; send anything else to the AI.

        The vocabulary needs no network and is undoable like any edit; a
        request in plain words goes out through aiRequested, with the page and
        the selection as context (the Studio routes it to the AI Design view).
        """
        command = self.chat_input.text().strip()
        if not command: return
        self.chat_history.appendPlainText(f"> {command}")
        try:
            response = self.apply_text_command(command)
        except ValueError as exc:
            # Only when something will answer: a bare workspace (tests, a
            # build without the AI view) keeps the old "use add, ..." reply.
            # "Add the customer's logo to the header" starts like the add
            # command but names no widget: that is a sentence for the AI too.
            not_a_command = str(exc) == "use add, remove, set, or bind" or str(exc).startswith("unknown widget")
            if not_a_command and self.receivers(SIGNAL("aiRequested(QString)")) > 0:
                self.chat_input.clear()
                self.chat_history.appendPlainText("Sent to the AI.")
                self.aiRequested.emit(command)
                return
            response = f"Could not apply: {exc}"
        else:
            self.chat_input.clear()
        self.chat_history.appendPlainText(response)
        self.show_composer_reply(response)

    # -- Studio 2: Pages tab, size wishes, readable layer names ----------------
    def _build_pages_tab(self):
        """The page list and the screen it is designed for, with the project's
        deployment name: the settings that used to fill a second toolbar."""
        body = QWidget(); body.setObjectName("panelBody")
        form = QVBoxLayout(body); form.setContentsMargins(12, 12, 12, 12); form.setSpacing(6)

        def caption(text):
            label = QLabel(text.upper()); label.setObjectName("panelCaption")
            form.addWidget(label)

        caption("Page")
        page_row = QHBoxLayout(); page_row.setSpacing(4)
        page_row.addWidget(self.pages, 1)
        for text, slot, icon_name in (("New Page", self.new_page, "plus"),
                                      ("Duplicate Page", self.duplicate_page, "copy"),
                                      ("Delete Page", self.delete_page, "trash")):
            button = QToolButton(); button.setObjectName("pageButton")
            button.setToolTip(text); button.setFixedSize(26, 26); button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(slot)
            self._designer_toolbutton_icons[button] = (icon_name, "foreground")
            page_row.addWidget(button)
        form.addLayout(page_row)
        form.addSpacing(10)
        caption("Screen")
        size_row = QHBoxLayout(); size_row.setSpacing(6)
        for text, widget in (("W", self.screen_width), ("H", self.screen_height)):
            tag = QLabel(text); tag.setObjectName("propLabel")
            size_row.addWidget(tag); size_row.addWidget(widget)
        size_row.addStretch()
        form.addLayout(size_row)
        theme_row = QHBoxLayout(); theme_row.setSpacing(6)
        tag = QLabel("Theme"); tag.setObjectName("propLabel")
        theme_row.addWidget(tag); theme_row.addWidget(self.screen_theme, 1)
        form.addLayout(theme_row)
        form.addSpacing(10)
        caption("Deployment name")
        form.addWidget(self.project_name)
        form.addStretch()
        return body

    @staticmethod
    def _compact_tabs(tabs):
        """Three short tabs that always fit their pane: no scroll arrows (the
        app-wide tab style is sized for the Studio's top level)."""
        bar = tabs.tabBar()
        bar.setUsesScrollButtons(False)
        bar.setExpanding(False)
        bar.setElideMode(Qt.ElideNone)

    SIZE_WISHES = (("compact", "Compact"), ("normal", "Normal"), ("large", "Large"))

    def _build_size_row(self):
        """Compact / Normal / Large for the selected widget: a wish the layout
        compiler honours (designer.layout.compiler.SIZE_MARK); on a compiled
        page it recompiles the page at once."""
        row = QFrame(); row.setObjectName("sizeRow")
        layout = QVBoxLayout(row); layout.setContentsMargins(14, 10, 14, 6); layout.setSpacing(6)
        caption = QLabel("SIZE ON SCREEN"); caption.setObjectName("inspectorSection")
        layout.addWidget(caption)
        segment = QFrame(); segment.setObjectName("sizeSegment")
        seg_layout = QHBoxLayout(segment); seg_layout.setContentsMargins(3, 3, 3, 3); seg_layout.setSpacing(2)
        self.size_buttons = {}
        for value, text in self.SIZE_WISHES:
            button = QToolButton(); button.setObjectName("sizeOption"); button.setText(text)
            button.setCheckable(True); button.setAutoExclusive(True); button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed); button.setFixedHeight(26)
            button.clicked.connect(lambda _checked=False, v=value: self.set_size_wish(v))
            seg_layout.addWidget(button)
            self.size_buttons[value] = button
        layout.addWidget(segment)
        self.size_hint = QLabel(""); self.size_hint.setObjectName("panelHint"); self.size_hint.setWordWrap(True)
        layout.addWidget(self.size_hint)
        self.size_row = row
        self._sync_size_row([])
        return row

    def _sync_size_row(self, models):
        from designer.layout.compiler import SIZE_FACTORS, SIZE_MARK, is_planned
        model = models[0] if len(models) == 1 else None
        self.size_row.setEnabled(model is not None)
        wish = str(model.properties.get(SIZE_MARK, "") if model else "").lower()
        current = {"small": "compact", "tight": "compact", "big": "large", "prominent": "large"}.get(wish, wish)
        if current not in SIZE_FACTORS or current in ("medium", "default"):
            current = "normal"
        for value, button in self.size_buttons.items():
            button.blockSignals(True); button.setChecked(model is not None and value == current); button.blockSignals(False)
        if model is None:
            self.size_hint.setText("Select a widget to size it.")
        elif is_planned(self.current_page):
            self.size_hint.setText("The layout recompiles around the new size.")
        else:
            self.size_hint.setText("Applies when the page is compiled (Tidy up on an AI page).")

    def set_size_wish(self, value: str):
        """Undoably set the selected widget's size wish; on a compiled page,
        recompile the page around it."""
        from designer.layout.compiler import SIZE_MARK, compile_page, is_planned
        models = self.scene.selected_models()
        if len(models) != 1:
            return
        model_id = models[0].id
        page = self.current_page
        before = copy.deepcopy(page.widgets)
        target = next((w for w in page.walk() if w.id == model_id), None)
        if target is None:
            return
        if value == "normal":
            target.properties.pop(SIZE_MARK, None)
        else:
            target.properties[SIZE_MARK] = value
        if is_planned(page):
            try:
                compile_page(self.project, page, self.registry)
            except Exception as exc:
                page.widgets[:] = before
                self._load_page(select=[model_id])
                self.message.emit(f"Could not recompile: {exc}")
                return
        after = copy.deepcopy(page.widgets)

        def apply(widgets):
            page.widgets[:] = copy.deepcopy(widgets)
            self._load_page(select=[model_id])
            self.designChanged.emit()

        page.widgets[:] = before
        self.undo_stack.push(CallbackCommand(f"Size {value}", lambda: apply(after), lambda: apply(before)))

    def _display_name(self, model) -> str:
        """What a designer calls a widget: a card's heading, a widget's label
        or caption, a text's words, else its id in words."""
        from designer.layout import intake
        if model.type in ("ShCard", "Rectangle", "Item") and model.children:
            heading = next((c for c in model.children if c.type == "Text" and c.id.endswith("Heading")), None)
            if heading is not None and heading.properties.get("text"):
                return str(heading.properties["text"])
        if model.type == "Text":
            text = str(model.properties.get("text", "") or "").strip()
            if text:
                return text if len(text) <= 32 else text[:31] + "…"
        for key in ("_lampLabel", "caption", "title", "label", "text"):
            value = str(model.properties.get(key, "") or "").strip()
            if value and len(value) > 1:
                return value
        return intake.humanise(model.id) or model.id

    def _tree_item_for(self, widget_id):
        """The Layers row of a widget id (rows show names, so search by data)."""
        iterator = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while iterator:
            item = iterator.pop()
            if item.data(0, Qt.UserRole) == widget_id:
                return item
            iterator.extend(item.child(i) for i in range(item.childCount()))
        return None

    def apply_text_command(self, command: str) -> str:
        text = command.strip()
        add_match = re.fullmatch(r"add\s+(.+?)(?:\s+(?:named|as)\s+([A-Za-z_]\w*))?", text, re.I)
        if add_match:
            requested = re.sub(r"[ _-]", "", add_match.group(1)).lower()
            definition = next((d for d in self.registry.definitions()
                               if re.sub(r"[ _-]", "", d.display_name).lower() == requested
                               or d.type.lower() == requested), None)
            if not definition: raise ValueError(f"unknown widget {add_match.group(1)!r}")
            self.add_widget(definition.type, 20, 20)
            model = self.current_page.widgets[-1]
            if add_match.group(2):
                wanted = add_match.group(2)
                if self._find(wanted) and self._find(wanted) is not model: raise ValueError(f"ID {wanted!r} already exists")
                model.id = wanted; self._load_page(select=[wanted])
            return f"Added {definition.display_name} as {model.id}."
        remove_match = re.fullmatch(r"(?:remove|delete)\s+([A-Za-z_]\w*)", text, re.I)
        if remove_match:
            model = self._find(remove_match.group(1))
            if not model or model not in self.current_page.widgets: raise ValueError("widget not found on this page")
            item = self.scene.item_for_id(model.id); self.scene.clearSelection(); item.setSelected(True); self.delete_selected()
            return f"Removed {model.id}."
        set_match = re.fullmatch(r"set\s+([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*=\s*(.+)", text, re.I)
        if set_match:
            model = self._find(set_match.group(1))
            if not model: raise ValueError("widget not found")
            prop, value = set_match.group(2), set_match.group(3)
            definition = self.registry.get(model.type)
            value_type = definition.properties.get(prop) if definition else None
            if value_type is int: value = int(value)
            elif value_type is float: value = float(value)
            elif value_type is bool: value = value.lower() in ("true", "1", "yes", "on")
            item = self.scene.item_for_id(model.id); self.scene.clearSelection(); item.setSelected(True); self._property_command(prop, value)
            return f"Set {model.id}.{prop}."
        bind_match = re.fullmatch(r"bind\s+([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:=|to)\s*([A-Za-z0-9_.-]+)", text, re.I)
        if bind_match:
            model = self._find(bind_match.group(1))
            if not model: raise ValueError("widget not found")
            prop, tag = bind_match.group(2), bind_match.group(3)
            definition = self.registry.get(model.type)
            if not definition or prop not in definition.bindable_properties: raise ValueError(f"{prop!r} is not bindable")
            item = self.scene.item_for_id(model.id); self.scene.clearSelection(); item.setSelected(True); self._binding_command(prop, DesignerBinding(tag))
            return f"Bound {model.id}.{prop} to {tag}."
        raise ValueError("use add, remove, set, or bind")

    def _panel(self, title, icon_name, child, trailing=()):
        """A flat side panel: an uppercase caption row over its content.

        Boxed group titles floating on a border read as a settings dialog;
        OpenDesign's inspector separates sections with a hairline and a small
        letter-spaced caption, which is what the AI Design tab does too.
        """
        panel = QFrame(); panel.setObjectName("designerPanel")
        layout = QVBoxLayout(panel); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        head = QFrame(); head.setObjectName("panelHead"); head.setFixedHeight(34)
        row = QHBoxLayout(head); row.setContentsMargins(12, 0, 10, 0); row.setSpacing(7)
        glyph = QLabel(); glyph.setObjectName("panelIcon"); glyph.setFixedSize(14, 14)
        self._panel_icons = getattr(self, "_panel_icons", {})
        self._panel_icons[icon_name] = glyph
        caption = QLabel(title.upper()); caption.setObjectName("panelCaption")
        row.addWidget(glyph); row.addWidget(caption); row.addStretch()
        for widget in trailing:
            row.addWidget(widget, 0, Qt.AlignVCenter)
        layout.addWidget(head); layout.addWidget(child, 1)
        return panel

    def _scroll_panel(self, child):
        area = QScrollArea()
        area.setObjectName("designerInspectorScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setWidget(child)
        return area

    def _shortcuts(self):
        for key, callback in (("Ctrl+Shift+Z", self.undo_stack.redo), ("Ctrl+A", self.select_all),
                              ("Ctrl+Shift+K", self.open_code_window),
                              ("Left", lambda: self.nudge(-1, 0)), ("Right", lambda: self.nudge(1, 0)),
                              ("Up", lambda: self.nudge(0, -1)), ("Down", lambda: self.nudge(0, 1)),
                              ("Shift+Left", lambda: self.nudge(-10, 0)), ("Shift+Right", lambda: self.nudge(10, 0)),
                              ("Shift+Up", lambda: self.nudge(0, -10)), ("Shift+Down", lambda: self.nudge(0, 10))):
            QShortcut(QKeySequence(key), self, activated=callback)
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self)
        self.delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.delete_shortcut.setAutoRepeat(False)
        self.delete_shortcut.activated.connect(self._delete_from_keyboard)

    def _delete_from_keyboard(self):
        """Delete the canvas selection without eating text in an editor."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QPlainTextEdit, QSpinBox,
                              QDoubleSpinBox, QComboBox)):
            return
        self.delete_selected()

    def set_bundle(self, bundle_dir, manifest=None):
        self.bundle_dir = os.path.abspath(bundle_dir) if bundle_dir else ""
        self.scene.project_dir = self.bundle_dir
        if hasattr(self.scene.qml_previews, "project_dir"):
            # The panel's renderer resolves "assets/..." against the bundle.
            self.scene.qml_previews.project_dir = self.bundle_dir or None
            self.scene.qml_previews.clear()
        self.bindings.set_tags((manifest or {}).get("tags_required", []))
        path = os.path.join(self.bundle_dir, "project.edsui") if self.bundle_dir else ""
        if path and os.path.isfile(path):
            self.load_file(path)
            # Projects saved before the name field was introduced inherit the
            # bundle name once, then persist it in project.edsui on save.
            if not self.project.name:
                self.project.name = self._bundle_project_name(manifest)
        else:
            screen = (manifest or {}).get("screen", {})
            self.project = DesignerProject(name=self._bundle_project_name(manifest)); self.project.screen.width = int(screen.get("width", 1280)); self.project.screen.height = int(screen.get("height", 800))
            self.project.screen.theme = theme_of(manifest or {})
            self.file_path = path; self.current_page_index = 0; self._clear_undo(); self._load_page()
            # clear() is silent on an empty stack, so a fresh project would
            # otherwise never reach the Code window.
            self.designChanged.emit()
            self._retarget_to_connected_display()

    def new_ui(self):
        width = self.project.screen.width; height = self.project.screen.height
        name = ""
        if self.isVisible():
            name, accepted = QInputDialog.getText(
                self, "New design", "Project name used for deployment:",
                QLineEdit.Normal, "")
            if not accepted:
                return
            name = name.strip()
            if not NAME_RE.fullmatch(name):
                QMessageBox.warning(
                    self, "Invalid project name",
                    "Use 1-64 lowercase letters, numbers, dots, underscores, or hyphens."
                )
                return
        else:
            name = self._bundle_project_name()
        self.project = DesignerProject(name=name); self.project.screen.width = width; self.project.screen.height = height
        self.file_path = os.path.join(self.bundle_dir, "project.edsui") if self.bundle_dir else ""
        self.current_page_index = 0; self._clear_undo(); self._load_page()
        self.designChanged.emit()

    def open_ui(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open visual UI", self.bundle_dir, "Embedded Display UI (*.edsui)")
        if path: self.load_file(path)

    def load_file(self, path):
        try:
            self.project = DesignerProject.load(path); self.file_path = os.path.abspath(path); self.bundle_dir = os.path.dirname(self.file_path)
            self._drop_unrunnable_actions(self.project)
            self.scene.project_dir = self.bundle_dir
            self.current_page_index = 0; self._clear_undo(); self._load_page(); self.message.emit(f"Opened {path}")
            self.designChanged.emit()
            self._retarget_to_connected_display()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Could not open UI", str(exc))

    def load_project(self, project, label="Apply AI design"):
        """Swap in a generated DesignerProject as one undoable step.

        The AI Design tab hands over a whole project; the current screen
        geometry/theme and project name are kept unless the generated one
        set its own, so a design keeps targeting the connected glass.
        """
        previous = self.project
        self._drop_unrunnable_actions(project)
        # AI titles ("AI Design (partial)") are not manifest names; coerce
        # them here so Preview/Deploy never trip over the contract later.
        # A name the person gave (New design, or an earlier apply) stays: the
        # model's title only names a design that has none yet.
        project.name = previous.name or deployable_name(project.name, self._bundle_project_name())
        project.screen.width = previous.screen.width
        project.screen.height = previous.screen.height
        project.screen.theme = previous.screen.theme
        def apply(value):
            self.project = value; self.current_page_index = 0; self._load_page()
        self.undo_stack.push(CallbackCommand(label, lambda: apply(project), lambda: apply(previous)))
        self.message.emit(f"{label}: {sum(1 for _ in project.all_widgets())} widgets on canvas")
        # The AI Design view draws this same scene, so build up whenever the
        # Studio is on screen, not only when the Designer view is in front.
        if self.window().isVisible():
            self.reveal_page()

    REVEAL_STEP_MS = 70

    def reveal_page(self, skip=0):
        """Bring the page's widgets onto the canvas one by one, in reading order.

        Only the drawing changes: the model, the undo step and the selection
        are as they were. A generated design that appears all at once reads as
        a screenshot; built up card by card it reads as a design. `skip`
        widgets (in that order) are already shown: a reload of the same page
        mid build-up carries on from there.
        """
        from designer.canvas.designer_view import DesignerItem
        self._finish_reveal()

        def ordered(items):
            for item in sorted(items, key=lambda i: (round(i.pos().y() / 8), i.pos().x())):
                yield item
                yield from ordered([c for c in item.childItems() if isinstance(c, DesignerItem)])

        tops = [i for i in self.scene.items() if isinstance(i, DesignerItem) and i.parentItem() is None]
        items = list(ordered(tops))
        for index, item in enumerate(items):
            item.setOpacity(1.0 if index < skip else 0.0)
        self._reveal_queue = items[skip:]
        self._revealed = skip
        self._reveal_ids = self._page_ids()
        self._reveal_timer = QTimer(self)
        self._reveal_timer.timeout.connect(self._reveal_next)
        self._reveal_timer.start(self.REVEAL_STEP_MS)

    def _page_ids(self):
        return {widget.id for widget in self.current_page.walk()}

    def _reveal_next(self):
        queue = getattr(self, "_reveal_queue", [])
        while queue:
            item = queue.pop(0)
            if shiboken6.isValid(item):
                item.setOpacity(1.0)
                self._revealed = getattr(self, "_revealed", 0) + 1
                return
        self._finish_reveal()

    def _finish_reveal(self):
        timer = getattr(self, "_reveal_timer", None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._reveal_timer = None
        for item in getattr(self, "_reveal_queue", []):
            if shiboken6.isValid(item):
                item.setOpacity(1.0)
        self._reveal_queue = []

    def _drop_unrunnable_actions(self, project):
        """Remove actions that can never run, saying so in the console.

        Otherwise the design opens fine and then fails validation at every
        Generate and Deploy.
        """
        for removed in drop_unrunnable_actions(project, self.registry):
            self.message.emit(f"Removed an action that could never run: {removed}")
        # Same reason: a design saved with a reused widget id failed validation
        # on every Generate and Deploy until the id was changed by hand.
        for renamed in ensure_unique_ids(project):
            self.message.emit(renamed)

    def save(self):
        if not self.file_path:
            path, _ = QFileDialog.getSaveFileName(self, "Save visual UI", self.bundle_dir, "Embedded Display UI (*.edsui)")
            if not path: return False
            self.file_path = path if path.lower().endswith(".edsui") else path + ".edsui"
            self.bundle_dir = os.path.dirname(os.path.abspath(self.file_path))
            self.scene.project_dir = self.bundle_dir
        try:
            self.project.save(self.file_path); self.undo_stack.setClean(); self.message.emit(f"Saved {self.file_path}"); return True
        except OSError as exc:
            QMessageBox.critical(self, "Could not save UI", str(exc)); return False

    def parent_id_of(self, model):
        """The container holding this widget; empty for a page-level widget."""
        for candidate in self.current_page.walk():
            if any(child is model for child in candidate.children):
                return candidate.id
        return ""

    def siblings_of(self, parent_id):
        """The list a widget lives in: a container's children, or the page."""
        parent = self._find(parent_id) if parent_id else None
        definition = self.registry.get(parent.type) if parent else None
        if parent is not None and definition is not None and definition.container:
            return parent.children
        return self.current_page.widgets

    def save_selection_as_custom(self, _checked=False, name=None):
        """Save the selected widgets as a custom widget: one palette entry that
        inserts the whole group, on any page of any project."""
        models = self.scene.selected_models()
        # A child selected with its container is already inside it.
        models = [m for m in models if not any(m is not o and m in list(o.walk()) for o in models)]
        if not models:
            self.message.emit("Select the widgets to save as a custom widget first")
            return None
        if name is None:
            suggested = self._display_name(models[0]) if len(models) == 1 else ""
            name, accepted = QInputDialog.getText(self, "Save as custom widget",
                                                  "Name in the palette:", QLineEdit.Normal, suggested)
            if not accepted:
                return None
        name = str(name).strip()
        if not name:
            return None
        custom = self.custom_library.save(name, models)
        self.message.emit(f"Saved custom widget \"{custom.name}\" ({len(custom.widgets)} parts) "
                          "to the palette's Custom section")
        return custom

    def add_custom_widget(self, widget_type, x=20, y=20, parent_id=""):
        """Insert a copy of a custom widget, as one undoable step."""
        model = self.custom_library.instantiate(widget_type, self.project, x, y)
        if model is None:
            self.message.emit("That custom widget is no longer in the library")
            return
        custom = self.custom_library.get(widget_type)
        siblings = self.siblings_of(parent_id)
        def redo(): siblings.append(model) if model not in siblings else None; self._load_page(select=[model.id])
        def undo(): siblings.remove(model) if model in siblings else None; self._load_page()
        self.undo_stack.push(CallbackCommand(f"Add {custom.name}", redo, undo))

    def add_widget(self, widget_type, x=20, y=20, parent_id=""):
        from designer.palette.custom_widgets import is_custom
        if is_custom(widget_type):
            return self.add_custom_widget(widget_type, x, y, parent_id)
        definition = self.registry.get(widget_type)
        if not definition: return
        model = DesignerWidget(widget_type, self.project.unique_id(widget_type[2:].lower() if widget_type.startswith("Sh") else widget_type.lower()),
            {"x": max(0, x), "y": max(0, y), "width": definition.default_width, "height": definition.default_height}, copy.deepcopy(definition.defaults))
        siblings = self.siblings_of(parent_id)
        def redo(): siblings.append(model) if model not in siblings else None; self._load_page(select=[model.id])
        def undo(): siblings.remove(model) if model in siblings else None; self._load_page()
        self.undo_stack.push(CallbackCommand(f"Add {definition.display_name}", redo, undo))

    def delete_selected(self):
        models = self.scene.selected_models()
        if not models: return
        positions = []
        for model in models:
            siblings = self.siblings_of(self.parent_id_of(model))
            if model in siblings: positions.append((siblings, siblings.index(model), model))
        if not positions: return
        def redo():
            for siblings, _, model in positions:
                if model in siblings: siblings.remove(model)
            self._load_page()
        def undo():
            for siblings, index, model in positions: siblings.insert(min(index, len(siblings)), model)
            self._load_page(select=[m.id for _, _, m in positions])
        self.undo_stack.push(CallbackCommand("Delete widgets", redo, undo))

    def copy(self):
        # Remember the container too, so a duplicated child stays in its container.
        self.clipboard = [(self.parent_id_of(model), copy.deepcopy(model))
                          for model in self.scene.selected_models()]
    def cut(self): self.copy(); self.delete_selected()
    def paste(self):
        if not self.clipboard: return
        # One undo step for the whole clipboard, however many widgets it holds.
        self.undo_stack.beginMacro("Paste widgets" if len(self.clipboard) > 1 else "Paste widget")
        try: self._paste_each()
        finally: self.undo_stack.endMacro()
    def _paste_each(self):
        for parent_id, source in self.clipboard:
            model = copy.deepcopy(source); model.id = self.project.unique_id(source.id); model.geometry["x"] += 10; model.geometry["y"] += 10
            for child in model.walk():
                if child is not model: child.id = self.project.unique_id(child.id)
            siblings = self.siblings_of(parent_id)
            def redo(m=model, s=siblings): s.append(m) if m not in s else None; self._load_page(select=[m.id])
            def undo(m=model, s=siblings): s.remove(m) if m in s else None; self._load_page()
            self.undo_stack.push(CallbackCommand("Paste widget", redo, undo))
    def duplicate(self): self.copy(); self.paste()

    def _reparent_requested(self, widget_id, parent_id, x, y):
        """Move a widget into (or out of) a container, undoably.

        Args:
            widget_id: the widget that was dragged.
            parent_id: the container it was dropped on, or "" for the page.
            x, y: its new position in the new parent's coordinates.
        """
        model = self._find(widget_id)
        if model is None or model.locked:
            return
        previous_id = self.parent_id_of(model)
        if previous_id == parent_id:
            return
        # A container cannot be dropped into its own subtree; the canvas
        # filters this out, but the object tree will reach here too.
        if any(child is self._find(parent_id) for child in model.walk()):
            return
        source = self.siblings_of(previous_id)
        target = self.siblings_of(parent_id)
        before = dict(model.geometry)
        after = dict(model.geometry)
        after["x"], after["y"] = max(0, x), max(0, y)
        label = self.registry.get(model.type).display_name

        def redo():
            if model in source: source.remove(model)
            if model not in target: target.append(model)
            model.geometry.update(after)
            self._load_page(select=[widget_id])

        def undo():
            if model in target: target.remove(model)
            if model not in source: source.append(model)
            model.geometry.update(before)
            self._load_page(select=[widget_id])

        self.undo_stack.push(CallbackCommand(f"Reparent {label}", redo, undo))

    def _geometry_command(self, widget_id, before, after):
        model = self._find(widget_id)
        if not model: return
        def apply(value): model.geometry.update(value); self._load_page(select=[model.id])
        self.undo_stack.push(CallbackCommand("Move/resize widget", lambda: apply(after), lambda: apply(before)))

    def _single_geometry_command(self, name, value):
        selected = self.scene.selected_models()
        if not selected: return
        model = selected[0]; before = model.geometry[name]
        if before == value: return
        def apply(v): model.geometry[name] = v; self._load_page(select=[model.id])
        self.undo_stack.push(CallbackCommand(f"Change {name}", lambda: apply(value), lambda: apply(before)))

    def _property_command(self, name, value):
        selected = self.scene.selected_models()
        if not selected: return
        model = selected[0]
        value = clamp_property(name, value, model.type)
        if name == "id":
            value = value.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) or (self._find(value) and value != model.id):
                QMessageBox.warning(self, "Invalid ID", "IDs must be unique QML identifiers."); self._selection_changed([model.id]); return
            before = model.id
            def apply(v): model.id = v; self._load_page(select=[v])
        elif name == "locked":
            before = model.locked
            def apply(v): model.locked = v; self._load_page(select=[model.id])
        else:
            before = model.properties.get(name)
            def apply(v): model.properties[name] = v; self._load_page(select=[model.id])
        if before != value: self.undo_stack.push(CallbackCommand(f"Change {name}", lambda: apply(value), lambda: apply(before)))

    def _binding_command(self, prop, value):
        selected = self.scene.selected_models()
        if not selected: return
        model = selected[0]; before = copy.deepcopy(model.bindings.get(prop))
        def apply(v):
            if v is None: model.bindings.pop(prop, None)
            else: model.bindings[prop] = copy.deepcopy(v)
            self._load_page(select=[model.id])
        self.undo_stack.push(CallbackCommand("Change tag binding", lambda: apply(value), lambda: apply(before)))
        self.bindings.set_tags(self.bindings.tags + ([value.tag] if value else []))

    def _action_command(self, signal, value):
        selected = self.scene.selected_models()
        if not selected: return
        model = selected[0]; before = copy.deepcopy(model.actions.get(signal))
        def apply(v):
            if v is None: model.actions.pop(signal, None)
            else: model.actions[signal] = copy.deepcopy(v)
            self._load_page(select=[model.id])
        self.undo_stack.push(CallbackCommand("Change action", lambda: apply(value), lambda: apply(before)))
        if value is not None and value.tag:
            self.bindings.set_tags(self.bindings.tags + [value.tag]); self.actions.set_tags(self.bindings.tags)

    def _load_page(self, select=None):
        # The items a running build-up holds are about to be replaced. The
        # same page coming back (Preview reopens the file it just saved)
        # carries on building; any other page (an undo) shows at once.
        resume = None
        if getattr(self, "_reveal_queue", None):
            resume = (self._reveal_ids, self._revealed)
            self._reveal_queue = []
            self._finish_reveal()
        self._load_page_now(select)
        if resume is not None and self._page_ids() == resume[0]:
            self.reveal_page(skip=resume[1])

    def _load_page_now(self, select=None):
        self.current_page_index = min(self.current_page_index, len(self.project.pages)-1)
        self.pages.blockSignals(True); self.pages.clear(); self.pages.addItems([p.name for p in self.project.pages]); self.pages.setCurrentIndex(self.current_page_index); self.pages.blockSignals(False)
        self.actions.set_pages(self.project.pages)
        self._sync_preview_background()
        self.scene.load_page(self.project, self.current_page); self._refresh_tree()
        # Loading a page clears the selection without emitting a selection
        # change, so the alignment buttons would stay enabled over an empty
        # canvas -- offering an edit that silently does nothing.
        self.align_button.setEnabled(False)
        self._sync_text_alignment()
        if self.view.isVisible():
            self.view.fit_canvas()
        self.screen_width.blockSignals(True); self.screen_height.blockSignals(True)
        self.screen_width.setValue(self.project.screen.width); self.screen_height.setValue(self.project.screen.height)
        self.screen_width.blockSignals(False); self.screen_height.blockSignals(False)
        self.screen_theme.blockSignals(True)
        self.screen_theme.setCurrentText(self.project.screen.theme)
        self.screen_theme.blockSignals(False)
        self.project_name.blockSignals(True)
        self.project_name.setText(self.project.name)
        self.project_name.blockSignals(False)
        for widget_id in select or []:
            item = self.scene.item_for_id(widget_id)
            if item: item.setSelected(True)
        self.pageChanged.emit(self.current_page_index)

    def _refresh_tree(self):
        """Layers: each widget by the name a designer uses for it, the tag it
        shows in the second column, the QML id in the tooltip. Cards stay
        expanded; renaming the id is the Properties panel's job."""
        self.tree.blockSignals(True); self.tree.clear(); root = QTreeWidgetItem([self.current_page.name, ""]); root.setData(0, Qt.UserRole, "")
        self.tree.addTopLevelItem(root)
        muted = QColor(color("mutedForeground", getattr(self, "theme", "dark")))
        from designer.layout.compiler import CHROME_MARK

        def add(parent, model):
            # The compiler's own furniture -- a card's heading, a lamp's words,
            # the header rule -- is part of its card or lamp, not a layer.
            if model.properties.get(CHROME_MARK) and not model.children and model.id != "screenTitle":
                return
            tag = next((b.tag for b in model.bindings.values() if getattr(b, "tag", "") and b.tag != "*"), "")
            item = QTreeWidgetItem([self._display_name(model), tag]); item.setData(0, Qt.UserRole, model.id)
            item.setToolTip(0, f"{model.id} · {model.type}" + (f" · bound to {tag}" if tag else ""))
            item.setForeground(1, muted)
            parent.addChild(item)
            for child in model.children: add(item, child)
            item.setExpanded(bool(model.children))
        for model in self.current_page.widgets: add(root, model)
        root.setExpanded(True); self.tree.blockSignals(False)

    def _selection_changed(self, ids):
        model = self._find(ids[0]) if len(ids) == 1 else None
        parent = self._find(self.parent_id_of(model)) if model else None
        self.properties.set_widget(model, positioned=bool(parent and parent.type in POSITIONERS))
        self.bindings.set_widget(model); self.actions.set_widget(model)
        self.selection_chip.setText(f"{model.type} · {model.id}" if model else (f"{len(ids)} selected" if ids else "Select a widget on the canvas or in Layers"))
        self.selection_title.setText(self._display_name(model) if model else (f"{len(ids)} widgets" if ids else "Nothing selected"))
        self._sync_size_row(self.scene.selected_models())
        self.composer_scope.setText(self._display_name(model) if model else (f"{len(ids)} widgets" if ids else "Whole page"))
        self.align_button.setEnabled(len(self._arrangeable_selection()) >= 2)
        self._sync_text_alignment()
        self.tree.blockSignals(True); self.tree.clearSelection()
        if ids:
            row = self._tree_item_for(ids[0])
            if row is not None: row.setSelected(True)
        self.tree.blockSignals(False)

    def _tree_selection(self):
        selected = self.tree.selectedItems(); widget_id = selected[0].data(0, Qt.UserRole) if selected else ""
        self.scene.clearSelection(); item = self.scene.item_for_id(widget_id)
        if item: item.setSelected(True)
    def _tree_renamed(self, item, column):
        old = item.data(0, Qt.UserRole); new = item.text(0)
        if old and old != new:
            model = self._find(old)
            if model: self.scene.clearSelection(); canvas_item = self.scene.item_for_id(old); canvas_item.setSelected(True); self._property_command("id", new)
    def _find(self, widget_id): return next((w for w in self.project.all_widgets() if w.id == widget_id), None)

    # Switching pages is navigation, not an edit: it stays off the undo stack
    # and announces itself. Page edits and nudges are commands, so undo can
    # never replay a geometry or page list the model no longer has.
    def change_page(self, index):
        if index >= 0: self.current_page_index = index; self._load_page(); self.designChanged.emit()
    def _push_page_insert(self, text, page):
        previous = self.current_page_index
        def redo():
            self.project.pages.append(page); self.current_page_index = len(self.project.pages)-1; self._load_page()
        def undo():
            if page in self.project.pages: self.project.pages.remove(page)
            self.current_page_index = previous; self._load_page()
        self.undo_stack.push(CallbackCommand(text, redo, undo))
    def new_page(self):
        number = len(self.project.pages)+1
        self._push_page_insert("New page", DesignerPage(self.project.unique_id(f"page{number}"), f"Page {number}"))
    def duplicate_page(self):
        source = self.current_page; number = len(self.project.pages) + 1
        page = copy.deepcopy(source); page.id = self.project.unique_id(f"page{number}"); page.name = f"{source.name} Copy"
        for widget in page.walk(): widget.id = self.project.unique_id(widget.id)
        self._push_page_insert("Duplicate page", page)
    def delete_page(self):
        if len(self.project.pages) == 1:
            QMessageBox.information(self, "Page required", "A design must contain at least one page."); return
        index = self.current_page_index; page = self.project.pages[index]
        def redo():
            self.project.pages.remove(page); self.current_page_index = min(index, len(self.project.pages)-1); self._load_page()
        def undo():
            self.project.pages.insert(index, page); self.current_page_index = index; self._load_page()
        self.undo_stack.push(CallbackCommand("Delete page", redo, undo))
    def edit_screen_idle(self, _checked=False, *, dialog_exec=None):
        """CONTRACT 13.5: dim / off after inactivity, one undo step.
        `dialog_exec` replaces QDialog.exec in tests (returns the result code)."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout
        dialog = QDialog(self); dialog.setWindowTitle("Screen idle")
        editor = ScreenIdleEditor(dialog); editor.load(dict(self.project.screen.idle))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog); layout.addWidget(editor); layout.addWidget(buttons)
        result = (dialog_exec or (lambda d: d.exec()))(dialog)
        if result != QDialog.DialogCode.Accepted:
            return False
        before, after = dict(self.project.screen.idle), editor.value()
        if before == after:
            return False
        def set_idle(value):
            self.project.screen.idle = dict(value)
        self.undo_stack.push(CallbackCommand("Screen idle", lambda: set_idle(after), lambda: set_idle(before)))
        return True
    def select_all(self):
        for item in self.scene.items():
            if hasattr(item, "widget_model"): item.setSelected(True)
    def nudge(self, dx, dy):
        models = self.scene.selected_models()
        if models: self.undo_stack.push(NudgeCommand(self, models, dx, dy))
    def _screen_changed(self):
        if not hasattr(self, "scene"): return
        self.project.screen.width = self.screen_width.value(); self.project.screen.height = self.screen_height.value()
        self.project.screen.theme = self.screen_theme.currentText()
        self.scene.update_screen_rect(); self.scene.update()

    def apply_target_resolution(self, width, height):
        """Match the canvas to the display the Studio is connected to.

        A design is drawn for one piece of glass. When the Studio learns the
        connected SOM's real geometry, the canvas has to follow, or the author
        places widgets against a screen that does not exist and only finds out
        after a deploy. Widget coordinates are left alone: this moves the
        design surface, not the contents.

        Args:
            width: panel width in pixels, > 0.
            height: panel height in pixels, > 0.

        Returns:
            True when the canvas changed, False when the call was a no-op.
        """
        if width <= 0 or height <= 0:
            return False
        # Remembered even when the canvas already matches, and before the
        # no-op return: the Studio probes the display once, on Connect, so by
        # the time a design is opened there is nothing left to send it again.
        self.target_resolution = (width, height)
        if (self.project.screen.width, self.project.screen.height) == (width, height):
            return False
        self.project.screen.width = width
        self.project.screen.height = height
        self.screen_width.blockSignals(True); self.screen_height.blockSignals(True)
        self.screen_width.setValue(width); self.screen_height.setValue(height)
        self.screen_width.blockSignals(False); self.screen_height.blockSignals(False)
        if hasattr(self, "scene"):
            self.scene.update_screen_rect(); self.scene.update()
        if self.view.isVisible():
            self.view.fit_canvas()
        self.message.emit(
            f"Designer canvas set to the connected display: {width} x {height} px")
        return True

    def _retarget_to_connected_display(self):
        """Re-apply the connected panel's geometry after a project is loaded.

        A saved design carries the screen it was drawn for, and loading one
        overwrites the canvas with it. While the Studio is connected that put
        the author back on a screen that is not plugged in -- exactly the
        mismatch apply_target_resolution exists to prevent, and harder to
        notice, because the canvas had been right until the file was opened.

        The connected display wins. Widget coordinates are untouched, so a
        design drawn for a smaller panel keeps its layout and simply gains
        room; nothing is moved or rescaled behind the author's back.
        """
        if self.target_resolution:
            self.apply_target_resolution(*self.target_resolution)

    def _project_name_edited(self):
        name = self.project_name.text().strip()
        # editingFinished also fires when the field merely loses focus (another
        # window opening, say); an untouched empty name on an unnamed design is
        # not an edit and must not raise the warning.
        if not name and not self.project.name:
            return
        if NAME_RE.fullmatch(name):
            self.project.name = name
            self.project_name.setText(name)
            return
        QMessageBox.warning(
            self, "Invalid project name",
            "Use 1-64 lowercase letters, numbers, dots, underscores, or hyphens."
        )
        self.project_name.setText(self.project.name)
    def set_text_alignment(self, value):
        """Set horizontalAlignment on every selected widget that has one.

        Routed through the same command the inspector uses, so a toolbar click
        and a combo box change produce one undo entry of the same shape rather
        than two paths that can drift.
        """
        targets = [model for model in self.scene.selected_models()
                   if (definition := self.registry.get(model.type))
                   and "horizontalAlignment" in definition.properties]
        value = clamp_property("horizontalAlignment", value)
        befores = [model.properties.get("horizontalAlignment") for model in targets]
        if any(before != value for before in befores):
            ids = [model.id for model in targets]
            def apply(values):
                for model, v in zip(targets, values): model.properties["horizontalAlignment"] = v
                self._load_page(select=ids)
            self.undo_stack.push(CallbackCommand(
                "Change horizontalAlignment",
                lambda: apply([value] * len(targets)), lambda: apply(befores)))
        self._sync_text_alignment()

    def _sync_text_alignment(self):
        """Check the button matching the selection, and disable all three
        when nothing selected can carry an alignment."""
        models = self.scene.selected_models()
        applicable = [
            model for model in models
            if (self.registry.get(model.type)
                and "horizontalAlignment" in self.registry.get(model.type).properties)
        ]
        current = ""
        if applicable:
            current = applicable[0].properties.get("horizontalAlignment", "Text.AlignLeft")
        for value, item in self._text_align_actions.items():
            item.setEnabled(bool(applicable))
            item.setChecked(bool(applicable) and value == current)

    def _arrangeable_selection(self):
        """Selected free siblings that can safely share an arrangement.

        Coordinates are relative to the parent, and Qt Quick positioners own
        their children's x/y.  Treating a mixed tree selection as one flat
        canvas would silently write invalid geometry, so the arrange controls
        intentionally stay scoped to free siblings.
        """
        models = self.scene.selected_models()
        if len(models) < 2 or any(model.locked for model in models):
            return []
        parents = {self.parent_id_of(model) for model in models}
        if len(parents) != 1:
            return []
        parent_id = next(iter(parents))
        parent = self._find(parent_id) if parent_id else None
        return [] if parent is not None and parent.type in POSITIONERS else models

    def align(self, mode):
        """Align, size-match or distribute the selection, undoably.

        Every other edit goes on the undo stack. These did not: they rewrote
        the geometry dicts in place, so Ctrl+Z after an align undid whatever
        came *before* it and left the align standing -- the stack and the
        model drifting apart with no way back.
        """
        models = self._arrangeable_selection()
        if len(models) < 2: return
        before = [dict(model.geometry) for model in models]
        g = arrange_selection(before, mode)
        if g == before:
            return
        after = [dict(item) for item in g]
        ids = [m.id for m in models]

        def redo():
            for model, geometry in zip(models, after): model.geometry.update(geometry)
            self._load_page(select=ids)

        def undo():
            for model, geometry in zip(models, before): model.geometry.update(geometry)
            self._load_page(select=ids)

        self.undo_stack.push(CallbackCommand(f"Align {mode}", redo, undo))

    def tidy_up(self):
        """Compose the current page: the layout pipeline, one undo step.

        The same pass the AI tab runs on a generated section -- an archetype,
        the grid, the type's own proportions and the style pass -- applied to
        whatever is on the canvas now. One CallbackCommand, so Ctrl+Z puts the
        page back exactly as it was drawn.
        """
        page = self.current_page
        if not page.widgets:
            self.message.emit("Nothing to tidy up on this page")
            return
        before = copy.deepcopy(page.widgets)
        try:
            from designer.layout.compiler import compile_page, is_planned
            if is_planned(page):
                # A page the layout compiler built is compiled again, which
                # keeps its cards; polish would take them apart.
                compiled = compile_page(self.project, page, self.registry)
                report = None
            else:
                from designer.layout.polish import polish
                report = polish(self.project, page, self.registry, brief=self.project.name)
        except Exception as exc:
            # Never leave half a composition on the canvas.
            page.widgets[:] = before
            self._load_page()
            self.message.emit(f"Could not tidy up: {exc}")
            return
        after = copy.deepcopy(page.widgets)
        if [w.to_dict() for w in after] == [w.to_dict() for w in before]:
            self.message.emit("Already composed: nothing to tidy up")
            return

        def apply(widgets):
            page.widgets[:] = copy.deepcopy(widgets)
            self._load_page()
            self.designChanged.emit()

        self.undo_stack.push(CallbackCommand("Tidy up", lambda: apply(after), lambda: apply(before)))
        if report is None:
            self.message.emit(f"Tidy up: compiled {compiled.layout}")
        else:
            self.message.emit(f"Tidy up: {report.archetype or 'composed'}, "
                              f"{report.before.score:.0f} → {report.after.score:.0f}")

    def z_order(self, mode):
        """Raise or lower the selection, undoably."""
        models = self.scene.selected_models()
        if not models: return
        values = [widget.z for widget in self.current_page.walk()]
        target = (max(values or [0]) + 1) if mode == "front" else (min(values or [0]) - 1)
        before = [model.z for model in models]
        if all(z == target for z in before):
            return
        ids = [m.id for m in models]

        def redo():
            for model in models: model.z = target
            self._load_page(select=ids)

        def undo():
            for model, z in zip(models, before): model.z = z
            self._load_page(select=ids)

        self.undo_stack.push(CallbackCommand(
            "Bring to front" if mode == "front" else "Send to back", redo, undo))
    def toggle_grid(self, checked): self.scene.grid_visible = checked; self.scene.update()
    def toggle_live_previews(self, checked):
        if self.scene.qml_previews is not None:
            self.scene.qml_previews.enabled = checked
        self.scene.update()
    def toggle_snap(self, checked): self.scene.snap_enabled = checked
    def toggle_object_snap(self, checked):
        self.scene.object_snap_enabled = checked
        self.scene.clear_snap_guides()
    def view_fit(self): self.view.fit_canvas()

    def _update_manifest(self, entry):
        path = os.path.join(self.bundle_dir, "manifest.json")
        manifest = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle: manifest = json.load(handle)
        project_name = self.project.name or self._bundle_project_name(manifest)
        self.project.name = project_name
        manifest.update({"schema": 1, "name": project_name, "version": manifest.get("version", "1.0.0"),
                         # The panel runs the design file itself (hmi-ui); the QML
                         # generated beside it is for this desktop's preview only.
                         "entry": "project.edsui", "runtime": "edsui",
                         "preview": entry.replace(os.sep, "/"),
                         "screen": {"width": self.project.screen.width, "height": self.project.screen.height},
                         "theme": self.project.screen.theme,
                         "tags_required": self.project.required_tags()})
        # Binding thresholds become the panel's alarm list (CONTRACT 4). None
        # left -> no key, so a design without thresholds validates as before.
        alarms = self.project.alarms()
        if alarms: manifest["alarms"] = alarms
        else: manifest.pop("alarms", None)
        with open(path, "w", encoding="utf-8", newline="\n") as handle: json.dump(manifest, handle, indent=2); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())

    def _bundle_project_name(self, manifest=None):
        """Return the deployable name for this designer project."""
        manifest_name = str((manifest or {}).get("name", "")).strip()
        if manifest_name:
            return manifest_name
        folder_name = os.path.basename(os.path.normpath(self.bundle_dir)) if self.bundle_dir else ""
        return folder_name or "designed-ui"

    def default_projects_root(self):
        """Folder that receives auto-provisioned design bundles."""
        if self.projects_root:
            return self.projects_root
        documents = (QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
                     or os.path.expanduser("~"))
        return os.path.join(documents, "EmbeddedDisplay Studio", "projects")

    def ensure_bundle(self):
        """Give the design a bundle on disk if it has none yet.

        The AI Design tab drops a project straight onto the canvas; the
        Studio may have no bundle open at all. Rather than refuse Preview
        with "open a bundle first", provision one under the projects root
        named after the design, so the same generate -> manifest -> preview
        -> deploy chain runs unchanged. Returns True once a bundle exists.
        """
        if self.bundle_dir:
            return True
        name = deployable_name(self.project.name)
        root = self.default_projects_root()
        bundle = os.path.join(root, name)
        # A folder that already holds another design must not be overwritten.
        counter = 2
        while os.path.isdir(bundle) and os.listdir(bundle):
            bundle = os.path.join(root, f"{name}-{counter}"); counter += 1
        try:
            os.makedirs(bundle, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Could not create project",
                                 f"Could not create a project folder at:\n{bundle}\n\n{exc}")
            return False
        self.project.name = name
        self.project_name.setText(name)
        self.bundle_dir = os.path.abspath(bundle)
        self.scene.project_dir = self.bundle_dir
        self.file_path = os.path.join(self.bundle_dir, "project.edsui")
        self.message.emit(f"Created project bundle at {self.bundle_dir}")
        return True

    def generate(self):
        if not self.ensure_bundle(): return []
        if not self.save(): return []
        try:
            output_dir = os.path.join(self.bundle_dir, "generated")
            paths = self.generator.write(self.project, output_dir, self.bundle_dir)
            entry = os.path.relpath(paths[0], self.bundle_dir); self._update_manifest(entry)
            self.bindings.set_tags(self.project.required_tags()); self.actions.set_tags(self.bindings.tags)
            self.message.emit(f"Generated {len(paths)} QML page(s) in {output_dir}"); return paths
        except (OSError, QmlGenerationError, ValueError) as exc:
            QMessageBox.critical(self, "Generation failed", str(exc)); return []
    # -- Code window --
    def host_code_window(self, window, activate):
        """The Studio embeds the Code window as a tab beside the Designer:
        `window` is that instance and `activate` switches to the tab.
        open_code_window then activates it instead of showing a window."""
        self._code_window = window
        self._code_activate = activate
        window.apply_theme(getattr(self, "theme", "dark"))

    def open_code_window(self):
        """Shows the Code window (designer/ui/code_window.py), creating the
        single instance on first use and raising it after; returns it. The
        window follows this workspace's selection, design changes and theme.
        When the Studio hosts it as a tab (host_code_window), that tab is
        selected instead."""
        if self._code_activate is not None and self._code_window is not None:
            self._code_window.apply_theme(getattr(self, "theme", "dark"))
            self._code_activate()
            return self._code_window
        if self._code_window is None:
            # Imported here, not at the top: the window pulls in the code
            # model and editor, which the Designer never needs until asked.
            from designer.ui.code_window import CodeWindow
            self._code_window = CodeWindow(self)
        window = self._code_window
        # The Studio themes the workspace before showing it; a window opened
        # later has to catch up on its own, and before the first paint.
        window.apply_theme(getattr(self, "theme", "dark"))
        window.show(); window.raise_(); window.activateWindow()
        return window

    def selected_widget(self):
        """The one selected widget model, or None (multi/none selected)."""
        models = self.scene.selected_models()
        return models[0] if len(models) == 1 else None

    def select_widget(self, widget_id):
        """Makes the widget with this id the only selection on the canvas and
        scrolls the view to it (the Code section's widget picker); False when
        the current page has no such widget."""
        item = self.scene.item_for_id(widget_id)
        if item is None:
            return False
        self.scene.clearSelection()
        item.setSelected(True)
        for view in self.scene.views():
            view.ensureVisible(item)
        return True

    def _slot_of(self, widget_id):
        """The list on the current page holding this widget, and its index
        there; (None, -1) when the page has no such widget.

        parent_id_of/siblings_of answer for containers the registry knows;
        this walks every child list so the swap lands in the list the widget
        is actually in, whatever its parent's definition says.
        """
        for siblings in [self.current_page.widgets] + [w.children for w in self.current_page.walk()]:
            for index, model in enumerate(siblings):
                if model.id == widget_id:
                    return siblings, index
        return None, -1

    def replace_widget(self, widget_id, new_widget):
        """Swaps the widget with id `widget_id` (anywhere on the current
        page) for `new_widget` (a DesignerWidget, children included) as one
        undoable command titled 'Edit <id> code'; reloads the canvas, keeps
        the new widget selected, emits designChanged. Returns False (and
        does nothing) when no such widget is on the current page."""
        siblings, index = self._slot_of(widget_id)
        if siblings is None:
            return False
        outgoing = siblings[index]
        # The caller (the Code window) may keep editing its object; the
        # command owns its own copy, like every other snapshot on the stack.
        incoming = copy.deepcopy(new_widget)

        def swap(old, new):
            # Located by identity: after the swap `old` and `new` can compare
            # equal, and the stack's ordering keeps the slot stable anyway.
            position = next((i for i, m in enumerate(siblings) if m is old), None)
            if position is None:
                siblings.insert(min(index, len(siblings)), new)
            else:
                siblings[position] = new
            self._load_page(select=[new.id])
            self.designChanged.emit()

        self.undo_stack.push(CallbackCommand(
            f"Edit {widget_id} code", lambda: swap(outgoing, incoming), lambda: swap(incoming, outgoing)))
        return True

    def replace_page(self, index, new_page):
        """Swaps `project.pages[index]` for `new_page` (a DesignerPage) as one
        undoable command titled 'Edit page code'; reloads the canvas when it
        is the current page, emits designChanged. False when index is out
        of range."""
        pages = self.project.pages
        if not 0 <= index < len(pages):
            return False
        outgoing, incoming = pages[index], copy.deepcopy(new_page)

        def swap(page):
            pages[index] = page
            if index == self.current_page_index:
                self._load_page()
            else:
                # Only _load_page rebuilds the page combo; a page edited
                # off-screen still has to show its (possibly new) name.
                self.pages.setItemText(index, page.name)
                self.actions.set_pages(pages)
            self.designChanged.emit()

        self.undo_stack.push(CallbackCommand(
            "Edit page code", lambda: swap(incoming), lambda: swap(outgoing)))
        return True

    def preview(self):
        """Generate and ask the Studio to reload; False when nothing was generated."""
        if not self.generate(): return False
        self.previewRequested.emit(self.bundle_dir); return True
    def deploy(self):
        if self.isVisible():
            name, accepted = QInputDialog.getText(
                self, "Deploy design", "Project name used for deployment:",
                QLineEdit.Normal, self.project.name or self._bundle_project_name())
            if not accepted:
                return
            name = name.strip()
            if not NAME_RE.fullmatch(name):
                QMessageBox.warning(
                    self, "Invalid project name",
                    "Use 1-64 lowercase letters, numbers, dots, underscores, or hyphens."
                )
                return
            self.project.name = name
            self.project_name.setText(name)
        if self.generate(): self.deployRequested.emit(self.bundle_dir)

    def choose_image_asset(self, source_path):
        if not self.bundle_dir: raise ValueError("open a bundle before adding assets")
        assets = os.path.join(self.bundle_dir, "assets"); os.makedirs(assets, exist_ok=True)
        destination = os.path.join(assets, os.path.basename(source_path))
        if os.path.abspath(source_path) != os.path.abspath(destination): shutil.copy2(source_path, destination)
        return os.path.relpath(destination, self.bundle_dir).replace(os.sep, "/")

    _PROMPT_IMAGE_RE = re.compile(
        r'"([^"]+\.(?:png|jpe?g|bmp|gif|webp|svg))"'
        r"|'([^']+\.(?:png|jpe?g|bmp|gif|webp|svg))'"
        r"|((?:[A-Za-z]:[\\/]|/)[^\s\"']+?\.(?:png|jpe?g|bmp|gif|webp|svg))(?![\w.])"
        r"|(?<![\w\\/.])(~?[\w.-]*(?:[\\/][\w.-]+)*\.(?:png|jpe?g|bmp|gif|webp|svg))(?![\w.])", re.I)

    def _resolve_prompt_image(self, path: str) -> str:
        """An image a person named: absolute, or relative to the project or
        to their home, Downloads, Desktop or Pictures folder. "" if none."""
        path = os.path.expanduser(path)
        if os.path.isabs(path):
            return path if os.path.isfile(path) else ""
        home = os.path.expanduser("~")
        for root in (self.bundle_dir, home, *(os.path.join(home, d) for d in ("Downloads", "Desktop", "Pictures"))):
            if root and os.path.isfile(os.path.join(root, path)):
                return os.path.join(root, path)
        return ""

    def drop_image_file(self, path, x, y, animate=True):
        """Copy a dropped image file into the bundle and place an Image on it.

        Only picture files the panel can decode land: png, jpg, jpeg, bmp, gif,
        webp and svg, else None. The file is copied into <bundle>/assets as a
        PNG, named from the file in the same way import_prompt_images names
        one (lowercase, spaces -> _), capped at 240x120, and an Image with
        PreserveAspectFit is placed at (x, y) as one undo step.

        A .gif is the exception: it is copied as it is (still a GIF, every
        frame kept) and lands as an ShAnimatedImage that plays it, 240x160.
        ``animate=False`` (a brand logo) keeps the old way: a still PNG Image.
        """
        stem = os.path.basename(path)
        if not (stem.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".svg"))):
            return None
        resolved = self._resolve_prompt_image(path)
        if not resolved:
            return None
        if not self.ensure_bundle():
            return None
        assets = os.path.join(self.bundle_dir, "assets"); os.makedirs(assets, exist_ok=True)
        stem = re.sub(r"\.(?:png|jpe?g|bmp|gif|webp|svg)$", "", os.path.basename(resolved).lower(),
                      flags=re.I)
        animated = animate and resolved.lower().endswith(".gif")
        name = re.sub(r"[^a-z0-9._]+", "_", stem) + (".gif" if animated else ".png")
        destination = os.path.join(assets, name)
        if animated:
            if os.path.abspath(resolved) != os.path.abspath(destination):
                shutil.copy2(resolved, destination)
        elif not _trim_transparent_margins(resolved, destination):
            if resolved.lower().endswith(".png"):
                shutil.copy2(resolved, destination)
            else:
                from PySide6.QtGui import QImage
                if not QImage(resolved).save(destination, "PNG"):
                    return None
        widget_type = "ShAnimatedImage" if animated else "Image"
        definition = self.registry.get(widget_type)
        cap_w, cap_h = (240, 160) if animated else (240, 120)
        model = DesignerWidget(widget_type, self.project.unique_id("animation" if animated else "image"),
            {"x": max(0, int(x)), "y": max(0, int(y)),
             "width": min(definition.default_width, cap_w),
             "height": min(definition.default_height, cap_h)},
            copy.deepcopy(definition.defaults))
        model.properties["source"] = os.path.relpath(destination, self.bundle_dir).replace(os.sep, "/")
        siblings = self.siblings_of("")
        def redo(): siblings.append(model) if model not in siblings else None; self._load_page(select=[model.id])
        def undo(): siblings.remove(model) if model in siblings else None; self._load_page()
        self.undo_stack.push(CallbackCommand("Add image", redo, undo))
        return model

    def import_prompt_images(self, prompt: str):
        """Copy the image files a request names into the project's assets.

        "Add C:\\Downloads\\Acme.png to the header" is how a person asks for a
        logo; the AI and the panel can only use it as "assets/acme.png". Each
        existing file is copied in (transparent margins trimmed, so a logo
        padded onto a square canvas is not drawn at a fraction of its box) and
        the request names the asset instead. Returns (prompt, [asset paths]).
        """
        imported = []

        def replace(match):
            named = next(group for group in match.groups() if group)
            if named.replace("\\", "/").startswith("assets/"):
                return match.group(0)            # already the project's own
            path = self._resolve_prompt_image(named)
            if not path or not self.ensure_bundle():
                return match.group(0)
            assets = os.path.join(self.bundle_dir, "assets"); os.makedirs(assets, exist_ok=True)
            # The panel's runtime decodes PNG only: every other format is
            # converted on the way in ("Logo.svg.webp" -> "logo.png").
            stem = re.sub(r"(\.(?:png|jpe?g|bmp|gif|webp|svg))+$", "", os.path.basename(path).lower())
            name = re.sub(r"[^a-z0-9._-]+", "-", stem) + ".png"
            destination = os.path.join(assets, name)
            if not _trim_transparent_margins(path, destination):
                if path.lower().endswith(".png"):
                    shutil.copy2(path, destination)
                else:
                    from PySide6.QtGui import QImage
                    if not QImage(path).save(destination, "PNG"):
                        return match.group(0)
            asset = os.path.relpath(destination, self.bundle_dir).replace(os.sep, "/")
            imported.append(asset)
            return asset

        return self._PROMPT_IMAGE_RE.sub(replace, prompt), imported

    def set_brand(self, logos=None, accent=None):
        """Import the brand's logos into the bundle and remember the accent.

        Each logo is copied like a dropped image (into <bundle>/assets as a
        PNG) and stored by its bundle-relative path. The accent is the one
        colour a generator carries to the AI prompt and the cab layout reads.
        """
        imported = []
        for logo in (logos or []):
            if self.drop_image_file(logo, 0, 0, animate=False) is not None:
                model = self.current_page.widgets[-1]
                imported.append(model.properties["source"])
        self.project.brand = {"logos": imported, "accent": accent or ""}

    def _ensure_project_location(self):
        """Assets are copied beside the project, so it needs a home on disk first."""
        return self.ensure_bundle()

    def _asset_requested(self, widget_id, property_name):
        """Double-clicking the widget itself is the shortest way to its image."""
        item = self.scene.item_for_id(widget_id)
        if item:
            self.scene.clearSelection(); item.setSelected(True)
        self._choose_property_asset(property_name)

    def _text_requested(self, widget_id, property_name):
        """Edit a widget's visible caption by double-clicking it on the canvas."""
        model = self._find(widget_id)
        if model is None:
            return
        item = self.scene.item_for_id(widget_id)
        if item:
            self.scene.clearSelection(); item.setSelected(True)
        current = str(model.properties.get(property_name, ""))
        value, accepted = QInputDialog.getMultiLineText(
            self, "Edit widget text", property_name, current)
        if accepted:
            self._property_command(property_name, value)

    def context_menu(self, widget_id):
        """The actions a widget offers on right-click, Qt Designer style."""
        menu = QMenu(self)
        model = self._find(widget_id) if widget_id else None
        definition = self.registry.get(model.type) if model else None
        if model is not None:
            # Qt opens a context menu with its top-left under the cursor, so
            # whatever is first sits directly beneath the pointer. "Clear
            # Image" was second: one twitch of the wrist between right-clicking
            # a picture and wiping it, with the file still on disk and nothing
            # on screen to say what happened. Destructive entries go to the
            # bottom, beside Delete, behind a separator.
            clearable = []
            for name in (definition.asset_properties if definition else ()):
                label = "Image" if name == "source" else name
                current = model.properties.get(name)
                menu.addAction(f"Change {label}..." if current else f"Set {label}...",
                               lambda checked=False, n=name: self._asset_requested(widget_id, n))
                if current:
                    clearable.append((name, label))
            if definition and definition.asset_properties:
                menu.addSeparator()
            menu.addAction("Cut", self.cut)
            menu.addAction("Copy", self.copy)
            menu.addAction("Duplicate", self.duplicate)
            menu.addAction("Save as custom widget...", self.save_selection_as_custom)
            menu.addSeparator()
            for name, label in clearable:
                menu.addAction(f"Clear {label}",
                               lambda checked=False, n=name: self._property_command(n, ""))
            menu.addAction("Delete", self.delete_selected)
            menu.addSeparator()
            menu.addAction("Bring to Front", lambda: self.z_order("front"))
            menu.addAction("Send to Back", lambda: self.z_order("back"))
            locked = menu.addAction("Locked")
            locked.setCheckable(True); locked.setChecked(model.locked)
            locked.toggled.connect(lambda value: self._property_command("locked", value))
            menu.addSeparator()
        paste = menu.addAction("Paste", self.paste)
        paste.setEnabled(bool(self.clipboard))
        if model is None:
            menu.addAction("Select All", self.select_all)
        return menu

    def _show_context_menu(self, widget_id, position):
        self.context_menu(widget_id).exec(position)

    def _tree_context_menu(self, position):
        item = self.tree.itemAt(position)
        widget_id = item.data(0, Qt.UserRole) if item else ""
        if widget_id:
            canvas_item = self.scene.item_for_id(widget_id)
            if canvas_item:
                self.scene.clearSelection(); canvas_item.setSelected(True)
        self._show_context_menu(widget_id, self.tree.viewport().mapToGlobal(position))

    def _choose_property_asset(self, property_name):
        if not self._ensure_project_location():
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Select image", self.bundle_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.svg);;All files (*)")
        if not source:
            return
        try:
            relative = self.choose_image_asset(source)
        except (OSError, ValueError, shutil.Error) as exc:
            QMessageBox.critical(self, "Could not add image", str(exc))
            return
        self._property_command(property_name, relative)
