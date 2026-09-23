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

Changes on disk: a QFileSystemWatcher watches every open file (re-adding the
path after an atomic replace, which drops it from the watcher). When one
changes, file_changed_on_disk runs: a clean tab reloads silently (scroll and
cursor kept); a dirty tab shows a banner above its editor -- "<name> changed
on disk." [Reload] [Keep mine] -- and stays as it is until the user picks.
A change whose content equals the tab's saved text (our own save) is ignored.
A deleted file keeps its tab, marked dirty, so its text can be saved again.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QTabWidget


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
        raise NotImplementedError

    # ---------------------------------------------------------- project

    def set_root(self, root: str) -> None:
        """The project folder: tooltips are relative to it and open_file
        refuses paths outside it (when a root is set). Open tabs stay."""
        raise NotImplementedError

    def root(self) -> str:
        raise NotImplementedError

    # ---------------------------------------------------------- tabs

    def add_pinned(self, widget, title: str, icon_name: str = "",
                   handlers: dict | None = None) -> int:
        """Adds a non-closable tab after the existing pinned ones and returns
        its index. icon_name is a Tabler icon name (ui.python.shadcn.icon),
        ignored when icons are unavailable. handlers maps 'save', 'undo',
        'redo' to callables used by save()/undo()/redo() while that tab is
        current ('save' returns a bool); a missing handler makes the key a
        no-op there (save() returns False)."""
        raise NotImplementedError

    def open_file(self, path: str, line: int = 0):
        """Opens `path` (or switches to its tab when already open), focuses
        the editor and, with line >= 1, puts the cursor on that line.
        Returns the CodeEditor, or None when the file cannot be opened (the
        reason goes out on `message`; no tab is added)."""
        raise NotImplementedError

    def editor_for(self, path: str):
        """The CodeEditor of an open file, or None."""
        raise NotImplementedError

    def open_paths(self) -> list[str]:
        """Absolute paths of the open file tabs, in tab order."""
        raise NotImplementedError

    def current_path(self) -> str:
        """The current tab's path, '' for a pinned tab or none."""
        raise NotImplementedError

    def is_dirty(self, path: str) -> bool:
        raise NotImplementedError

    def dirty_paths(self) -> list[str]:
        raise NotImplementedError

    def save(self, path: str | None = None) -> bool:
        """Saves one file (the current one when None) with
        project_files.write_text, keeping its encoding and newline style.
        With None on a pinned tab, runs its 'save' handler. False, with a
        message, on failure or when there is nothing to save."""
        raise NotImplementedError

    def save_all(self) -> bool:
        """Saves every dirty file; True when all saved."""
        raise NotImplementedError

    def close_file(self, path: str, force: bool = False) -> bool:
        """Closes a file tab. A dirty file asks _ask_unsaved(path) unless
        force: 'save' saves then closes (a failed save keeps the tab),
        'discard' closes, 'cancel' keeps it. True when the tab is gone."""
        raise NotImplementedError

    def close_all(self, force: bool = False) -> bool:
        """close_file on every file tab; stops at the first cancel."""
        raise NotImplementedError

    def undo(self) -> None:
        """Undo in the current file's editor, or the pinned tab's 'undo'."""
        raise NotImplementedError

    def redo(self) -> None:
        raise NotImplementedError

    # ---------------------------------------------------------- disk events

    def file_changed_on_disk(self, path: str) -> None:
        """See the module docstring. Paths that are not open are ignored."""
        raise NotImplementedError

    def has_banner(self, path: str) -> bool:
        """True while the "changed on disk" banner shows for that file."""
        raise NotImplementedError

    def resolve_banner(self, path: str, reload: bool) -> None:
        """The banner's buttons: reload=True replaces the text with the disk's
        (clean again), False keeps the editor's text (stays dirty)."""
        raise NotImplementedError

    def file_renamed(self, old: str, new: str) -> None:
        """Slot for ProjectTree.fileRenamed: retargets the tab of `old` (or of
        every open file under `old` when a folder was renamed)."""
        raise NotImplementedError

    def file_deleted(self, path: str) -> None:
        """Slot for ProjectTree.fileDeleted: a clean tab of that file (or under
        that folder) closes; a dirty one stays, still dirty."""
        raise NotImplementedError

    # ---------------------------------------------------------- agent context

    def selection_context(self) -> dict:
        """What the agent is told about the editor, {} on a pinned tab or none:
        {"path": abs path, "relative": path relative to root(),
         "language": ..., "cursor_line": 1-based,
         "start_line": 1-based, "end_line": 1-based, "text": selected text}
        With no selection, start_line == end_line == cursor_line and text ''."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light': every editor, the banners, the tab bar."""
        raise NotImplementedError

    # ---------------------------------------------------------- hooks

    def _ask_unsaved(self, path: str) -> str:
        """Asks Save / Discard / Cancel for a dirty file (a QMessageBox);
        returns SAVE, DISCARD or CANCEL. Tests replace this method."""
        raise NotImplementedError
