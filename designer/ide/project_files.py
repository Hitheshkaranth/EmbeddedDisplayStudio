"""designer/ide/project_files.py -- the project folder: file helpers and the tree.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W1. Public names,
signatures, signals and docstrings are the contract; W1 fills in the bodies
and may add private helpers and private classes. See docs/CODE_SECTION.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

# Directory names never shown in the tree (anywhere in the hierarchy).
IGNORED_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".opencode", ".idea", ".vscode",
    "build", "dist", "out",
})
# Larger files are not opened in an editor.
MAX_TEXT_BYTES = 2 * 1024 * 1024
# Bytes inspected for NULs when deciding a file is binary.
BINARY_SNIFF_BYTES = 8192
# Extension (lower case, with the dot) -> CodeEditor language.
EXTENSION_LANGUAGES = {
    ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c", ".cxx": "c",
    ".py": "python", ".pyw": "python",
    ".qml": "qml", ".js": "qml",
    ".json": "json", ".edsui": "json",
}


class FileReadError(Exception):
    """A file that cannot be opened as text: missing, binary, too large or
    unreadable. The message is a sentence fit for the status line."""


@dataclass
class TextFile:
    """What read_text found.

    text:     the content with every line ending normalised to "\\n".
    encoding: 'utf-8', 'utf-8-sig' (a BOM was present) or 'latin-1' (fallback).
    newline:  the file's line ending, "\\r\\n" when the first line ending in
              the file is CRLF, else "\\n" (also for a file with no newline).
    """
    text: str
    encoding: str = "utf-8"
    newline: str = "\n"


def language_for(path: str) -> str:
    """The CodeEditor language for a path, from EXTENSION_LANGUAGES
    (case-insensitive extension); 'plain' for anything else."""
    raise NotImplementedError


def is_binary(path: str) -> bool:
    """True when the first BINARY_SNIFF_BYTES bytes contain a NUL byte."""
    raise NotImplementedError


def read_text(path: str) -> TextFile:
    """Reads a text file for editing. Raises FileReadError when the path is
    not a file, is larger than MAX_TEXT_BYTES, is binary (is_binary), or
    cannot be read. Tries UTF-8 (detecting a BOM -> 'utf-8-sig'), falls back
    to latin-1."""
    raise NotImplementedError


def write_text(path: str, text: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Writes atomically: to a temporary file in the same directory, then
    os.replace over path. text uses "\\n"; each is written as `newline`.
    Parent directories must exist. Raises OSError on failure, leaving the
    original file untouched and no temporary file behind."""
    raise NotImplementedError


def is_inside(root: str, path: str) -> bool:
    """True when path (after os.path.realpath) is root or lies below it.
    Guards every path that reaches the file system from an agent or a name
    typed by the user."""
    raise NotImplementedError


def relative_path(root: str, path: str) -> str:
    """path relative to root with '/' separators ('.' for root itself);
    the absolute path, '/'-separated, when it is not inside root."""
    raise NotImplementedError


def validate_name(name: str) -> str:
    """A new file/folder name typed by the user, stripped. Raises ValueError
    (with a readable message) when it is empty, '.' or '..', or contains
    '/', '\\\\', ':' or a character in '<>\"|?*' or a control character."""
    raise NotImplementedError


class ProjectTree(QWidget):
    """The project folder as a tree, with a filter field on top.

    The model is built synchronously from os.scandir (not QFileSystemModel,
    whose asynchronous loading makes reveal() and tests unreliable): after
    set_root / refresh / new_file / new_folder / rename / delete return,
    visible_paths() already reflects the file system. Folders come first,
    then files, each case-insensitively by name; IGNORED_DIRS are hidden.
    A QFileSystemWatcher on the root and the expanded folders calls refresh()
    (debounced, ~200 ms) when something changes outside the Studio; refresh
    keeps the expanded folders and the selection.

    Typing in the filter shows the files whose name contains the text
    (case-insensitive) together with the folders leading to them, all
    expanded; clearing it restores the previous expansion.

    Activating a file (double-click, or Enter on the view) emits
    fileActivated(abs path). Folders expand/collapse instead.

    The context menu offers New file..., New folder..., Rename..., Delete,
    Copy path and Reveal in file manager; the dialogs are private and the
    work is done by the public methods below, which tests call directly.

    Attributes tests rely on: `view` (the QTreeView), `filter_edit`
    (the QLineEdit), `empty_label` (the QLabel shown when there is no root).

    Signals:
        fileActivated(str): a file was opened from the tree.
        fileRenamed(str, str): old abs path, new abs path (file or folder).
        fileDeleted(str): abs path of the deleted file or folder.
        rootChanged(str): the new root ('' for none).
    """

    fileActivated = Signal(str)
    fileRenamed = Signal(str, str)
    fileDeleted = Signal(str)
    rootChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def set_root(self, path: str) -> None:
        """Shows the folder `path` (made absolute); '' or a missing folder
        shows `empty_label` ("No project folder") instead of the view. The
        root's direct children are listed, folders collapsed. Emits
        rootChanged when the root actually changes."""
        raise NotImplementedError

    def root(self) -> str:
        """The absolute root, or ''."""
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-reads the file system, keeping expansion and selection."""
        raise NotImplementedError

    def visible_paths(self) -> list[str]:
        """Absolute paths of the rows a user can see right now (the rows of
        collapsed folders are not visible), top to bottom, root excluded."""
        raise NotImplementedError

    def expand(self, path: str) -> None:
        """Expands the folder `path` (and its ancestors)."""
        raise NotImplementedError

    def reveal(self, path: str) -> None:
        """Expands the ancestors of `path`, selects it and scrolls to it.
        Paths outside the root or missing are ignored."""
        raise NotImplementedError

    def selected_path(self) -> str:
        """The selected row's absolute path, or ''."""
        raise NotImplementedError

    def new_file(self, directory: str, name: str) -> str:
        """Creates an empty file `name` in `directory` (inside the root),
        reveals it and returns its path. Raises ValueError for a bad name or
        a directory outside the root, FileExistsError when it exists."""
        raise NotImplementedError

    def new_folder(self, directory: str, name: str) -> str:
        """Same as new_file for a folder."""
        raise NotImplementedError

    def rename(self, path: str, new_name: str) -> str:
        """Renames a file or folder in place (same parent), emits fileRenamed
        and returns the new path. ValueError / FileExistsError as above."""
        raise NotImplementedError

    def delete(self, path: str) -> None:
        """Deletes a file, or a folder with its contents (no confirmation --
        the context menu asks first), and emits fileDeleted. Refuses the
        root itself and paths outside it with ValueError."""
        raise NotImplementedError

    def set_filter(self, text: str) -> None:
        """Same as typing `text` into filter_edit."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        raise NotImplementedError
