"""Integrated visual designer workspace composed only from ordinary PySide6 APIs."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut, QUndoStack
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox,
    QFrame, QPlainTextEdit, QScrollArea, QSizePolicy, QSplitter, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from designer.canvas.designer_view import POSITIONERS, DesignerScene, DesignerView
from designer.commands import CallbackCommand
from designer.generators import QmlGenerationError, QmlGenerator
from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget
from designer.palette.widget_palette import WidgetPalette
from designer.palette.widget_registry import default_registry

try:
    from ui.python.shadcn import color, icon
except ImportError:
    from PySide6.QtGui import QIcon
    def icon(_name): return QIcon()
    def color(_name, theme="dark"): return "#18181b"


class PropertyEditor(QWidget):
    propertyEdited = Signal(str, object)
    geometryEdited = Signal(str, object)
    assetRequested = Signal(str)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry, self.widget_model = registry, None
        self.form = QFormLayout(self)
        self.form.setContentsMargins(6, 6, 6, 6)

    def set_widget(self, widget, positioned=False):
        self.widget_model = widget
        self.setMinimumHeight(0)
        while self.form.rowCount():
            self.form.removeRow(0)
        if widget is None:
            self.form.addRow(QLabel("Select a widget to edit its properties."))
            self._sync_form_height()
            return
        identifier = QLineEdit(widget.id)
        identifier.editingFinished.connect(lambda e=identifier: self.propertyEdited.emit("id", e.text()))
        self.form.addRow("ID", identifier)
        locked = QCheckBox()
        locked.setChecked(widget.locked)
        locked.toggled.connect(lambda value: self.propertyEdited.emit("locked", value))
        self.form.addRow("Locked", locked)
        for key in ("x", "y", "width", "height"):
            editor = QSpinBox()
            editor.setRange(-100000 if key in ("x", "y") else 1, 100000)
            editor.setValue(round(widget.geometry[key]))
            if positioned and key in ("x", "y"):
                editor.setEnabled(False)
                editor.setToolTip("The parent Row, Column or Grid places this widget.")
            else:
                editor.valueChanged.connect(lambda value, name=key: self.geometryEdited.emit(name, value))
            self.form.addRow(key.capitalize(), editor)
        definition = self.registry.get(widget.type)
        if not definition:
            self._sync_form_height()
            return
        for name, value_type in definition.properties.items():
            value = widget.properties.get(name, definition.defaults.get(name))
            editor = self._editor(definition, name, value_type, value)
            self.form.addRow(name, editor)
        self._sync_form_height()

    def _sync_form_height(self):
        """Expose dynamic rows to the containing inspector scroll area."""
        QTimer.singleShot(0, self._apply_form_height)

    def _apply_form_height(self):
        self.form.invalidate()
        self.form.activate()
        self.setMinimumHeight(self.form.sizeHint().height() + 12)

    def _editor(self, definition, name, value_type, value):
        if name in definition.choices:
            editor = QComboBox()
            editor.addItems(definition.choices[name])
            editor.setCurrentText(str(value or ""))
            editor.currentTextChanged.connect(lambda v: self.propertyEdited.emit(name, v))
        elif name in definition.color_properties:
            editor = QWidget()
            row = QHBoxLayout(editor); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
            text = QLineEdit(str(value or "")); text.setPlaceholderText("Theme default or #RRGGBB")
            choose = QPushButton("Color"); choose.setToolTip(f"Choose {name}")
            choose.setFixedHeight(36)
            text.editingFinished.connect(lambda e=text: self.propertyEdited.emit(name, e.text().strip()))
            def pick_color():
                initial = QColor(text.text()) if QColor(text.text()).isValid() else QColor("#3b82f6")
                selected = QColorDialog.getColor(initial, self, f"Choose {name}")
                if selected.isValid():
                    text.setText(selected.name(QColor.HexArgb) if selected.alpha() < 255 else selected.name())
                    self.propertyEdited.emit(name, text.text())
            choose.clicked.connect(pick_color)
            row.addWidget(text, 1); row.addWidget(choose)
        elif name in definition.asset_properties:
            editor = QWidget()
            row = QHBoxLayout(editor); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
            text = QLineEdit(str(value or "")); text.setPlaceholderText("assets/image.png")
            browse = QPushButton("Browse"); browse.setToolTip("Select and copy an image into project assets")
            browse.setFixedHeight(36)
            text.editingFinished.connect(lambda e=text: self.propertyEdited.emit(name, e.text().strip()))
            browse.clicked.connect(lambda: self.assetRequested.emit(name))
            row.addWidget(text, 1); row.addWidget(browse)
        elif value_type is bool:
            editor = QCheckBox(); editor.setChecked(bool(value))
            editor.toggled.connect(lambda v: self.propertyEdited.emit(name, v))
        elif value_type is int:
            editor = QSpinBox(); editor.setRange(-100000, 100000); editor.setValue(int(value or 0))
            editor.valueChanged.connect(lambda v: self.propertyEdited.emit(name, v))
        elif value_type is float:
            editor = QDoubleSpinBox(); editor.setRange(-1e9, 1e9); editor.setDecimals(4); editor.setValue(float(value or 0))
            editor.valueChanged.connect(lambda v: self.propertyEdited.emit(name, v))
        else:
            editor = QLineEdit(str(value or ""))
            editor.editingFinished.connect(lambda e=editor: self.propertyEdited.emit(name, e.text()))
            if name in ("color", "background"):
                editor.setPlaceholderText("#RRGGBB")
        return editor


class BindingEditor(QWidget):
    bindingEdited = Signal(str, object)

    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry, self.widget_model, self.tags = registry, None, []
        form = QFormLayout(self)
        self.property = QComboBox(); self.tag = QComboBox(); self.tag.setEditable(True)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search tags")
        self.format = QLineEdit(); self.multiplier = QDoubleSpinBox(); self.offset = QDoubleSpinBox()
        self.multiplier.setRange(-1e9, 1e9); self.multiplier.setValue(1.0)
        self.offset.setRange(-1e9, 1e9)
        self.unit = QLineEdit(); self.warning = QLineEdit(); self.critical = QLineEdit()
        for label, editor in (("Property", self.property), ("Search", self.search), ("Tag", self.tag),
                              ("Format", self.format), ("Multiplier", self.multiplier), ("Offset", self.offset),
                              ("Unit", self.unit), ("Warning", self.warning), ("Critical", self.critical)):
            form.addRow(label, editor)
        actions = QHBoxLayout(); bind = QPushButton("Apply binding"); remove = QPushButton("Remove")
        actions.addWidget(bind); actions.addWidget(remove); form.addRow(actions)
        self.search.textChanged.connect(self._filter)
        self.property.currentTextChanged.connect(self._load_binding)
        bind.clicked.connect(self._apply); remove.clicked.connect(self._remove)

    def set_tags(self, tags):
        self.tags = sorted(set(tags or [])); self._filter(self.search.text())

    def set_widget(self, widget):
        self.widget_model = widget; self.property.clear()
        definition = self.registry.get(widget.type) if widget else None
        if definition:
            self.property.addItems(definition.bindable_properties)
        self.setEnabled(bool(definition and definition.bindable_properties))

    def _filter(self, text):
        current = self.tag.currentText(); needle = text.lower()
        self.tag.clear(); self.tag.addItems([tag for tag in self.tags if needle in tag.lower()])
        self.tag.setCurrentText(current)

    def _load_binding(self, prop):
        binding = self.widget_model.bindings.get(prop) if self.widget_model else None
        if binding:
            self.tag.setCurrentText(binding.tag); self.format.setText(binding.format)
            self.multiplier.setValue(binding.multiplier); self.offset.setValue(binding.offset)
            self.unit.setText(binding.unit); self.warning.setText(binding.warning); self.critical.setText(binding.critical)

    def _apply(self):
        prop, tag = self.property.currentText(), self.tag.currentText().strip()
        if prop and tag:
            self.bindingEdited.emit(prop, DesignerBinding(tag, self.format.text(), self.multiplier.value(),
                self.offset.value(), self.unit.text(), self.warning.text(), self.critical.text()))

    def _remove(self):
        if self.property.currentText(): self.bindingEdited.emit(self.property.currentText(), None)


class DesignerWorkspace(QWidget):
    previewRequested = Signal(str)
    deployRequested = Signal(str)
    message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # The Designer contains several rich panes, but it must yield vertical
        # space to the Studio chrome/footer on scaled or smaller desktops.
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.registry = default_registry()
        self.generator = QmlGenerator(self.registry)
        self.project = DesignerProject()
        self.bundle_dir = ""
        self.file_path = ""
        self.current_page_index = 0
        self.undo_stack = QUndoStack(self)
        self.clipboard = []
        self._designer_icon_names = {}
        self._build_ui(); self._shortcuts(); self._load_page()

    @property
    def current_page(self):
        return self.project.pages[self.current_page_index]

    def _build_ui(self):
        self.setObjectName("designerWorkspace")
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 8, 8, 8); layout.setSpacing(6)
        primary = QToolBar("Designer primary actions")
        canvas_bar = QToolBar("Designer canvas actions")
        primary.setObjectName("designerPrimaryToolbar")
        canvas_bar.setObjectName("designerCanvasToolbar")
        for bar in (primary, canvas_bar):
            bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            bar.setFixedHeight(38)
        def action(bar, text, slot, icon_name="adjustments", shortcut=None, checkable=False):
            item = bar.addAction(icon(icon_name), text); item.triggered.connect(slot); item.setCheckable(checkable)
            self._designer_icon_names[item] = icon_name
            item.setToolTip(text + (f" ({shortcut})" if shortcut else ""))
            if shortcut: item.setShortcut(QKeySequence(shortcut))
            return item
        action(primary, "New UI", self.new_ui, "file-code")
        action(primary, "Open", self.open_ui, "folder-open")
        action(primary, "Save", self.save, "download", "Ctrl+S")
        primary.addSeparator()
        undo = self.undo_stack.createUndoAction(self, "Undo"); undo.setIcon(icon("history")); self._designer_icon_names[undo] = "history"; primary.addAction(undo)
        redo = self.undo_stack.createRedoAction(self, "Redo"); redo.setIcon(icon("rotate-clockwise")); self._designer_icon_names[redo] = "rotate-clockwise"; primary.addAction(redo)
        action(primary, "Cut", self.cut, "x", "Ctrl+X")
        action(primary, "Copy", self.copy, "clipboard-text", "Ctrl+C")
        action(primary, "Paste", self.paste, "clipboard-text", "Ctrl+V")
        action(primary, "Delete", self.delete_selected, "trash", "Delete")
        action(primary, "Duplicate", self.duplicate, "plus", "Ctrl+D")
        primary.addSeparator()
        action(primary, "Preview", self.preview, "player-play")
        action(primary, "Generate", self.generate, "file-code")
        action(primary, "Deploy", self.deploy, "upload")

        action(canvas_bar, "New Page", self.new_page, "folder-plus")
        action(canvas_bar, "Duplicate Page", self.duplicate_page, "clipboard-text")
        action(canvas_bar, "Delete Page", self.delete_page, "trash")
        self.pages = QComboBox(); self.pages.currentIndexChanged.connect(self.change_page); canvas_bar.addWidget(self.pages)
        canvas_bar.addSeparator(); canvas_bar.addWidget(QLabel(" W")); self.screen_width = QSpinBox(); self.screen_width.setRange(64, 16384); self.screen_width.setValue(1280); canvas_bar.addWidget(self.screen_width)
        canvas_bar.addWidget(QLabel(" H")); self.screen_height = QSpinBox(); self.screen_height.setRange(64, 16384); self.screen_height.setValue(800); canvas_bar.addWidget(self.screen_height)
        self.screen_width.valueChanged.connect(self._screen_changed); self.screen_height.valueChanged.connect(self._screen_changed)
        self.grid_action = action(canvas_bar, "Grid", self.toggle_grid, "adjustments", checkable=True); self.grid_action.setChecked(True)
        self.snap_action = action(canvas_bar, "Snap", self.toggle_snap, "plug-connected", checkable=True); self.snap_action.setChecked(True)
        canvas_bar.addSeparator()
        for label, mode in (("Left", "left"), ("Right", "right"), ("Top", "top"), ("Bottom", "bottom"),
                            ("H Center", "hcenter"), ("V Center", "vcenter"), ("Same W", "same_width"),
                            ("Same H", "same_height"), ("Distribute H", "distribute_h"), ("Distribute V", "distribute_v")):
            action(canvas_bar, label, lambda _checked=False, m=mode: self.align(m), "adjustments")
        action(canvas_bar, "Front", lambda: self.z_order("front"), "upload")
        action(canvas_bar, "Back", lambda: self.z_order("back"), "download")
        canvas_bar.addSeparator(); action(canvas_bar, "−", lambda: self.view.set_zoom(round(self.view.transform().m11()*100)-10), "x")
        self.zoom_label = QLabel("100%  "); canvas_bar.addWidget(self.zoom_label)
        action(canvas_bar, "+", lambda: self.view.set_zoom(round(self.view.transform().m11()*100)+10), "plus")
        action(canvas_bar, "Fit", self.view_fit, "device-desktop")
        layout.addWidget(primary); layout.addWidget(canvas_bar)
        split = QSplitter(Qt.Horizontal); split.setObjectName("designerMainSplitter"); split.setHandleWidth(4)
        left = QSplitter(Qt.Vertical); left.setHandleWidth(4)
        self.palette = WidgetPalette(self.registry); self.palette.setObjectName("designerPalette")
        self.tree = QTreeWidget(); self.tree.setObjectName("designerObjectTree"); self.tree.setHeaderLabel("Pages / Objects")
        left.addWidget(self._group("Widget Palette", self.palette)); left.addWidget(self._group("Object Tree", self.tree)); split.addWidget(left)
        left.setSizes([360, 260])
        self.scene = DesignerScene(self.registry); self.view = DesignerView(self.scene); self.view.setObjectName("designerCanvas"); split.addWidget(self.view)
        right = QSplitter(Qt.Vertical); right.setHandleWidth(4)
        self.properties = PropertyEditor(self.registry); self.bindings = BindingEditor(self.registry)
        right.addWidget(self._group("Properties", self._scroll_panel(self.properties)))
        right.addWidget(self._group("Tag Binding", self._scroll_panel(self.bindings)))
        right.addWidget(self._build_chat()); split.addWidget(right)
        right.setSizes([330, 300, 220])
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        split.setSizes([240, 700, 280]); layout.addWidget(split, 1)
        self.scene.widgetDropped.connect(self.add_widget); self.scene.selectionIdsChanged.connect(self._selection_changed)
        self.scene.geometryEdited.connect(self._geometry_command); self.tree.itemSelectionChanged.connect(self._tree_selection)
        self.tree.itemChanged.connect(self._tree_renamed); self.properties.propertyEdited.connect(self._property_command)
        self.properties.geometryEdited.connect(self._single_geometry_command); self.bindings.bindingEdited.connect(self._binding_command)
        self.properties.assetRequested.connect(self._choose_property_asset)
        self.scene.assetRequested.connect(self._asset_requested)
        self.scene.contextMenuRequested.connect(self._show_context_menu)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_context_menu)
        self.view.zoomChanged.connect(lambda value: self.zoom_label.setText(f"{value}%  "))
        # Match the Studio's Connect control exactly. QSS height is content-box
        # based for QPushButton on Windows, so a direct widget height avoids a
        # two-pixel platform-style expansion.
        for button in self.findChildren(QPushButton):
            button.setFixedHeight(36)

    def apply_theme(self, theme: str) -> None:
        """Re-render Designer icons and canvas chrome for the active theme."""
        for action, name in self._designer_icon_names.items():
            action.setIcon(icon(name))
        self.scene.set_theme(theme)
        panel = color("card", theme); border = color("border", theme)
        muted = color("muted", theme); foreground = color("foreground", theme)
        accent = color("accent", theme)
        self.setStyleSheet(f"""
            QWidget#designerWorkspace {{ background: {color('background', theme)}; }}
            QToolBar#designerPrimaryToolbar, QToolBar#designerCanvasToolbar {{
                background: {panel}; border: 1px solid {border}; border-radius: 8px;
                spacing: 2px; padding: 2px 5px;
            }}
            QToolBar#designerPrimaryToolbar QToolButton,
            QToolBar#designerCanvasToolbar QToolButton {{
                background: transparent; color: {foreground}; border: 1px solid transparent;
                border-radius: 8px; padding: 0 8px;
                min-height: 34px; max-height: 34px;
            }}
            QToolBar#designerPrimaryToolbar QToolButton:hover,
            QToolBar#designerCanvasToolbar QToolButton:hover {{ background: {accent}; }}
            QToolBar#designerPrimaryToolbar QToolButton:checked,
            QToolBar#designerCanvasToolbar QToolButton:checked {{
                background: {muted}; border-color: {border};
            }}
            QSplitter#designerMainSplitter::handle {{ background: {border}; }}
            QGroupBox[designerPanel="true"] {{
                background: {panel}; border: 1px solid {border}; border-radius: 9px;
                margin-top: 16px; padding-top: 5px;
            }}
            QGroupBox[designerPanel="true"]::title {{
                color: {foreground}; subcontrol-origin: margin; left: 8px;
                padding: 0 5px; font-size: 12px; font-weight: 700;
            }}
            QGraphicsView#designerCanvas {{
                border: 1px solid {border}; border-radius: 9px; background: {muted};
            }}
            QScrollArea#designerInspectorScroll,
            QScrollArea#designerInspectorScroll > QWidget > QWidget {{
                background: transparent; border: none;
            }}
            QTreeWidget#designerPalette, QTreeWidget#designerObjectTree {{
                border: none; border-radius: 6px; background: {color('background', theme)};
            }}
            QWidget#designerWorkspace QLineEdit,
            QWidget#designerWorkspace QComboBox,
            QWidget#designerWorkspace QSpinBox,
            QWidget#designerWorkspace QDoubleSpinBox {{
                min-height: 34px; max-height: 34px;
                border: 1px solid {color('input', theme)}; border-radius: 8px;
                background: {color('background', theme)}; color: {foreground};
                padding-top: 0; padding-bottom: 0;
            }}
            QWidget#designerWorkspace QPushButton {{
                border-radius: 8px; padding-top: 0; padding-bottom: 0;
            }}
            QPlainTextEdit {{
                background: {color('background', theme)}; color: {foreground};
                border: 1px solid {border}; border-radius: 6px;
            }}
        """)
        for button in self.findChildren(QPushButton):
            button.setFixedHeight(36)

    def _build_chat(self):
        panel = QWidget(); layout = QVBoxLayout(panel); layout.setContentsMargins(4, 8, 4, 4)
        self.chat_history = QPlainTextEdit(); self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText(
            "Text commands: add Value Tile; remove inputVoltage; "
            "set inputVoltage title=Input Voltage; bind inputVoltage value=power.input_voltage"
        )
        row = QHBoxLayout(); self.chat_input = QLineEdit(); self.chat_input.setPlaceholderText("Describe an edit…")
        send = QPushButton("Apply"); row.addWidget(self.chat_input, 1); row.addWidget(send)
        layout.addWidget(self.chat_history, 1); layout.addLayout(row)
        send.clicked.connect(self._apply_chat); self.chat_input.returnPressed.connect(self._apply_chat)
        return self._group("Design Chat", panel)

    def _apply_chat(self):
        """Apply a small, deterministic text-edit vocabulary.

        This local adapter makes text-based authoring useful without a network
        dependency and provides a stable seam for a future LLM provider.
        """
        command = self.chat_input.text().strip()
        if not command: return
        self.chat_history.appendPlainText(f"> {command}"); self.chat_input.clear()
        try:
            response = self.apply_text_command(command)
        except ValueError as exc:
            response = f"Could not apply: {exc}"
        self.chat_history.appendPlainText(response)

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

    def _group(self, title, child):
        box = QGroupBox(title); box.setProperty("designerPanel", True)
        lay = QVBoxLayout(box); lay.setContentsMargins(6, 10, 6, 6); lay.setSpacing(4); lay.addWidget(child); return box

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
                              ("Left", lambda: self.nudge(-1, 0)), ("Right", lambda: self.nudge(1, 0)),
                              ("Up", lambda: self.nudge(0, -1)), ("Down", lambda: self.nudge(0, 1)),
                              ("Shift+Left", lambda: self.nudge(-10, 0)), ("Shift+Right", lambda: self.nudge(10, 0)),
                              ("Shift+Up", lambda: self.nudge(0, -10)), ("Shift+Down", lambda: self.nudge(0, 10))):
            QShortcut(QKeySequence(key), self, activated=callback)

    def set_bundle(self, bundle_dir, manifest=None):
        self.bundle_dir = os.path.abspath(bundle_dir) if bundle_dir else ""
        self.scene.project_dir = self.bundle_dir
        self.bindings.set_tags((manifest or {}).get("tags_required", []))
        path = os.path.join(self.bundle_dir, "project.edsui") if self.bundle_dir else ""
        if path and os.path.isfile(path):
            self.load_file(path)
        else:
            screen = (manifest or {}).get("screen", {})
            self.project = DesignerProject(); self.project.screen.width = int(screen.get("width", 1280)); self.project.screen.height = int(screen.get("height", 800))
            self.file_path = path; self.current_page_index = 0; self.undo_stack.clear(); self._load_page()

    def new_ui(self):
        width = self.project.screen.width; height = self.project.screen.height
        self.project = DesignerProject(); self.project.screen.width = width; self.project.screen.height = height
        self.file_path = os.path.join(self.bundle_dir, "project.edsui") if self.bundle_dir else ""
        self.current_page_index = 0; self.undo_stack.clear(); self._load_page()

    def open_ui(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open visual UI", self.bundle_dir, "Embedded Display UI (*.edsui)")
        if path: self.load_file(path)

    def load_file(self, path):
        try:
            self.project = DesignerProject.load(path); self.file_path = os.path.abspath(path); self.bundle_dir = os.path.dirname(self.file_path)
            self.scene.project_dir = self.bundle_dir
            self.current_page_index = 0; self.undo_stack.clear(); self._load_page(); self.message.emit(f"Opened {path}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QMessageBox.critical(self, "Could not open UI", str(exc))

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

    def add_widget(self, widget_type, x=20, y=20, parent_id=""):
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
        for parent_id, source in self.clipboard:
            model = copy.deepcopy(source); model.id = self.project.unique_id(source.id); model.geometry["x"] += 10; model.geometry["y"] += 10
            for child in model.walk():
                if child is not model: child.id = self.project.unique_id(child.id)
            siblings = self.siblings_of(parent_id)
            def redo(m=model, s=siblings): s.append(m) if m not in s else None; self._load_page(select=[m.id])
            def undo(m=model, s=siblings): s.remove(m) if m in s else None; self._load_page()
            self.undo_stack.push(CallbackCommand("Paste widget", redo, undo))
    def duplicate(self): self.copy(); self.paste()

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

    def _load_page(self, select=None):
        self.current_page_index = min(self.current_page_index, len(self.project.pages)-1)
        self.pages.blockSignals(True); self.pages.clear(); self.pages.addItems([p.name for p in self.project.pages]); self.pages.setCurrentIndex(self.current_page_index); self.pages.blockSignals(False)
        self.scene.load_page(self.project, self.current_page); self._refresh_tree()
        if self.view.isVisible():
            self.view.fit_canvas()
        self.screen_width.blockSignals(True); self.screen_height.blockSignals(True)
        self.screen_width.setValue(self.project.screen.width); self.screen_height.setValue(self.project.screen.height)
        self.screen_width.blockSignals(False); self.screen_height.blockSignals(False)
        for widget_id in select or []:
            item = self.scene.item_for_id(widget_id)
            if item: item.setSelected(True)

    def _refresh_tree(self):
        self.tree.blockSignals(True); self.tree.clear(); root = QTreeWidgetItem([self.current_page.name]); root.setData(0, Qt.UserRole, "")
        self.tree.addTopLevelItem(root)
        def add(parent, model):
            item = QTreeWidgetItem([model.id]); item.setData(0, Qt.UserRole, model.id); item.setFlags(item.flags() | Qt.ItemIsEditable); parent.addChild(item)
            for child in model.children: add(item, child)
        for model in self.current_page.widgets: add(root, model)
        root.setExpanded(True); self.tree.blockSignals(False)

    def _selection_changed(self, ids):
        model = self._find(ids[0]) if len(ids) == 1 else None
        parent = self._find(self.parent_id_of(model)) if model else None
        self.properties.set_widget(model, positioned=bool(parent and parent.type in POSITIONERS))
        self.bindings.set_widget(model)
        self.tree.blockSignals(True); self.tree.clearSelection()
        if ids:
            iterator = self.tree.findItems(ids[0], Qt.MatchExactly | Qt.MatchRecursive)
            if iterator: iterator[0].setSelected(True)
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

    def change_page(self, index):
        if index >= 0: self.current_page_index = index; self._load_page()
    def new_page(self):
        number = len(self.project.pages)+1; page = DesignerPage(self.project.unique_id(f"page{number}"), f"Page {number}")
        self.project.pages.append(page); self.current_page_index = len(self.project.pages)-1; self._load_page()
    def duplicate_page(self):
        source = self.current_page; number = len(self.project.pages) + 1
        page = copy.deepcopy(source); page.id = self.project.unique_id(f"page{number}"); page.name = f"{source.name} Copy"
        for widget in page.walk(): widget.id = self.project.unique_id(widget.id)
        self.project.pages.append(page); self.current_page_index = len(self.project.pages)-1; self._load_page()
    def delete_page(self):
        if len(self.project.pages) == 1:
            QMessageBox.information(self, "Page required", "A design must contain at least one page."); return
        del self.project.pages[self.current_page_index]; self.current_page_index = min(self.current_page_index, len(self.project.pages)-1); self._load_page()
    def select_all(self):
        for item in self.scene.items():
            if hasattr(item, "widget_model"): item.setSelected(True)
    def nudge(self, dx, dy):
        models = self.scene.selected_models()
        for model in models: model.geometry["x"] += dx; model.geometry["y"] += dy
        if models: self._load_page(select=[m.id for m in models])
    def _screen_changed(self):
        if not hasattr(self, "scene"): return
        self.project.screen.width = self.screen_width.value(); self.project.screen.height = self.screen_height.value()
        self.scene.update_screen_rect(); self.scene.update()
    def align(self, mode):
        models = self.scene.selected_models()
        if len(models) < 2: return
        g = [model.geometry for model in models]; anchor = g[0]
        if mode == "left":
            for item in g[1:]: item["x"] = anchor["x"]
        elif mode == "right":
            edge = anchor["x"] + anchor["width"]
            for item in g[1:]: item["x"] = edge - item["width"]
        elif mode == "top":
            for item in g[1:]: item["y"] = anchor["y"]
        elif mode == "bottom":
            edge = anchor["y"] + anchor["height"]
            for item in g[1:]: item["y"] = edge - item["height"]
        elif mode == "hcenter":
            center = anchor["x"] + anchor["width"] / 2
            for item in g[1:]: item["x"] = center - item["width"] / 2
        elif mode == "vcenter":
            center = anchor["y"] + anchor["height"] / 2
            for item in g[1:]: item["y"] = center - item["height"] / 2
        elif mode == "same_width":
            for item in g[1:]: item["width"] = anchor["width"]
        elif mode == "same_height":
            for item in g[1:]: item["height"] = anchor["height"]
        elif mode.startswith("distribute_") and len(g) > 2:
            axis = "x" if mode.endswith("h") else "y"; ordered = sorted(g, key=lambda item: item[axis])
            span = ordered[-1][axis] - ordered[0][axis]
            for index, item in enumerate(ordered[1:-1], 1): item[axis] = ordered[0][axis] + span * index / (len(ordered)-1)
        self._load_page(select=[m.id for m in models])
    def z_order(self, mode):
        models = self.scene.selected_models()
        if not models: return
        values = [widget.z for widget in self.current_page.walk()]
        target = (max(values or [0]) + 1) if mode == "front" else (min(values or [0]) - 1)
        for model in models: model.z = target
        self._load_page(select=[m.id for m in models])
    def toggle_grid(self, checked): self.scene.grid_visible = checked; self.scene.update()
    def toggle_snap(self, checked): self.scene.snap_enabled = checked
    def view_fit(self): self.view.fit_canvas()

    def _update_manifest(self, entry):
        path = os.path.join(self.bundle_dir, "manifest.json")
        manifest = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as handle: manifest = json.load(handle)
        manifest.update({"schema": 1, "name": manifest.get("name", "designed-ui"), "version": manifest.get("version", "1.0.0"),
                         "entry": entry.replace(os.sep, "/"), "runtime": "qml",
                         "screen": {"width": self.project.screen.width, "height": self.project.screen.height},
                         "tags_required": self.project.required_tags()})
        with open(path, "w", encoding="utf-8", newline="\n") as handle: json.dump(manifest, handle, indent=2); handle.write("\n")

    def generate(self):
        if not self.bundle_dir:
            QMessageBox.warning(self, "No project", "Open an application bundle before generating."); return []
        if not self.save(): return []
        try:
            output_dir = os.path.join(self.bundle_dir, "generated")
            paths = self.generator.write(self.project, output_dir, self.bundle_dir)
            entry = os.path.relpath(paths[0], self.bundle_dir); self._update_manifest(entry)
            self.bindings.set_tags(self.project.required_tags()); self.message.emit(f"Generated {len(paths)} QML page(s) in {output_dir}"); return paths
        except (OSError, QmlGenerationError, ValueError) as exc:
            QMessageBox.critical(self, "Generation failed", str(exc)); return []
    def preview(self):
        if self.generate(): self.previewRequested.emit(self.bundle_dir)
    def deploy(self):
        if self.generate(): self.deployRequested.emit(self.bundle_dir)

    def choose_image_asset(self, source_path):
        if not self.bundle_dir: raise ValueError("open a bundle before adding assets")
        assets = os.path.join(self.bundle_dir, "assets"); os.makedirs(assets, exist_ok=True)
        destination = os.path.join(assets, os.path.basename(source_path))
        if os.path.abspath(source_path) != os.path.abspath(destination): shutil.copy2(source_path, destination)
        return os.path.relpath(destination, self.bundle_dir).replace(os.sep, "/")

    def _ensure_project_location(self):
        """Assets are copied beside the project, so it needs a home on disk first."""
        if self.bundle_dir:
            return True
        answer = QMessageBox.question(
            self, "Save the project first",
            "Images are copied into the project's assets folder, so this UI needs a "
            "location on disk before an image can be added.\n\nSave it now?",
            QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Save)
        if answer != QMessageBox.Save:
            return False
        return bool(self.save() and self.bundle_dir)

    def _asset_requested(self, widget_id, property_name):
        """Double-clicking the widget itself is the shortest way to its image."""
        item = self.scene.item_for_id(widget_id)
        if item:
            self.scene.clearSelection(); item.setSelected(True)
        self._choose_property_asset(property_name)

    def context_menu(self, widget_id):
        """The actions a widget offers on right-click, Qt Designer style."""
        menu = QMenu(self)
        model = self._find(widget_id) if widget_id else None
        definition = self.registry.get(model.type) if model else None
        if model is not None:
            for name in (definition.asset_properties if definition else ()):
                label = "Image" if name == "source" else name
                current = model.properties.get(name)
                menu.addAction(f"Change {label}..." if current else f"Set {label}...",
                               lambda checked=False, n=name: self._asset_requested(widget_id, n))
                if current:
                    menu.addAction(f"Clear {label}",
                                   lambda checked=False, n=name: self._property_command(n, ""))
            if definition and definition.asset_properties:
                menu.addSeparator()
            menu.addAction("Cut", self.cut)
            menu.addAction("Copy", self.copy)
            menu.addAction("Duplicate", self.duplicate)
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
