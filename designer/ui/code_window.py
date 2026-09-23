"""designer/ui/code_window.py -- the Studio's Code window.

FROZEN CONTRACT (Code window swarm, 2026-09-22). Owner: W3. Public names,
signatures and signals below are the contract; W3 fills them in and may add
private helpers and private classes.

A separate, non-modal window ("Code") beside the Studio that shows the code
of what is selected in the Designer and follows the selection live:

    toolbar   Scope: [Selected widget | Whole screen]   Format: [QML (desktop preview) | Design JSON]
              [Preview] toggle   ...   [Apply] [Copy] [Save as...]
    body      left: title line + CodeEditor (designer/ui/code_editor.py)
              right (when Preview is on): the same section rendered by the
              workspace's renderer (workspace.scene.qml_previews): hmi-ui, the
              panel's own, when its binary is at hand (a page is rendered
              whole through page_image_for), else the Qt/QML fallback (a page
              goes through a "Rectangle" wrapper holding its widgets). Fitted
              to the pane, aspect kept, re-rendered when the design changes.
    status    a line for messages: 'Applied', an error from CodeError, etc.

Behaviour:
  * Follows workspace.scene.selectionIdsChanged (widget scope shows the first
    selected widget; none selected -> the "nothing selected" section), and
    workspace.designChanged / page changes (refreshes the text; the editor
    keeps its scroll position).
  * QML sections are read-only. Design JSON sections are editable; while the
    text differs from the model's, the title gets a ' *' and Apply is enabled.
    Apply parses with designer.code.parse_widget_edsui / parse_page_edsui and
    calls workspace.replace_widget / workspace.replace_page (one undo step);
    a CodeError goes to the status line and the editor jumps to the line
    when the message names one.
  * Switching scope/format while edited asks Discard/Keep (Keep stays).
  * Closing the window hides it (the workspace keeps one instance).
  * apply_theme follows the workspace's theme.
"""
from __future__ import annotations

import hashlib
import json
import re

from PySide6.QtCore import QRect, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow, QMessageBox, QSizePolicy,
    QSplitter, QToolBar, QVBoxLayout, QWidget,
)

# Module references, not names: the functions and the editor class are looked
# up when they are used, so a test can stand in for a piece that has not
# landed yet without reaching into this module.
from designer import code as design_code
from designer.model import DesignerWidget
from designer.ui import code_editor

try:
    from ui.python.shadcn import color, icon
except ImportError:
    from PySide6.QtGui import QIcon

    _FALLBACK_TOKENS = {
        "dark": {"background": "#09090b", "card": "#18181b", "border": "#27272a",
                 "foreground": "#fafafa", "mutedForeground": "#a1a1aa", "primary": "#fafafa"},
        "light": {"background": "#ffffff", "card": "#ffffff", "border": "#e4e4e7",
                  "foreground": "#09090b", "mutedForeground": "#71717a", "primary": "#18181b"},
    }

    def icon(_name, _size=16, _color=None): return QIcon()

    def color(name, theme="dark"): return _FALLBACK_TOKENS[theme][name]

SCOPES = ("widget", "page")
# The Code section shows what the panel runs: the design itself. The QML the
# generator writes is the desktop's own preview code and is not offered here
# (designer.code still produces it for tools that want it).
FORMATS = ("edsui", "c")
SCOPE_LABELS = ("Selected widget", "Whole screen")
# The Format combo, top to bottom, mapped to FORMATS explicitly: the tuple
# above is the contract's order and the section identity, the combo is
# presentation. The design is what the panel runs; QML is only what this
# desktop's Qt preview runs.
# What the panel runs comes first; the QML is the desktop's preview code.
FORMAT_ORDER = ("edsui", "c")
FORMAT_LABELS_BY_FMT = {"edsui": "Design (.edsui)", "c": "Runtime C (hmi-ui)", "qml": "QML (desktop preview)"}
FORMAT_LABELS = tuple(FORMAT_LABELS_BY_FMT[f] for f in FORMAT_ORDER)
# What the section title's suffix says here, over the code model's own
# wording, so the title and the Format combo tell the same story.
TITLE_SUFFIXES = {" -- generated QML": " -- QML (desktop preview)",
                  " -- design JSON": " -- design (.edsui)"}
