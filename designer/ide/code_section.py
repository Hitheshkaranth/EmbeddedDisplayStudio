"""designer/ide/code_section.py -- the Studio's Code tab, put together.

Integration module of the Code IDE (docs/CODE_SECTION.md): the project tree,
the widget picker, the whole-design outline and the Backend (tags) pane on the
left, the editors in the middle -- the design view
(designer.ui.code_window.CodeWindow) pinned first as "Design" -- and the
coding agent on the right. Owns the wiring between them and nothing else;
each piece is usable, and tested, on its own.

The left panes and the agent read the design through one DesignIndex,
rebuilt here whenever the Designer reports a change.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMessageBox, QSizePolicy, QSplitter, QTabWidget, QToolBar, QVBoxLayout,
    QWidget,
)

from designer.ide.agent_backend import OpencodeBackend
from designer.ide.agent_context import design_brief, quick_actions
from designer.ide.agent_panel import AgentPanel
from designer.ide.backend_scaffold import BACKEND_DIR, write_scaffold
from designer.ide.design_index import DesignIndex
from designer.ide.editor_tabs import EditorTabs
from designer.ide.project_files import ProjectTree
from designer.ide.tag_panel import TagPanel
from designer.ide.tag_source import EngineTagSource, SimulatedTagSource, ranges_from_index
from designer.ide.widget_outline import WidgetOutline
from designer.ide.widget_picker import WidgetPicker
from designer.ui.code_window import CodeWindow

try:
    from ui.python.shadcn import color, icon
except ImportError:
    from PySide6.QtGui import QIcon

    def icon(_name, _size=16, _color=None): return QIcon()

    def color(name, theme="dark"):
        return {"dark": {"border": "#27272a", "mutedForeground": "#a1a1aa", "background": "#09090b"},
                "light": {"border": "#e4e4e7", "mutedForeground": "#71717a", "background": "#ffffff"}}[theme][name]

SETTINGS_SPLITTER_KEY = "codeSection/splitter"
SETTINGS_ROOT_KEY = "codeSection/root"
FILES_TAB, WIDGETS_TAB, OUTLINE_TAB, BACKEND_TAB = 0, 1, 2, 3


class CodeSection(QWidget):
    """Signals:
        message(str): status-line text from any of the pieces.
    """

    message = Signal(str)

    def __init__(self, workspace, backend=None, parent=None):
        super().__init__(parent)
        self.setObjectName("codeSection")
        self.workspace = workspace
        self._theme = "dark"
        # A folder the user opened by hand wins over the design's bundle
        # folder until they open another design.
        self._manual_root = ""
        self._followed_bundle = None
        self._agent_started = False
        self._index = DesignIndex.build(None)
        # Live values: the Studio's TagEngine while it is receiving, else
        # the simulator, so the Backend pane always shows moving numbers.
        self._engine_provider = None
        self._engine_source = None
        self.simulator = SimulatedTagSource(parent=self)

        self.design = CodeWindow(workspace)
        self.design.setWindowFlags(Qt.Widget)
        # Picking a widget should show its code *and* what it looks like.
        self.design.set_preview_visible(True)

        self.tree = ProjectTree()
        self.picker = WidgetPicker(workspace)
        self.outline = WidgetOutline(workspace)
        self.backend_pane = TagPanel()
        self.tabs = EditorTabs()
        self.tabs.add_pinned(self.design, "Design", "components", handlers={
            "save": workspace.save,
            "undo": workspace.undo_stack.undo,
            "redo": workspace.undo_stack.redo,
        })
        self.agent = AgentPanel(backend if backend is not None else OpencodeBackend())
        self.agent.set_context_provider(self.tabs.selection_context)
        self.agent.set_design_provider(self._design_brief)

        self._build_ui()
        self._connect()
        self._sync_root()
        self.rebuild_index()

    # ---------------------------------------------------------------- API

    def index(self) -> DesignIndex:
        """The DesignIndex the outline, Backend pane and agent read."""
        return self._index

    def rebuild_index(self) -> None:
        """Re-reads the design into the index and hands it to every consumer.
        Line numbers come from project.edsui on disk: that is the text the
        editor opens when the outline asks for a widget's source."""
        ws = self.workspace
        text = None
        path = getattr(ws, "file_path", "") or ""
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8-sig") as f:
                    text = f.read()
            except (OSError, UnicodeDecodeError):
                text = None
        declared = getattr(getattr(ws, "bindings", None), "tags", None) or ()
        self._index = DesignIndex.build(getattr(ws, "project", None), getattr(ws, "registry", None),
                                        declared, text)
        self.outline.set_index(self._index)
        self.backend_pane.set_index(self._index)
        self.simulator.set_tags([entry.tag for entry in self._index.tags()])
        for tag, (lo, hi) in ranges_from_index(self._index).items():
            self.simulator.set_range(tag, lo, hi)
        self._update_quick_actions()

    def set_engine_provider(self, provider) -> None:
        """A function returning the Studio's TagEngine or None (it is built
        lazily, on the first preview). Asked each time the section is shown."""
        self._engine_provider = provider
        self._pick_source()

    def tag_source(self):
        """The TagSource the Backend pane shows now."""
        return self.backend_pane.source()

    def generate_backend(self, overwrite: bool | None = None) -> dict:
        """What "Generate backend..." does: writes backend/ into the project
        folder from the index and opens backend.py. With overwrite None the
        user is asked when files already exist."""
        root = self.root()
        if not root or not os.path.isdir(root):
            self.message.emit("Open a project folder before generating a backend")
            return {"written": [], "skipped": []}
        result = write_scaffold(root, self._index, overwrite=bool(overwrite))
        if result["skipped"] and overwrite is None:
            names = "\n".join(os.path.basename(p) for p in result["skipped"])
            answer = QMessageBox.question(
                self, "Backend files exist",
                f"These files in {BACKEND_DIR}/ already exist and were kept:\n\n{names}\n\n"
                "Overwrite them with freshly generated ones? Your edits in them will be lost.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer == QMessageBox.Yes:
                again = write_scaffold(root, self._index, overwrite=True)
                result = {"written": result["written"] + again["written"], "skipped": []}
        self.tree.refresh()
        for path in result["written"]:
            self.tabs.file_changed_on_disk(path)
        self.open_file(os.path.join(root, BACKEND_DIR, "backend.py"))
        self.message.emit(f"Backend: wrote {len(result['written'])} file(s), kept {len(result['skipped'])}")
        return result

    def root(self) -> str:
        return self.tree.root()

    def set_root(self, path: str) -> None:
        """Shows `path` in the tree, scopes the editors to it and, once the
        section has been shown, points the agent at it."""
        path = os.path.abspath(path) if path else ""
        self.tree.set_root(path)
        self.tabs.set_root(path)
        self._root_label.setText(path or "No project folder")
        self._root_label.setToolTip(path)
        if self._agent_started:
            self.agent.set_directory(path)

    def open_folder(self, path: str) -> None:
        """What Open folder... does with the chosen folder."""
        self._manual_root = os.path.abspath(path)
        QSettings("MIL-HMI", "Deployer").setValue(SETTINGS_ROOT_KEY, self._manual_root)
        self.set_root(self._manual_root)

    def show_design(self) -> None:
        """Switches to the pinned Design tab (the Designer's Code action)."""
        self.tabs.setCurrentWidget(self.design)

    def open_file(self, path: str, line: int = 0):
        editor = self.tabs.open_file(path, line)
        if editor is not None:
            self.tree.reveal(path)
        return editor

    def refresh(self) -> None:
        self.design.refresh()

    def apply_theme(self, theme: str) -> None:
        self._theme = theme if theme in ("dark", "light") else "dark"
        for part in (self.design, self.tree, self.picker, self.outline, self.backend_pane, self.tabs, self.agent):
            part.apply_theme(self._theme)
        border = color("border", self._theme)
        muted = color("mutedForeground", self._theme)
        self.setStyleSheet(
            f"QSplitter#codeSectionSplitter::handle {{ background: {border}; }}"
            f"QLabel#codeSectionRoot {{ color: {muted}; padding: 0 8px; }}")

    def confirm_close(self) -> bool:
        """Before the Studio closes: unsaved editors ask Save all / Discard /
        Cancel. True when closing may go ahead."""
        dirty = self.tabs.dirty_paths()
        if not dirty:
            return True
        names = "\n".join(os.path.basename(p) for p in dirty[:10])
        answer = QMessageBox.question(
            self, "Unsaved files", f"Save changes to these files?\n\n{names}",
            QMessageBox.SaveAll | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.SaveAll)
        if answer == QMessageBox.Cancel:
            return False
        return answer == QMessageBox.Discard or self.tabs.save_all()

    def shutdown(self) -> None:
        """Stops the agent (and the opencode server it started). The Studio
        calls this on exit; unsaved editors are the caller's to ask about."""
        self.agent.backend().stop()
        self.simulator.stop()
        if self._engine_source is not None:
            self._engine_source.stop()

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = self._bar = QToolBar("Code section actions")
        bar.setObjectName("codeSectionToolbar")
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        bar.setIconSize(QSize(16, 16))
        bar.setFixedHeight(36)

        def action(text, slot, icon_name, tip, checkable=False):
            item = bar.addAction(icon(icon_name), text)
            item.setToolTip(tip)
            item.setCheckable(checkable)
            (item.toggled if checkable else item.triggered).connect(slot)
            return item

        action("Open folder...", self._choose_folder, "folder-open", "Show another folder in the Files pane")
        self._root_label = QLabel()
        self._root_label.setObjectName("codeSectionRoot")
        self._root_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bar.addWidget(self._root_label)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        # Tool buttons only: the keys themselves belong to EditorTabs.
        self.undo_action = action("Undo", self.tabs.undo, "arrow-back-up", "Undo (Ctrl+Z)")
        self.redo_action = action("Redo", self.tabs.redo, "arrow-forward-up", "Redo (Ctrl+Y)")
        self.save_action = action("Save", lambda: self.tabs.save(), "device-floppy", "Save (Ctrl+S)")
        self.save_all_action = action("Save all", self.tabs.save_all, "device-floppy", "Save all (Ctrl+Shift+S)")
        bar.addSeparator()
        self.files_action = action("Files", self._toggle_left, "list-tree", "Show the Files and Widgets pane", True)
        self.agent_action = action("Agent", self._toggle_agent, "sparkles", "Show the coding agent", True)
        layout.addWidget(bar)

        self.left = QTabWidget()
        self.left.setObjectName("codeSectionNavigator")
        self.left.addTab(self.tree, "Files")
        self.left.addTab(self.picker, "Widgets")
        self.left.addTab(self.outline, "Outline")
        self.left.addTab(self.backend_pane, "Backend")
        self.left.setTabToolTip(OUTLINE_TAB, "Every widget of the design, what it is wired to, and its issues")
        self.left.setTabToolTip(BACKEND_TAB, "The tags the design reads and writes, with live values")
        self.left.setMinimumWidth(180)
        self.agent.setMinimumWidth(260)

        split = self._splitter = QSplitter(Qt.Horizontal)
        split.setObjectName("codeSectionSplitter")
        split.setChildrenCollapsible(False)
        split.addWidget(self.left)
        split.addWidget(self.tabs)
        split.addWidget(self.agent)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([380, 660, 360])
        state = QSettings("MIL-HMI", "Deployer").value(SETTINGS_SPLITTER_KEY)
        if state is not None:
            split.restoreState(state)
        split.splitterMoved.connect(
            lambda *_: QSettings("MIL-HMI", "Deployer").setValue(SETTINGS_SPLITTER_KEY, split.saveState()))
        layout.addWidget(split, 1)
        self.files_action.setChecked(True)
        self.agent_action.setChecked(True)

    def _connect(self) -> None:
        ws = self.workspace
        self.tree.fileActivated.connect(self.open_file)
        self.tree.fileRenamed.connect(self.tabs.file_renamed)
        self.tree.fileDeleted.connect(self.tabs.file_deleted)
        self.picker.widgetPicked.connect(lambda _id: self.show_design())
        self.outline.widgetPicked.connect(lambda _id: self.show_design())
        self.outline.sourceRequested.connect(self._open_widget_source)
        self.backend_pane.tagActivated.connect(self._tag_activated)
        self.backend_pane.scaffoldRequested.connect(lambda: self.generate_backend())
        self.backend_pane.message.connect(self.message)
        ws.scene.selectionIdsChanged.connect(lambda _ids: self._update_quick_actions())
        ws.pageChanged.connect(lambda _i: self._update_quick_actions())
        self.agent.openFileRequested.connect(self.open_file)
        self.agent.fileEdited.connect(self._agent_edited)
        self.tabs.message.connect(self.message)
        self.tabs.fileSaved.connect(self._file_saved)
        self.tabs.currentChanged.connect(self._tab_changed)
        ws.designChanged.connect(self._sync_root)
        ws.designChanged.connect(self.rebuild_index)
        self._tab_changed(self.tabs.currentIndex())

    # ---------------------------------------------------------------- slots

    def _sync_root(self) -> None:
        """Follows the design's bundle folder: a newly opened design moves the
        tree there even after a manual Open folder."""
        bundle = getattr(self.workspace, "bundle_dir", "") or ""
        if bundle == self._followed_bundle:
            return
        first = self._followed_bundle is None
        self._followed_bundle = bundle
        if bundle:
            self._manual_root = ""
            self.set_root(bundle)
        elif first:
            # No design yet: the folder opened last time, if it still exists.
            saved = QSettings("MIL-HMI", "Deployer").value(SETTINGS_ROOT_KEY, "") or ""
            self._manual_root = saved if saved and os.path.isdir(saved) else ""
            self.set_root(self._manual_root)

    def _selected_id(self) -> str:
        widget = self.workspace.selected_widget()
        return widget.id if widget is not None else ""

    def _design_brief(self) -> str:
        return design_brief(self._index, self._selected_id())

    def _update_quick_actions(self) -> None:
        self.agent.set_quick_actions(quick_actions(self._index, self._selected_id()))

    def _open_widget_source(self, widget_id: str, line: int) -> None:
        path = getattr(self.workspace, "file_path", "") or ""
        if not path or not os.path.isfile(path):
            self.message.emit("Save the design first: project.edsui is not on disk yet")
            return
        if not self.workspace.undo_stack.isClean():
            self.message.emit("project.edsui on disk is older than the Designer's copy; save to see your changes")
        self.open_file(path, line)

    def _tag_activated(self, tag: str) -> None:
        # Filters the Outline without leaving the Backend pane: the "Used by"
        # column already names the widgets, the outline is one click away.
        self.outline.show_tag(tag)
        users = self._index.widgets_using(tag)
        self.message.emit(f"{tag}: used by {', '.join(users) if users else 'no widget'}")

    def _pick_source(self) -> None:
        engine = self._engine_provider() if self._engine_provider is not None else None
        if engine is not None and (self._engine_source is None or self._engine_source.engine() is not engine):
            if self._engine_source is not None:
                self._engine_source.stop()
                self._engine_source.onlineChanged.disconnect(self._engine_online)
            self._engine_source = EngineTagSource(engine, self)
            self._engine_source.onlineChanged.connect(self._engine_online)
            self._engine_source.start()
        live = self._engine_source is not None and self._engine_source.is_online()
        wanted = self._engine_source if live else self.simulator
        if live:
            self.simulator.stop()
        elif self.isVisible():
            self.simulator.start()
        if self.backend_pane.source() is not wanted:
            self.backend_pane.set_source(wanted)

    def _engine_online(self, _online: bool) -> None:
        self._pick_source()

    def _agent_edited(self, path: str) -> None:
        self.tabs.file_changed_on_disk(path)
        self.tree.refresh()
        # The agent edited the design the Designer holds: say so rather than
        # silently diverge (reloading would drop the Designer's undo history).
        design = getattr(self.workspace, "file_path", "")
        if design and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(design)):
            self.message.emit("The agent changed project.edsui on disk; reopen it in the Designer to see the change")

    def _file_saved(self, path: str) -> None:
        self.message.emit(f"Saved {os.path.basename(path)}")

    def _tab_changed(self, _index: int) -> None:
        # The navigator shows what the editor is about: widgets beside the
        # design, the files beside a file.
        # The Outline and Backend panes are about the design whatever is
        # open, so they are left alone.
        if self.left.currentIndex() in (OUTLINE_TAB, BACKEND_TAB):
            return
        on_design = self.tabs.currentWidget() is self.design
        self.left.setCurrentIndex(WIDGETS_TAB if on_design else FILES_TAB)

    def _choose_folder(self) -> None:
        start = self.root() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "Open folder", start)
        if path:
            self.open_folder(path)

    def _toggle_left(self, on: bool) -> None:
        self.left.setVisible(on)

    def _toggle_agent(self, on: bool) -> None:
        self.agent.setVisible(on)
        if on and self.isVisible():
            self._start_agent()

    def _start_agent(self) -> None:
        # opencode starts on first sight of the section, not at Studio launch:
        # most sessions never open the Code tab.
        if not self._agent_started:
            self._agent_started = True
            self.agent.set_directory(self.root())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.agent.isVisible():
            self._start_agent()
        self._pick_source()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        # Nothing on screen reads the simulated values.
        self.simulator.stop()
