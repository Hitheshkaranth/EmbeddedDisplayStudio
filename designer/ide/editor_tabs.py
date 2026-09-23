"""designer/ide/editor_tabs.py -- the tabbed editors of the Code section.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W2. Public names,
signatures, signals and docstrings are the contract; W2 fills in the bodies
and may add private helpers and private classes. See docs/CODE_SECTION.md.

One tab per open file, each a designer.ui.code_editor.CodeEditor holding
the file's text in the language project_files.language_for gives. Pinned
tabs (the Design view) come first and cannot be closed.

Keys: QShortcuts with Qt.WidgetWithChildrenShortcut on this widget (so they
work anywhere inside the tabs and never reach the Designer tab). This widget
is the ONLY owner of these keys in the Code section -- two shortcuts with the
same key in overlapping contexts cancel each other in Qt:
    Ctrl+S          save()        -- current file, or the pinned tab's 'save'
    Ctrl+Shift+S    save_all()
    Ctrl+W          close_file(current_path()) on a file tab
    Ctrl+Z          undo()        -- current file's editor, or pinned 'undo'
    Ctrl+Y, Ctrl+Shift+Z   redo() -- current file's editor, or pinned 'redo'
A focused, editable CodeEditor takes Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z itself
first (it accepts the ShortcutOverride), so inside the Design tab's JSON
editor they undo text, and elsewhere in the Design tab they undo the design.
Undo history is per file and survives switching tabs; saving does not clear
it; reloading from disk does (CodeEditor.set_code clears it).

Dirty state: a file is dirty when its editor's text differs from the text
last read from or written to disk -- typing a change and typing it back
makes it clean again. The tab title is the file name, with " *" appended
while dirty; the tooltip is the path relative to root(). dirtyChanged fires
on every transition.

Changes on disk: a QFileSystemWatcher (on Windows a poller that holds no
handles -- see project_files._PollingWatcher) watches every open file (re-adding the
path after an atomic replace, which drops it from the watcher). When one
changes, file_changed_on_disk runs: a clean tab reloads silently (scroll and
cursor kept); a dirty tab shows a banner above its editor -- "<name> changed
on disk." [Reload] [Keep mine] -- and stays as it is until the user picks.
A change whose content equals the tab's saved text (our own save) is ignored.
A deleted file keeps its tab, marked dirty, so its text can be saved again.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabBar, QTabWidget, QVBoxLayout,
    QWidget,
)

from designer.ide import project_files
from designer.ui.code_editor import DARK_PALETTE, LIGHT_PALETTE, CodeEditor

try:
    from ui.python.shadcn import icon as _tabler_icon
except ImportError:                                     # icons are a nicety, not a need
    _tabler_icon = None

# A watched file that vanished is often being rewritten (delete + create, as
# some editors and tools save); look again after this long before calling it
# deleted.
_GONE_RECHECK_MS = 250

_NBSP, _LINE_SEP, _PARAGRAPH_SEP = chr(0xA0), chr(0x2028), chr(0x2029)


def _editor_view(text: str) -> str:
    # CodeEditor.code() is QTextDocument.toPlainText(), which turns NBSP into
    # a space and Unicode line/paragraph separators into "\n". Disk text is
    # compared in that form, or such a file would look changed forever.
    return text.replace(_NBSP, " ").replace(_LINE_SEP, "\n").replace(_PARAGRAPH_SEP, "\n")


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(a) == os.path.normcase(b)


def _under(path: str, folder: str) -> bool:
    folder = os.path.normcase(folder.rstrip("\\/"))
    return os.path.normcase(path).startswith(folder + os.sep)


class _Banner(QFrame):
    """"<name> changed on disk." [Reload] [Keep mine], above a dirty editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorBanner")
        self.label = QLabel(objectName="editorBannerText")
        self.reload_button = QPushButton("Reload", objectName="editorBannerButton")
        self.keep_button = QPushButton("Keep mine", objectName="editorBannerButton")
        for button in (self.reload_button, self.keep_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)   # the editor keeps the keyboard
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 6, 4)
        layout.setSpacing(6)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.reload_button)
        layout.addWidget(self.keep_button)
        self.hide()

    def set_name(self, name: str) -> None:
        self.label.setText(f"{name} changed on disk.")