SETTINGS_KEY = "codeWindow/geometry"
DEFAULT_SIZE = QSize(1000, 700)
# The wrapper the whole screen is rendered through; its id never clashes
# with a design id because "__" is not what the id validator hands out.
PAGE_WRAPPER_ID = "__page__"
PREVIEWS_OFF = "Live previews are off (Designer toolbar)"
RENDERING = "Rendering..."
NOTHING_SELECTED = "Nothing selected"
UNAVAILABLE = "This section did not render"


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})"


class _PreviewPane(QWidget):
    """The right-hand pane: one QImage fitted to whatever room it has, or a
    line of text saying why there is no image yet.

    While a render is on its way (the RENDERING message) a pixel-mosaic
    loader fills the pane (ui/python/fx/mosaic.py, Libraries.dev img-fx);
    when the image lands it dissolves into it at the image's final size and
    place, then the plain label takes over again."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("codePreviewPane")
        self.setMinimumWidth(160)
        self._image = None
        self._label = QLabel(self)
        self._label.setObjectName("codePreviewImage")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        # A QLabel holding a pixmap wants at least the pixmap's size, which
        # would stop the splitter from ever shrinking the pane again once a
        # full-screen render landed. Let the layout decide and fit to it.
        self._label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._label.setMinimumSize(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._label)
        from ui.python.fx.mosaic import MosaicView
        self._mosaic = MosaicView(self, radius=10)
        self._mosaic.hide()

    def set_theme(self, theme: str) -> None:
        self._mosaic.set_theme(theme)

    def set_image(self, image) -> None:
        self._image = image
        self._label.setText("")
        if self._mosaic.isVisible() and self._mosaic.loading() and image is not None and not image.isNull():
            self._mosaic.setGeometry(self._image_rect(image))
            self._mosaic.set_image(image)
            from ui.python.fx.mosaic import REVEAL_S
            QTimer.singleShot(int(REVEAL_S * 1000) + 120, self._settle)
            return
        self._settle()

    def set_message(self, text: str) -> None:
        self._image = None
        self._label.setPixmap(QPixmap())
        if text == RENDERING:
            self._label.setText("")
            self._mosaic.setGeometry(self._label.geometry())
            self._mosaic.show()
            self._mosaic.raise_()
            self._mosaic.set_loading()
            return
        self._mosaic.set_message("")
        self._mosaic.hide()
        self._label.setText(text)

    def _settle(self) -> None:
        if self._mosaic.revealing():
            return
        self._mosaic.set_message("")
        self._mosaic.hide()
        self._fit()

    def _image_rect(self, image):
        """Where _fit will put `image` inside the label (the reveal lands there)."""
        area = self._label.geometry()
        size = image.size()
        if size.width() > area.width() or size.height() > area.height():
            size = size.scaled(area.size(), Qt.KeepAspectRatio)
        x = area.x() + (area.width() - size.width()) // 2
        y = area.y() + (area.height() - size.height()) // 2
        return QRect(x, y, size.width(), size.height())

    def _fit(self) -> None:
        if self._image is None or self._image.isNull():
            return
        area = self._label.size()
        if area.width() < 2 or area.height() < 2:
            return
        pixmap = QPixmap.fromImage(self._image)
        # Shrink to fit, never enlarge: a render is at the section's real
        # pixel size, and blowing a 160 px widget up to fill the pane only
        # blurs it. Small sections sit centred at 1:1 with room around them.
        area = area.boundedTo(pixmap.size() + QSize(0, 0)) if (pixmap.width() <= area.width() and pixmap.height() <= area.height()) else area
        self._label.setPixmap(pixmap.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class CodeWindow(QMainWindow):
    """The Code window bound to one DesignerWorkspace.

    Signals:
        sectionChanged(str, str): (scope, fmt) after the view switched.

    Public attributes (part of the contract; tests use them):
        editor: the CodeEditor.
        preview: the preview pane widget (a QWidget; hidden when off).
    """

    sectionChanged = Signal(str, str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        self._workspace = workspace
        # Opens on the design: it is what the panel runs and what can be edited.
        self._scope, self._fmt = "widget", "edsui"
        # The section the editor currently holds, the text the window put
        # there, and what it belongs to (a widget id or a page index). An edit
        # is measured against the loaded text rather than against the live
        # model, so an Apply followed by Undo -- the model moving under a
        # text the user did not touch -- reads as "not edited" and refreshes.
        self._section = None
        self._loaded_text = ""
        self._target = None
        # Set when a refresh left an edit alone; the next time the text is
        # back to what was loaded, the skipped refresh is made up.
        self._stale = False
        self._theme = "dark"
        self._icon_names = {}
        self.setWindowTitle("Code")
        self.setObjectName("codeWindow")
        self._build_ui()
        self._connect(workspace)
        self.resize(DEFAULT_SIZE)
        geometry = QSettings("EmbeddedDisplay", "Studio").value(SETTINGS_KEY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.apply_theme(getattr(workspace, "theme", "dark"))
        self.refresh()

    # ---------------------------------------------------------------- API

    @property
    def scope(self) -> str:
        """'widget' or 'page'."""
        return self._scope

    @property
    def fmt(self) -> str:
        """'qml' or 'edsui'."""
        return self._fmt

    def show_section(self, scope: str, fmt: str) -> None:
        """Switches the view (asks about unapplied edits first)."""
        if scope not in SCOPES or fmt not in FORMATS:
            raise ValueError(f"unknown section {scope!r}/{fmt!r}")
        if (scope, fmt) == (self._scope, self._fmt) and self._section is not None:
            self._sync_boxes()
            return
        if self.is_edited() and not self._confirm_discard():
            self._sync_boxes()
            return
        self._scope, self._fmt = scope, fmt
        self._sync_boxes()
        self._load(overwrite=True, keep_scroll=False)
        self.sectionChanged.emit(scope, fmt)

    def refresh(self) -> None:
        """Re-reads the model into the editor and preview (called on
        selection/design changes; safe to call at any time)."""
        self._load(overwrite=False, keep_scroll=True)

    def set_preview_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self._preview_action.blockSignals(True)
        self._preview_action.setChecked(visible)
        self._preview_action.blockSignals(False)
        self.preview.setVisible(visible)
        if visible:
            # A pane that was hidden when the splitter first laid out comes
            # back at its minimum width; give it its share once.
            if self.preview.width() <= self.preview.minimumWidth():
                total = max(self._splitter.width(), DEFAULT_SIZE.width())
                self._splitter.setSizes([total * 3 // 5, total * 2 // 5])
            self._refresh_preview()

    def preview_visible(self) -> bool:
        return self._preview_action.isChecked()

    def is_edited(self) -> bool:
        """True while the editor text differs from the model's JSON."""
        return bool(self._section is not None and self._section.editable
                    and self.editor.code() != self._loaded_text)

    def apply(self) -> bool:
        """Parses and applies an edited design JSON. True on success."""
        section = self._section
        if section is None or not section.editable:
            self._say("Nothing to apply: this view is read-only")
            return False
        workspace, text = self._workspace, self.editor.code()
        try:
            if section.scope == "widget":
                widget_id = self._target
                if not widget_id:
                    self._say("Nothing to apply: no widget is selected")
                    return False
                new = design_code.parse_widget_edsui(text, workspace.registry, workspace.project,
                                                     replacing=widget_id)
                applied = workspace.replace_widget(widget_id, new)
                what = f'widget "{widget_id}"'
            else:
                index = self._target if isinstance(self._target, int) else -1
                pages = workspace.project.pages
                page = pages[index] if 0 <= index < len(pages) else None
                new = design_code.parse_page_edsui(text, workspace.registry, workspace.project,
                                                   replacing=page.id if page else None)
                applied = workspace.replace_page(index, new)
                what = f"page {index + 1}"
        except design_code.CodeError as exc:
            self._report_error(str(exc))
            return False
        except ValueError as exc:
            # The model's own complaint (from_dict on a value it cannot
            # take) is as much a code error as a parse failure is.
            self._report_error(str(exc))
            return False
        if not applied:
            self._say(f"Could not apply: {what} is no longer in the design")
            return False
        # The model holds what was parsed; show it the way the model writes
        # it, so the view and the model agree byte for byte from here on.
        self._load(overwrite=True, keep_scroll=True)
        self._say("Applied")
        return True

    # -- FROZEN CONTRACT additions (native previews swarm, 2026-09-22; owner W3) --
    def format_label(self, fmt: str) -> str:
        """The Format combo's label for 'edsui' / 'qml'. The design is what the
        panel runs and comes first ("Design (.edsui)"); QML is labelled as the
        desktop's preview code ("QML (desktop preview)")."""
        if fmt not in FORMATS:
            raise ValueError(f"unknown format {fmt!r}")
        return FORMAT_LABELS_BY_FMT[fmt]

    def preview_image(self):
        """The QImage currently shown in the preview pane, or None."""
        image = self.preview._image
        return image if image is not None and not image.isNull() else None

    def preview_renderer_name(self) -> str:
        """'hmi-ui' when the preview pane is drawn by the panel's renderer
        (designer.preview.NativeRenderer), 'qml' when by the Qt fallback."""
        name = getattr(self._workspace, "preview_renderer_name", None)
        if name in ("hmi-ui", "qml"):
            return name
        return "hmi-ui" if self._page_renderer() is not None else "qml"

    def status_text(self) -> str:
        """What the status line says (tests read it)."""
        return self.statusBar().currentMessage()

    def apply_theme(self, theme: str) -> None:
        theme = "light" if theme == "light" else "dark"
        self._theme = theme
        self.editor.apply_theme(theme)
        self.preview.set_theme(theme)
        t = lambda name: color(name, theme)
        # W2's editor palette, when it says what its surface is, wins for
        # the panes that touch the editor so code and preview sit on one
        # colour; the chrome keeps the Studio's tokens.
        palette = getattr(code_editor, "LIGHT_PALETTE" if theme == "light" else "DARK_PALETTE", None)
        palette = palette if isinstance(palette, dict) else {}
        bg, fg = palette.get("background", t("background")), palette.get("foreground", t("foreground"))
        card, border, muted_fg, primary = t("card"), t("border"), t("mutedForeground"), t("primary")
        surface = card if theme == "dark" else t("background")
        raised = _rgba(fg, 0.035 if theme == "dark" else 0.025)
        hover = _rgba(fg, 0.06)
        mono = '"Cascadia Mono", Consolas, Menlo, "DejaVu Sans Mono", monospace'
        for action, name in self._icon_names.items():
            action.setIcon(icon(name, 16, fg))
        # The same chevron the Designer's combos use (a QSS image has to be a file).
        from designer.ui.designer_workspace import _icon_file
        arrow = _icon_file("chevron-down", 12, muted_fg)
        self.setStyleSheet(f"""
            QMainWindow#codeWindow {{ background: {bg}; }}
            QMainWindow#codeWindow QWidget {{ font-size: 12px; }}
            QSplitter#codeSplitter::handle {{ background: {border}; }}
            QWidget#codeEditorPane, QWidget#codePreviewPane {{ background: {bg}; }}
            QLabel#codePreviewImage {{ background: transparent; color: {muted_fg}; }}
            QLabel#codeTitle {{
                background: {bg}; color: {muted_fg}; font-family: {mono}; font-size: 11px;
                border-bottom: 1px solid {border}; padding: 6px 12px;
            }}
            QToolBar#codeToolbar {{
                background: {surface}; border: none; border-bottom: 1px solid {border};
                padding: 0 10px; spacing: 2px;
            }}
            QToolBar#codeToolbar::separator {{ background: {border}; width: 1px; margin: 8px 6px; }}
            QToolBar#codeToolbar QToolButton {{
                background: transparent; color: {fg}; border: 1px solid transparent;
                border-radius: 6px; padding: 0 8px; min-height: 26px; max-height: 26px;
            }}
            QToolBar#codeToolbar QToolButton:hover {{ background: {hover}; }}
            QToolBar#codeToolbar QToolButton:pressed {{ background: {_rgba(primary, 0.15)}; }}
            QToolBar#codeToolbar QToolButton:checked {{
                background: {_rgba(primary, 0.14)}; border-color: {_rgba(primary, 0.35)}; }}
            QToolBar#codeToolbar QToolButton:disabled {{ color: {_rgba(fg, 0.35)}; }}
            QLabel#barCaption {{
                background: transparent; color: {muted_fg}; font-size: 10px; font-weight: 600;
                letter-spacing: 1px;
            }}
            QWidget#barSpacer {{ background: transparent; }}
            QComboBox#barField {{
                background: {raised}; color: {fg}; border: 1px solid {border}; border-radius: 5px;
                padding: 0 24px 0 8px; height: 24px; min-height: 22px; max-height: 24px; font-size: 12px;
            }}
            QComboBox#barField:hover {{ border-color: {_rgba(primary, 0.55)}; }}
            QComboBox#barField::drop-down {{
                subcontrol-origin: padding; subcontrol-position: center right;
                width: 22px; border: none; background: transparent;
            }}
            QComboBox#barField::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; }}
            QComboBox#barField QAbstractItemView {{
                background: {surface}; color: {fg}; border: 1px solid {border};
                selection-background-color: {_rgba(primary, 0.18)}; selection-color: {fg};
            }}
            QStatusBar {{ background: {surface}; color: {muted_fg}; border-top: 1px solid {border}; }}
            QStatusBar::item {{ border: none; }}
        """)

    # ------------------------------------------------------------- build

    def _build_ui(self) -> None:
        bar = QToolBar("Code window actions")
        bar.setObjectName("codeToolbar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.setIconSize(QSize(16, 16))
        bar.setFixedHeight(36)
        bar.layout().setSpacing(4)
        bar.layout().setContentsMargins(0, 0, 0, 0)
        self.addToolBar(bar)

        def caption(text):
            label = QLabel(text.upper())
            label.setObjectName("barCaption")
            label.setContentsMargins(8, 0, 6, 0)
            label.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
            bar.addWidget(label)

        def field(text, labels, width, tooltip):
            caption(text)
            box = QComboBox()
            box.setObjectName("barField")
            box.addItems(list(labels))
            # Wide enough for the longest entry plus the drop-down arrow under
            # the Studio's stylesheet (a fixed width clipped "Selected widget"
            # and hid the arrow once the app font applied); `width` is a floor.
            longest = max(box.fontMetrics().horizontalAdvance(label) for label in labels)
            box.setMinimumWidth(max(width, longest + 2 * 8 + 26))
            box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            box.setFixedHeight(24)
            box.setToolTip(tooltip)
            bar.addWidget(box)
            gap = QWidget()
            gap.setObjectName("barSpacer")
            gap.setFixedWidth(10)
            bar.addWidget(gap)
            return box

        def action(text, slot, icon_name, checkable=False):
            item = bar.addAction(icon(icon_name), text)
            item.setCheckable(checkable)
            item.setToolTip(text)
            self._icon_names[item] = icon_name
            (item.toggled if checkable else item.triggered).connect(slot)
            button = bar.widgetForAction(item)
            if button is not None:
                button.setCursor(Qt.PointingHandCursor)
            return item

        self._scope_box = field("Scope", SCOPE_LABELS, 140, "What the code is of")
        self._fmt_box = field("Format", FORMAT_LABELS, 150,
                              "The design the panel runs (editable), or the C that draws it in hmi-ui (read-only)")
        self._scope_box.currentIndexChanged.connect(self._box_changed)
        self._fmt_box.currentIndexChanged.connect(self._box_changed)
        bar.addSeparator()
        self._preview_action = action("Preview", self.set_preview_visible, "eye", checkable=True)
        spacer = QWidget()
        spacer.setObjectName("barSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self._apply_action = action("Apply", self.apply, "check")
        self._apply_action.setEnabled(False)
        self._copy_action = action("Copy", self._copy, "copy")
        self._save_action = action("Save as...", self._save_as, "device-floppy")

        splitter = self._splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("codeSplitter")
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setObjectName("codeEditorPane")
        column = QVBoxLayout(left)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._title = QLabel()
        self._title.setObjectName("codeTitle")
        column.addWidget(self._title)
        self.editor = code_editor.CodeEditor(left)
        self.editor.codeEdited.connect(self._edited)
        column.addWidget(self.editor, 1)
        self.preview = _PreviewPane()
        self.preview.hide()
        splitter.addWidget(left)
        splitter.addWidget(self.preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.statusBar().setSizeGripEnabled(True)

    def _connect(self, workspace) -> None:
        workspace.scene.selectionIdsChanged.connect(self._selection_changed)
        workspace.designChanged.connect(self.refresh)
        workspace.pageChanged.connect(self._page_changed)
        renderer = getattr(workspace.scene, "qml_previews", None)
        if renderer is not None:
            renderer.ready.connect(self._preview_ready)

    # ------------------------------------------------------------ slots

    def _box_changed(self, _index) -> None:
        self.show_section(SCOPES[self._scope_box.currentIndex()], FORMAT_ORDER[self._fmt_box.currentIndex()])

    def _sync_boxes(self) -> None:
        for box, values, current in ((self._scope_box, SCOPES, self._scope), (self._fmt_box, FORMAT_ORDER, self._fmt)):
            box.blockSignals(True)
            box.setCurrentIndex(values.index(current))
            box.blockSignals(False)

    def _selection_changed(self, _ids) -> None:
        # A page view does not change with the selection; reloading it would
        # only reset the editor's undo history for nothing.
        if self._scope == "widget":
            self.refresh()
        else:
            self._refresh_preview()

    def _page_changed(self, _index) -> None:
        self.refresh()

    def _preview_ready(self, _key) -> None:
        if self.preview_visible():
            self._refresh_preview()

    def _edited(self) -> None:
        edited = self.is_edited()
        self._apply_action.setEnabled(edited)
        self._update_title()
        if not edited and self._stale:
            self.refresh()

    # ------------------------------------------------------------ loading

    def _load(self, *, overwrite: bool, keep_scroll: bool) -> None:
        if not overwrite and self.is_edited():
            # The user's text stays; the model has moved on underneath it.
            self._stale = True
            self._update_title()
            self._refresh_preview()
            return
        section, target = self._read_section()
        self._section, self._target, self._stale = section, target, False
        self.editor.set_language(section.language)
        self.editor.set_read_only_view(not section.editable)
        if self.editor.code() != section.text:
            self.editor.set_code(section.text, keep_scroll=keep_scroll)
        self._loaded_text = section.text
        self._apply_action.setEnabled(False)
        self._update_title()
        self._refresh_preview()

    def _read_section(self):
        workspace = self._workspace
        widget = workspace.selected_widget() if self._scope == "widget" else None
        page = workspace.current_page
        target = (widget.id if widget else None) if self._scope == "widget" else workspace.current_page_index
        try:
            section = design_code.section_for(workspace.generator, workspace.registry, workspace.project,
                                              page, widget, self._scope, self._fmt)
        except Exception as exc:      # noqa: BLE001 -- a code view must never take the Studio down
            section = design_code.CodeSection(self._scope, self._fmt, "Code unavailable",
                                              f"// {exc}\n", False, "plain")
        return section, target

    def _update_title(self) -> None:
        if self._section is None:
            self._title.setText("")
            return
        title = self._section.title
        for suffix, shown in TITLE_SUFFIXES.items():
            if title.endswith(suffix):
                title = title[:-len(suffix)] + shown
                break
        self._title.setText(title + (" *" if self.is_edited() else ""))

    def _confirm_discard(self) -> bool:
        box = QMessageBox(QMessageBox.Question, "Unapplied edits",
                          "The design JSON has edits that were not applied.", parent=self)
        box.setInformativeText("Discard them and switch the view, or keep editing?")
        discard = box.addButton("Discard", QMessageBox.DestructiveRole)
        keep = box.addButton("Keep", QMessageBox.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.exec()
        return box.clickedButton() is discard

    # ------------------------------------------------------------ preview

    def _refresh_preview(self) -> None:
        if not self.preview_visible():
            return
        workspace = self._workspace
        renderer = getattr(workspace.scene, "qml_previews", None)
        if renderer is None or not renderer.enabled:
            self.preview.set_message(PREVIEWS_OFF)
            return
        screen = workspace.project.screen
        if self._scope == "widget":
            widget = workspace.selected_widget()
            if widget is None:
                self.preview.set_message(NOTHING_SELECTED)
                return
            width, height = widget.geometry.get("width", 0), widget.geometry.get("height", 0)
            image = renderer.image_for(widget, width, height, screen.theme, 1.0)
        elif self._page_renderer() is not None:
            # The panel's renderer draws a page as the panel does, from the
            # project itself; the Rectangle wrapper below is only how the QML
            # renderer, which knows nothing of pages, is handed a whole screen.
            image = renderer.page_image_for(workspace.project, workspace.current_page, screen.theme, 1.0)
        else:
            widget = self._page_wrapper(workspace.current_page, screen)
            image = renderer.image_for(widget, screen.width, screen.height, screen.theme, 1.0)
        if image is None:
            self.preview.set_message(RENDERING)
        elif image.isNull():
            self.preview.set_message(UNAVAILABLE)
        else:
            self.preview.set_image(image)

    def _page_renderer(self):
        """The scene's renderer when it can draw a whole page itself
        (designer.preview.NativeRenderer), else None."""
        renderer = getattr(self._workspace.scene, "qml_previews", None)
        return renderer if callable(getattr(renderer, "page_image_for", None)) else None

    @staticmethod
    def _page_wrapper(page, screen) -> DesignerWidget:
        """The page's widgets on one Rectangle the renderer can draw whole:
        the screen, with the design's background, as the page file paints it.

        The renderer keys its cache on the wrapper's own properties and its
        children's ids, not on what the children hold, so a property edit
        on the page would keep showing the old render. Folding a digest of
        the page into a property the generator never emits (it is not a
        registered Rectangle property) makes the key follow the content.
        """
        content = json.dumps([w.to_dict() for w in page.widgets], sort_keys=True, default=str)
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()
        return DesignerWidget(type="Rectangle", id=PAGE_WRAPPER_ID,
                              geometry={"x": 0, "y": 0, "width": screen.width, "height": screen.height},
                              properties={"color": screen.background, "borderWidth": 0, "radius": 0,
                                          "_content": digest},
                              children=list(page.widgets))

    # ------------------------------------------------------------ actions

    def _say(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def _report_error(self, message: str) -> None:
        self._say(message)
        match = re.search(r"\bline (\d+)", message)
        if match:
            self.editor.go_to_line(int(match.group(1)))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.editor.code())
        self._say("Copied")

    def _suggested_name(self) -> str:
        if self._scope == "widget":
            return str(self._target or "widget")
        page = self._workspace.current_page
        return page.id or "page"

    def _save_as(self) -> None:
        if self._fmt == "c":
            extension, filters = "c", "C sources (*.c);;All files (*)"
        elif self._fmt == "qml":
            extension, filters = "qml", "QML files (*.qml);;All files (*)"
        else:
            extension, filters = "json", "JSON files (*.json);;All files (*)"
        path, _ = QFileDialog.getSaveFileName(self, "Save code as", f"{self._suggested_name()}.{extension}", filters)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(self.editor.code())
        except OSError as exc:
            self._say(f"Could not save: {exc}")
            return
        self._say(f"Saved {path}")

    # ------------------------------------------------------------ events

    def closeEvent(self, event):
        QSettings("EmbeddedDisplay", "Studio").setValue(SETTINGS_KEY, self.saveGeometry())
        event.ignore()
        self.hide()