class _FileTab:
    """What EditorTabs knows about one open file."""

    def __init__(self, path: str, editor: CodeEditor, page: QWidget, banner: _Banner):
        self.path = path
        self.editor = editor
        self.page = page
        self.banner = banner
        self.saved = ""             # editor-view text last read from / written to disk
        self.encoding = "utf-8"
        self.newline = "\n"
        self.missing = False        # deleted on disk: dirty until saved again
        self.dirty = False          # last state announced on dirtyChanged
        self.pending = None         # the TextFile the banner is about


class EditorTabs(QTabWidget):
    """Signals:
        currentFileChanged(str): the current tab's absolute path, '' for a
            pinned tab or no tab.
        dirtyChanged(str, bool): path, dirty.
        fileSaved(str): path, after a successful save.
        message(str): a sentence for the status line ("Saved main.c",
            "Cannot open logo.png: binary file", ...).
    """

    currentFileChanged = Signal(str)
    dirtyChanged = Signal(str, bool)
    fileSaved = Signal(str)
    message = Signal(str)

    # What _ask_unsaved may answer.
    SAVE, DISCARD, CANCEL = "save", "discard", "cancel"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorTabs")
        self.setTabsClosable(True)
        self.setDocumentMode(True)
        self._root = ""
        self._theme = "dark"
        self._files: dict[QWidget, _FileTab] = {}       # tab page -> file
        self._pinned: dict[QWidget, dict] = {}          # pinned widget -> handlers
        self._pinned_icons: dict[QWidget, str] = {}
        self._watcher = project_files._file_watcher(self)
        self._watcher.fileChanged.connect(self._on_watched_file_changed)
        self._gone: set[str] = set()
        self._gone_timer = QTimer(self)
        self._gone_timer.setSingleShot(True)
        self._gone_timer.setInterval(_GONE_RECHECK_MS)
        self._gone_timer.timeout.connect(self._recheck_gone)
        self.tabCloseRequested.connect(self._on_tab_close_requested)
        self.currentChanged.connect(self._on_current_changed)
        self._keys = []                                 # (QKeyCombination, slot)
        for keys, slot in (
            ("Ctrl+S", self._key_save),
            ("Ctrl+Shift+S", self._key_save_all),
            ("Ctrl+W", self._key_close),
            ("Ctrl+Z", self.undo),
            ("Ctrl+Y", self.redo),
            ("Ctrl+Shift+Z", self.redo),
        ):
            sequence = QKeySequence(keys)
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
            self._keys.append((sequence[0], slot))
        self.apply_theme("dark")

    # ---------------------------------------------------------- project

    def set_root(self, root: str) -> None:
        """The project folder: tooltips are relative to it and open_file
        refuses paths outside it (when a root is set). Open tabs stay."""
        self._root = os.path.realpath(root) if root else ""
        for rec in self._files.values():
            self._update_tab(rec)

    def root(self) -> str:
        return self._root

    # ---------------------------------------------------------- tabs

    def add_pinned(self, widget, title: str, icon_name: str = "",
                   handlers: dict | None = None) -> int:
        """Adds a non-closable tab after the existing pinned ones and returns
        its index. icon_name is a Tabler icon name (ui.python.shadcn.icon),
        ignored when icons are unavailable. handlers maps 'save', 'undo',
        'redo' to callables used by save()/undo()/redo() while that tab is
        current ('save' returns a bool); a missing handler makes the key a
        no-op there (save() returns False)."""
        index = self.insertTab(len(self._pinned), widget, title)
        self._pinned[widget] = dict(handlers or {})
        if icon_name:
            self._pinned_icons[widget] = icon_name
            self._set_pinned_icon(widget, icon_name)
        bar = self.tabBar()
        for side in (QTabBar.LeftSide, QTabBar.RightSide):
            button = bar.tabButton(index, side)
            if button is not None:
                bar.setTabButton(index, side, None)
                button.deleteLater()
        return index

    def open_file(self, path: str, line: int = 0):
        """Opens `path` (or switches to its tab when already open), focuses
        the editor and, with line >= 1, puts the cursor on that line.
        Returns the CodeEditor, or None when the file cannot be opened (the
        reason goes out on `message`; no tab is added)."""
        path = os.path.realpath(path)
        rec = self._find(path)
        if rec is None:
            name = os.path.basename(path)
            if self._root and not project_files.is_inside(self._root, path):
                self.message.emit(f"Cannot open {name}: it is outside the project folder")
                return None
            try:
                loaded = project_files.read_text(path)
            except project_files.FileReadError as exc:
                self.message.emit(str(exc) or f"Cannot open {name}")
                return None
            except OSError as exc:
                self.message.emit(f"Cannot open {name}: {exc.strerror or exc}")
                return None
            rec = self._new_tab(path, loaded)
        self.setCurrentWidget(rec.page)
        rec.editor.setFocus(Qt.OtherFocusReason)
        if line >= 1:
            rec.editor.go_to_line(line)
        return rec.editor

    def editor_for(self, path: str):
        """The CodeEditor of an open file, or None."""
        rec = self._find(path)
        return rec.editor if rec is not None else None

    def open_paths(self) -> list[str]:
        """Absolute paths of the open file tabs, in tab order."""
        return [rec.path for rec in self._records()]

    def current_path(self) -> str:
        """The current tab's path, '' for a pinned tab or none."""
        rec = self._files.get(self.currentWidget())
        return rec.path if rec is not None else ""

    def is_dirty(self, path: str) -> bool:
        rec = self._find(path)
        return rec is not None and self._dirty(rec)

    def dirty_paths(self) -> list[str]:
        return [rec.path for rec in self._records() if self._dirty(rec)]

    def save(self, path: str | None = None) -> bool:
        """Saves one file (the current one when None) with
        project_files.write_text, keeping its encoding and newline style.
        With None on a pinned tab, runs its 'save' handler. False, with a
        message, on failure or when there is nothing to save."""
        if path is None:
            current = self.currentWidget()
            if current in self._pinned:
                handler = self._pinned[current].get("save")
                return bool(handler()) if handler is not None else False
            rec = self._files.get(current)
        else:
            rec = self._find(path)
        if rec is None:
            self.message.emit("Nothing to save")
            return False
        name = os.path.basename(rec.path)
        text = rec.editor.code()
        # Not watched while it is replaced: on Windows the watcher's thread
        # opens watched files when their folder changes (our temp file is such
        # a change), and os.replace over an open file fails "Access is denied".
        # Re-adding afterwards also moves the watch onto the new file.
        self._unwatch(rec.path)
        try:
            project_files.write_text(rec.path, text, rec.encoding, rec.newline)
        except (OSError, ValueError) as exc:
            # ValueError: a character the file's encoding (latin-1) cannot hold.
            self._watch(rec.path)
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else exc
            self.message.emit(f"Cannot save {name}: {reason}")
            return False
        rec.saved = text
        rec.missing = False
        self._watch(rec.path)
        self._refresh_dirty(rec)
        self.message.emit(f"Saved {name}")
        self.fileSaved.emit(rec.path)
        return True

    def save_all(self) -> bool:
        """Saves every dirty file; True when all saved."""
        ok = True
        for rec in self._records():
            if self._dirty(rec):
                ok = self.save(rec.path) and ok
        return ok

    def close_file(self, path: str, force: bool = False) -> bool:
        """Closes a file tab. A dirty file asks _ask_unsaved(path) unless
        force: 'save' saves then closes (a failed save keeps the tab),
        'discard' closes, 'cancel' keeps it. True when the tab is gone."""
        if not path:
            return False
        rec = self._find(path)
        if rec is None:
            return True
        if not force and self._dirty(rec):
            self.setCurrentWidget(rec.page)
            answer = self._ask_unsaved(rec.path)
            if answer == self.SAVE:
                if not self.save(rec.path):
                    return False
            elif answer != self.DISCARD:
                return False
        self._remove(rec)
        return True

    def close_all(self, force: bool = False) -> bool:
        """close_file on every file tab; stops at the first cancel."""
        for rec in self._records():
            if not self.close_file(rec.path, force):
                return False
        return True

    def undo(self) -> None:
        """Undo in the current file's editor, or the pinned tab's 'undo'."""
        self._edit_action("undo")

    def redo(self) -> None:
        self._edit_action("redo")

    # ---------------------------------------------------------- disk events

    def file_changed_on_disk(self, path: str) -> None:
        """See the module docstring. Paths that are not open are ignored."""
        rec = self._find(path)
        if rec is None:
            return
        name = os.path.basename(rec.path)
        self._watch(rec.path)
        if not os.path.isfile(rec.path):
            if not rec.missing:
                rec.missing = True
                self._hide_banner(rec)
                self._refresh_dirty(rec)
                self.message.emit(f"{name} was deleted on disk")
            return
        try:
            loaded = project_files.read_text(rec.path)
        except (project_files.FileReadError, OSError) as exc:
            self.message.emit(f"Cannot reload {name}: {exc}")
            return
        disk = _editor_view(loaded.text)
        mine = rec.editor.code()
        if disk == rec.saved or disk == mine:
            # Our own save, or the disk caught up with the editor: nothing to
            # ask, and a banner about an older version is stale now.
            rec.saved, rec.encoding, rec.newline = disk, loaded.encoding, loaded.newline
            rec.missing = False
            self._hide_banner(rec)
            self._refresh_dirty(rec)
            return
        if mine == rec.saved:
            self._reload(rec, loaded)
            return
        rec.pending = loaded
        rec.banner.set_name(name)
        rec.banner.show()

    def has_banner(self, path: str) -> bool:
        """True while the "changed on disk" banner shows for that file."""
        rec = self._find(path)
        return rec is not None and not rec.banner.isHidden()

    def resolve_banner(self, path: str, reload: bool) -> None:
        """The banner's buttons: reload=True replaces the text with the disk's
        (clean again), False keeps the editor's text (stays dirty)."""
        rec = self._find(path)
        if rec is None:
            return
        if reload:
            try:
                loaded = project_files.read_text(rec.path)
            except (project_files.FileReadError, OSError) as exc:
                self.message.emit(f"Cannot reload {os.path.basename(rec.path)}: {exc}")
                return
            self._reload(rec, loaded)
            return
        if rec.pending is not None:
            # The version the user saw and declined becomes the baseline, so
            # the same content arriving again does not ask again.
            rec.saved = _editor_view(rec.pending.text)
            rec.encoding, rec.newline = rec.pending.encoding, rec.pending.newline
        self._hide_banner(rec)
        self._refresh_dirty(rec)

    def file_renamed(self, old: str, new: str) -> None:
        """Slot for ProjectTree.fileRenamed: retargets the tab of `old` (or of
        every open file under `old` when a folder was renamed)."""
        old, new = os.path.realpath(old), os.path.realpath(new)
        current = self.current_path()
        for rec in self._records():
            if _same_path(rec.path, old):
                target = new
            elif _under(rec.path, old):
                target = os.path.join(new, rec.path[len(old.rstrip("\\/")) + 1:])
            else:
                continue
            self._unwatch(rec.path)
            rec.path = target
            language = project_files.language_for(target)
            if language != rec.editor._language:
                rec.editor.set_language(language)
            rec.banner.set_name(os.path.basename(target))
            self._watch(target)
            self._update_tab(rec)
        if self.current_path() != current:
            self.currentFileChanged.emit(self.current_path())

    def file_deleted(self, path: str) -> None:
        """Slot for ProjectTree.fileDeleted: a clean tab of that file (or under
        that folder) closes; a dirty one stays, still dirty."""
        path = os.path.realpath(path)
        for rec in self._records():
            if not (_same_path(rec.path, path) or _under(rec.path, path)):
                continue
            if self._dirty(rec):
                self._unwatch(rec.path)
                rec.missing = True
                self._hide_banner(rec)
                self._refresh_dirty(rec)
            else:
                self._remove(rec)

    # ---------------------------------------------------------- agent context

    def selection_context(self) -> dict:
        """What the agent is told about the editor, {} on a pinned tab or none:
        {"path": abs path, "relative": path relative to root(),
         "language": ..., "cursor_line": 1-based,
         "start_line": 1-based, "end_line": 1-based, "text": selected text}
        With no selection, start_line == end_line == cursor_line and text ''."""
        rec = self._files.get(self.currentWidget())
        if rec is None:
            return {}
        editor = rec.editor
        cursor = editor.textCursor()
        document = editor.document()
        cursor_line = cursor.blockNumber() + 1
        start_line = end_line = cursor_line
        text = ""
        if cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            start_line = document.findBlock(start).blockNumber() + 1
            end_block = document.findBlock(end)
            end_line = end_block.blockNumber() + 1
            # A selection that stops at the very start of a line (whole lines
            # picked with Shift+Down) does not include that line.
            if end_line > start_line and end == end_block.position():
                end_line -= 1
            # Positions index toPlainText() one-to-one; selectedText() would
            # hand back U+2029 for the line breaks.
            text = editor.code()[start:end]
        return {
            "path": rec.path,
            "relative": self._relative(rec.path),
            "language": editor._language,
            "cursor_line": cursor_line,
            "start_line": start_line,
            "end_line": end_line,
            "text": text,
        }

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light': every editor, the banners, the tab bar."""
        self._theme = "light" if theme == "light" else "dark"
        p = LIGHT_PALETTE if self._theme == "light" else DARK_PALETTE
        warn = "#b45309" if self._theme == "light" else "#e3b341"
        self.setStyleSheet(f"""
            QTabWidget#editorTabs::pane {{ border: none; background: {p['background']}; }}
            QTabWidget#editorTabs > QTabBar {{ background: {p['bar']}; }}
            QTabWidget#editorTabs > QTabBar::tab {{
                background: {p['bar']}; color: {p['muted']}; border: none;
                border-right: 1px solid {p['border']}; border-bottom: 1px solid {p['border']};
                padding: 5px 10px; font-size: 12px;
            }}
            QTabWidget#editorTabs > QTabBar::tab:selected {{
                background: {p['background']}; color: {p['bar_text']};
                border-bottom: 1px solid {p['background']};
            }}
            QTabWidget#editorTabs > QTabBar::tab:hover:!selected {{ color: {p['bar_text']}; }}
            QFrame#editorBanner {{ background: {p['bar']}; border-bottom: 1px solid {warn}; }}
            QLabel#editorBannerText {{ background: transparent; color: {warn}; font-size: 12px; }}
            QPushButton#editorBannerButton {{
                background: transparent; color: {p['bar_text']}; border: 1px solid {p['border']};
                border-radius: 4px; padding: 2px 10px; font-size: 12px;
            }}
            QPushButton#editorBannerButton:hover {{ background: {p['current_line']}; }}
        """)
        for rec in self._files.values():
            rec.editor.apply_theme(self._theme)
        for widget, name in self._pinned_icons.items():
            self._set_pinned_icon(widget, name)

    # ---------------------------------------------------------- hooks

    def _ask_unsaved(self, path: str) -> str:
        """Asks Save / Discard / Cancel for a dirty file (a QMessageBox);
        returns SAVE, DISCARD or CANCEL. Tests replace this method."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save the changes to {os.path.basename(path)}?")
        box.setInformativeText("Your changes are lost if you don't save them.")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        box.setEscapeButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.standardButton(box.clickedButton())
        box.deleteLater()
        if clicked == QMessageBox.Save:
            return self.SAVE
        if clicked == QMessageBox.Discard:
            return self.DISCARD
        return self.CANCEL

    # ---------------------------------------------------------- Qt hooks

    def event(self, event) -> bool:
        # Claim our keys when they are pressed inside this widget, before the
        # application's shortcut map sees them. The map matches QShortcuts
        # against the *active* window's focus widget, not against the widget
        # the key was sent to: until the window system activates this window
        # (just shown, or embedded in one that never activates) another
        # window's shortcut -- another EditorTabs' Ctrl+S -- would take the
        # key. A child that wants the key claims it first (CodeEditor does for
        # undo/redo), because the override reaches it before bubbling here.
        # The claimed key then arrives as a key press (keyPressEvent below);
        # the QShortcuts still serve focus this event never passes through.
        if event.type() == QEvent.ShortcutOverride and self._key_slot(event) is not None:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        slot = self._key_slot(event)
        if slot is None:
            super().keyPressEvent(event)
            return
        event.accept()
        slot()

    # ---------------------------------------------------------- private

    def _key_slot(self, event):
        mods = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier
                                    | Qt.MetaModifier)
        for combo, slot in self._keys:
            if event.key() == combo.key() and mods == combo.keyboardModifiers():
                return slot
        return None

    def _records(self) -> list[_FileTab]:
        """The open files in tab order (a snapshot: callers may close tabs)."""
        pages = (self.widget(i) for i in range(self.count()))
        return [self._files[page] for page in pages if page in self._files]

    def _find(self, path: str) -> _FileTab | None:
        if not path:
            return None
        wanted = os.path.normcase(os.path.realpath(path))
        for rec in self._files.values():
            if os.path.normcase(rec.path) == wanted:
                return rec
        return None

    def _relative(self, path: str) -> str:
        if not self._root:
            return path.replace(os.sep, "/")
        return project_files.relative_path(self._root, path)

    def _new_tab(self, path: str, loaded) -> _FileTab:
        editor = CodeEditor()
        editor.set_language(project_files.language_for(path))
        editor.apply_theme(self._theme)
        editor.set_code(loaded.text, keep_scroll=False)
        page = QWidget()
        page.setObjectName("editorPage")
        banner = _Banner(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(banner)
        layout.addWidget(editor, 1)
        rec = _FileTab(path, editor, page, banner)
        rec.saved = editor.code()
        rec.encoding, rec.newline = loaded.encoding, loaded.newline
        banner.reload_button.clicked.connect(lambda: self.resolve_banner(rec.path, True))
        banner.keep_button.clicked.connect(lambda: self.resolve_banner(rec.path, False))
        editor.codeEdited.connect(lambda: self._refresh_dirty(rec))
        # Registered before addTab: adding the first tab makes it current, and
        # currentFileChanged must already see its path.
        self._files[page] = rec
        self.addTab(page, "")
        self._update_tab(rec)
        self._watch(path)
        return rec

    def _remove(self, rec: _FileTab) -> None:
        self._unwatch(rec.path)
        del self._files[rec.page]
        index = self.indexOf(rec.page)
        if index >= 0:
            self.removeTab(index)
        rec.page.deleteLater()

    def _dirty(self, rec: _FileTab) -> bool:
        return rec.missing or rec.editor.code() != rec.saved

    def _refresh_dirty(self, rec: _FileTab) -> None:
        dirty = self._dirty(rec)
        if dirty == rec.dirty:
            return
        rec.dirty = dirty
        self._update_tab(rec)
        self.dirtyChanged.emit(rec.path, dirty)

    def _update_tab(self, rec: _FileTab) -> None:
        index = self.indexOf(rec.page)
        if index < 0:
            return
        # A bare '&' would turn into a mnemonic underline in the tab title.
        title = os.path.basename(rec.path).replace("&", "&&")
        self.setTabText(index, title + (" *" if rec.dirty else ""))
        self.setTabToolTip(index, self._relative(rec.path))

    def _reload(self, rec: _FileTab, loaded) -> None:
        rec.editor.set_code(loaded.text, keep_scroll=True)
        rec.saved = rec.editor.code()
        rec.encoding, rec.newline = loaded.encoding, loaded.newline
        rec.missing = False
        self._hide_banner(rec)
        self._refresh_dirty(rec)

    def _hide_banner(self, rec: _FileTab) -> None:
        rec.pending = None
        rec.banner.hide()

    def _watch(self, path: str, fresh: bool = False) -> None:
        # An atomic replace (ours or anyone's) leaves the watch on the old,
        # unlinked file; `fresh` re-adds it so it follows the new one.
        if fresh and path in self._watcher.files():
            self._watcher.removePath(path)
        if os.path.isfile(path) and path not in self._watcher.files():
            self._watcher.addPath(path)

    def _unwatch(self, path: str) -> None:
        if path in self._watcher.files():
            self._watcher.removePath(path)

    def _on_watched_file_changed(self, path: str) -> None:
        if os.path.isfile(path):
            self._watch(path, fresh=True)
            self.file_changed_on_disk(path)
        else:
            self._gone.add(path)
            self._gone_timer.start()

    def _recheck_gone(self) -> None:
        gone, self._gone = self._gone, set()
        for path in gone:
            self.file_changed_on_disk(path)

    def _on_current_changed(self, _index: int) -> None:
        self.currentFileChanged.emit(self.current_path())

    def _edit_action(self, name: str) -> None:
        current = self.currentWidget()
        if current in self._pinned:
            handler = self._pinned[current].get(name)
            if handler is not None:
                handler()
            return
        rec = self._files.get(current)
        if rec is not None:
            getattr(rec.editor, name)()

    def _key_save(self) -> None:
        self.save()

    def _key_save_all(self) -> None:
        self.save_all()

    def _key_close(self) -> None:
        path = self.current_path()
        if path:
            self.close_file(path)

    def _on_tab_close_requested(self, index: int) -> None:
        rec = self._files.get(self.widget(index))
        if rec is not None:
            self.close_file(rec.path)

    def _set_pinned_icon(self, widget: QWidget, name: str) -> None:
        if _tabler_icon is None:
            return
        index = self.indexOf(widget)
        if index < 0:
            return
        palette = LIGHT_PALETTE if self._theme == "light" else DARK_PALETTE
        try:
            self.setTabIcon(index, _tabler_icon(name, 16, palette["text"]))
        except Exception:                               # an unknown icon name is not fatal
            pass
