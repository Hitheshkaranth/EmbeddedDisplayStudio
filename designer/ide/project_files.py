"""designer/ide/project_files.py -- the project folder: file helpers and the tree.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W1. Public names,
signatures, signals and docstrings are the contract; W1 fills in the bodies
and may add private helpers and private classes. See docs/CODE_SECTION.md.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import QFileSystemWatcher, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QMenu, QTreeView, QHeaderView, QLineEdit, QLabel, QVBoxLayout, QWidget, QApplication,
)

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
    _, ext = os.path.splitext(path)
    return EXTENSION_LANGUAGES.get(ext.lower(), "plain")


def is_binary(path: str) -> bool:
    """True when the first BINARY_SNIFF_BYTES bytes contain a NUL byte."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(BINARY_SNIFF_BYTES)
            return b"\x00" in chunk
    except OSError:
        return False


def read_text(path: str) -> TextFile:
    """Reads a text file for editing. Raises FileReadError when the path is
    not a file, is larger than MAX_TEXT_BYTES, is binary (is_binary), or
    cannot be read. Tries UTF-8 (detecting a BOM -> 'utf-8-sig'), falls back
    to latin-1."""
    if not os.path.isfile(path):
        raise FileReadError(f"Not a file: {path}")
    try:
        size = os.path.getsize(path)
    except OSError:
        raise FileReadError("Cannot stat file")
    if size > MAX_TEXT_BYTES:
        raise FileReadError("File is too large")
    if is_binary(path):
        raise FileReadError("File is binary")
    # Read raw bytes
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise FileReadError(f"Cannot read file: {e}")
    # Determine newline style from the first line ending
    newline = "\n"
    crlf_pos = raw.find(b"\r\n")
    if crlf_pos != -1:
        newline = "\r\n"
    # Try UTF-8 (with BOM detection)
    encoding = "utf-8"
    text = None
    try:
        decoded = raw.decode("utf-8")
        if raw.startswith(b"\xef\xbb\xbf"):
            encoding = "utf-8-sig"
            decoded = decoded[1:]  # strip BOM from text
        text = decoded
    except UnicodeDecodeError:
        pass
    if text is None:
        # Fall back to latin-1
        encoding = "latin-1"
        text = raw.decode("latin-1")
    # Normalize line endings to \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return TextFile(text=text, encoding=encoding, newline=newline)


def write_text(path: str, text: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Writes atomically: to a temporary file in the same directory, then
    os.replace over path. text uses "\\n"; each is written as `newline`.
    Parent directories must exist. Raises OSError on failure, leaving the
    original file untouched and no temporary file behind."""
    parent = os.path.dirname(path)
    fd = None
    tmp_path = None
    try:
        # Encode BEFORE creating temp file so a bad codec leaves nothing behind
        encoded = text.replace("\n", newline).encode(encoding)
        fd, tmp_path = tempfile.mkstemp(dir=parent)
        os.write(fd, encoded)
        os.close(fd)
        fd = None
        os.replace(tmp_path, path)
        tmp_path = None
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def is_inside(root: str, path: str) -> bool:
    """True when path (after os.path.realpath) is root or lies below it.
    Guards every path that reaches the file system from an agent or a name
    typed by the user."""
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


def relative_path(root: str, path: str) -> str:
    """path relative to root with '/' separators ('.' for root itself);
    the absolute path, '/'-separated, when it is not inside root."""
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    if not is_inside(root, path):
        return path.replace(os.sep, "/")
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def validate_name(name: str) -> str:
    """A new file/folder name typed by the user, stripped. Raises ValueError
    (with a readable message) when it is empty, '.' or '..', or contains
    '/', '\\\\', ':' or a character in '<>\"|?*' or a control character."""
    name = name.strip()
    if not name:
        raise ValueError("Name is empty")
    if name in (".", ".."):
        raise ValueError(f"Invalid name: {name!r}")
    for ch in name:
        if ch in '<>:"|?*':
            raise ValueError(f"Name contains invalid character: {ch!r}")
        if ch == "/" or ch == "\\":
            raise ValueError(f"Name contains separator: {ch!r}")
        if ch == ":":
            raise ValueError(f"Name contains colon: {ch!r}")
        if ord(ch) < 32:  # control characters
            raise ValueError(f"Name contains control character")
    return name


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
        self._view = QTreeView()
        self._view.setHeaderHidden(True)
        self._view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.setEditTriggers(QTreeView.EditTrigger.DoubleClicked | QTreeView.EditTrigger.SelectedClicked)
        self._view.setExpandsOnDoubleClick(False)
        self._view.setSortingEnabled(False)

        # Model created and set before connecting signals
        self._model = QStandardItemModel(self._view)
        self._view.setModel(self._model)
        self._model.rowsInserted.connect(self._on_rows_inserted)

        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # Event filter on the view to catch Return/Enter key (not just double-click)
        self._view.installEventFilter(self)

        # Proxy for filtering
        self._proxy = QSortFilterProxyModel()
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setSourceModel(self._model)
        self._view.setModel(self._proxy)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter")
        self._filter_edit.textChanged.connect(self._on_filter_changed)

        self._empty_label = QLabel("No project folder")
        self._empty_label.setAlignment(Qt.AlignCenter)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._filter_edit)
        layout.addWidget(self._empty_label)
        layout.addWidget(self._view)

        self._root = ""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._watch_timer = QTimer()
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(200)
        self._watch_timer.timeout.connect(self.refresh)
        self._watch_timer.timeout.connect(self._watch_timer.stop)

        self._expanded_paths = set()  # track which folders are expanded
        self._filter_text = ""
        self._previous_expansion = set()  # before filter
        self._selecting = False  # block selection signals during programmatic selection

        # Connect signals
        self._view.activated.connect(self._on_activated)
        self._view.doubleClicked.connect(self._on_double_clicked)
        self._view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._view.expanded.connect(self._on_expanded)
        self._view.collapsed.connect(self._on_collapsed)

    def eventFilter(self, obj, event):
        """Catch Return and Enter key on the view."""
        from PySide6.QtWidgets import QTreeView
        from PySide6.QtCore import Qt, QEvent

        if obj is self._view and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                # Activate the current index
                idx = self._view.currentIndex()
                if idx.isValid():
                    proxy_idx = idx  # already a proxy index
                    source_idx = self._proxy.mapToSource(proxy_idx)
                    self._activate_item(source_idx, proxy_idx)
                return True
        return super().eventFilter(obj, event)

    def _on_directory_changed(self, path):
        """When a watched directory changes on disk, debounce a refresh."""
        self._watch_timer.start()

    def _on_rows_inserted(self, parent, start, end):
        """When rows are inserted into the model, track them."""
        pass

    def _on_filter_changed(self, text):
        """When the filter text changes, apply filter or restore."""
        self._apply_filter(text)

    def _on_activated(self, index):
        """Handle activated (Enter key) on the tree."""
        if index.isValid():
            source_idx = self._proxy.mapToSource(index)
            self._activate_item(source_idx, index)

    def _on_double_clicked(self, index):
        """Handle double-click on the tree."""
        if index.isValid():
            source_idx = self._proxy.mapToSource(index)
            self._activate_item(source_idx, index)

    def _on_selection_changed(self, selected, deselected):
        """Track expansion state when selection changes."""
        pass

    def _on_expanded(self, index):
        """Track when a folder is expanded."""
        if index.isValid():
            source_idx = self._proxy.mapToSource(index)
            path = str(source_idx.data(Qt.UserRole))
            self._expanded_paths.add(path)
            # Watch the folder for changes
            if path and os.path.isdir(path) and path not in self._watcher.directories():
                self._watcher.addPath(path)

    def _on_collapsed(self, index):
        """Track when a folder is collapsed."""
        if index.isValid():
            source_idx = self._proxy.mapToSource(index)
            path = str(source_idx.data(Qt.UserRole))
            self._expanded_paths.discard(path)
            # Unwatch when collapsed
            if path and path in self._watcher.directories():
                self._watcher.removePath(path)

    def _activate_item(self, source_idx, proxy_idx):
        """Activate a file or expand a folder."""
        item = self._model.itemFromIndex(source_idx)
        if item is None:
            return
        path = str(item.data(Qt.UserRole))
        if not path:
            return
        if os.path.isdir(path):
            # Expand/collapse the folder
            is_expanded = self._view.isExpanded(proxy_idx)
            if is_expanded:
                self._view.collapse(proxy_idx)
            else:
                self._view.expand(proxy_idx)
                # Load children synchronously
                self._load_children(path)
        else:
            # It's a file, emit activation
            self.fileActivated.emit(path)

    # --------------------------------------------------------------------

    def set_root(self, path: str) -> None:
        """Shows the folder `path` (made absolute); '' or a missing folder
        shows `empty_label` ("No project folder") instead of the view. The
        root's direct children are listed, folders collapsed. Emits
        rootChanged when the root actually changes."""
        if path:
            path = os.path.realpath(path)
        if path == self._root:
            return
        # Clean up old root watching
        if self._root and self._root in self._watcher.directories():
            self._watcher.removePath(self._root)
        old_root = self._root
        self._root = path
        self._expanded_paths.clear()
        self._filter_text = ""
        self._filter_edit.clear()
        self._model.clear()
        if path and os.path.isdir(path):
            self._empty_label.hide()
            self._view.show()
            self._build_root(path)
            self._watcher.addPath(path)
            self.rootChanged.emit(path)
        else:
            self._empty_label.show()
            self._view.hide()
            self._root = ""
            self.rootChanged.emit("")
            if old_root:
                self.rootChanged.emit("")

    def root(self) -> str:
        """The absolute root, or ''."""
        return self._root

    def refresh(self) -> None:
        """Re-reads the file system, keeping expansion and selection."""
        if not self._root or not os.path.isdir(self._root):
            return
        # Save selection and expanded state
        selected = self.selected_path()
        expanded = set(self._expanded_paths)

        # Rebuild the model
        self._model.clear()
        self._build_root(self._root)

        # Restore expanded folders (re-load children)
        self._expanded_paths = set()
        for path in expanded:
            if os.path.isdir(path):
                self._expanded_paths.add(path)
                self._view_expand_path(path)

        # Restore selection
        if selected and os.path.exists(selected):
            self.reveal(selected)

    def visible_paths(self) -> list[str]:
        """Absolute paths of the rows a user can see right now (the rows of
        collapsed folders are not visible), top to bottom, root excluded."""
        result = []
        self._walk_visible(self._model.index(0, 0), result)
        return result

    def _walk_visible(self, source_parent, result):
        """Walk the model depth-first, descending only into expanded rows."""
        row_count = self._model.rowCount(source_parent)
        for row in range(row_count):
            source_idx = self._model.index(row, 0, source_parent)
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if not proxy_idx.isValid():
                continue
            item = self._model.itemFromIndex(source_idx)
            if item is None:
                continue
            path = str(item.data(Qt.UserRole))
            if not path:
                continue
            is_expanded = self._view.isExpanded(proxy_idx)
            # Add the current item (visible if parent is expanded or it's a top-level row)
            result.append(path)
            if is_expanded and os.path.isdir(path):
                self._walk_visible(source_idx, result)

    def expand(self, path: str) -> None:
        """Expands the folder `path` (and its ancestors)."""
        if not self._root:
            return
        # Make sure all ancestors are loaded
        self._expand_ancestors(path)
        # Expand the folder itself
        source_idx = self._find_index(path)
        if source_idx.isValid():
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if proxy_idx.isValid():
                self._view.expand(proxy_idx)
                self._expanded_paths.add(path)
                # Watch the folder
                if path not in self._watcher.directories():
                    self._watcher.addPath(path)

    def _expand_ancestors(self, path):
        """Make sure the path exists in the model by loading all ancestors."""
        if not self._root or not is_inside(self._root, path):
            return
        # Walk up the hierarchy and ensure each parent is expanded
        parent = os.path.dirname(path)
        if parent == self._root or not is_inside(self._root, parent):
            return
        # Load parent
        parent_idx = self._find_index(parent)
        if parent_idx.isValid():
            proxy_idx = self._proxy.mapFromSource(parent_idx)
            if proxy_idx.isValid():
                self._view.expand(proxy_idx)
                self._expanded_paths.add(parent)
                if parent not in self._watcher.directories():
                    self._watcher.addPath(parent)
        else:
            # Parent doesn't exist in model yet, load it
            self._view_expand_path(parent)
        self._expand_ancestors(parent)

    def reveal(self, path: str) -> None:
        """Expands the ancestors of `path`, selects it and scrolls to it.
        Paths outside the root or missing are ignored."""
        if not self._root or not is_inside(self._root, path):
            return
        if not os.path.exists(path):
            return
        self.expand(path)
        source_idx = self._find_index(path)
        if source_idx.isValid():
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if proxy_idx.isValid():
                self._view.setCurrentIndex(proxy_idx)
                self._view.scrollTo(proxy_idx)
                self._view.ensureVisible(proxy_idx)

    def selected_path(self) -> str:
        """The selected row's absolute path, or ''."""
        sel = self._view.selectionModel()
        if sel is None:
            return ""
        indexes = sel.selectedIndexes()
        if not indexes:
            return ""
        # Get the first column index
        idx = indexes[0]
        source_idx = self._proxy.mapToSource(idx)
        item = self._model.itemFromIndex(source_idx)
        if item is None:
            return ""
        return str(item.data(Qt.UserRole)) or ""

    def new_file(self, directory: str, name: str) -> str:
        """Creates an empty file `name` in `directory` (inside the root),
        reveals it and returns its path. Raises ValueError for a bad name or
        a directory outside the root, FileExistsError when it exists."""
        if not self._root:
            raise ValueError("No root set")
        name = validate_name(name)
        if not is_inside(self._root, directory):
            raise ValueError(f"Directory {directory} is outside the root")
        path = os.path.join(directory, name)
        if os.path.exists(path):
            raise FileExistsError(f"File already exists: {path}")
        # Create the file
        with open(path, "w") as f:
            f.write("")
        self.reveal(path)
        return path

    def new_folder(self, directory: str, name: str) -> str:
        """Same as new_file for a folder."""
        if not self._root:
            raise ValueError("No root set")
        name = validate_name(name)
        if not is_inside(self._root, directory):
            raise ValueError(f"Directory {directory} is outside the root")
        path = os.path.join(directory, name)
        if os.path.exists(path):
            raise FileExistsError(f"Folder already exists: {path}")
        os.makedirs(path, exist_ok=True)
        self.reveal(path)
        return path

    def rename(self, path: str, new_name: str) -> str:
        """Renames a file or folder in place (same parent), emits fileRenamed
        and returns the new path. ValueError / FileExistsError as above."""
        new_name = validate_name(new_name)
        if not self._root or not is_inside(self._root, path):
            raise ValueError(f"Path {path} is outside the root")
        parent = os.path.dirname(path)
        new_path = os.path.join(parent, new_name)
        if os.path.exists(new_path):
            raise FileExistsError(f"Already exists: {new_path}")
        os.rename(path, new_path)
        self.fileRenamed.emit(path, new_path)
        self.reveal(new_path)
        return new_path

    def delete(self, path: str) -> None:
        """Deletes a file, or a folder with its contents (no confirmation --
        the context menu asks first), and emits fileDeleted. Refuses the
        root itself and paths outside it with ValueError."""
        if not self._root:
            raise ValueError("No root set")
        root_real = os.path.realpath(self._root)
        path_real = os.path.realpath(path)
        if path_real == root_real:
            raise ValueError("Cannot delete the root folder")
        if not is_inside(self._root, path):
            raise ValueError(f"Path {path} is outside the root")
        self.fileDeleted.emit(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def set_filter(self, text: str) -> None:
        """Same as typing `text` into filter_edit."""
        self._filter_edit.blockSignals(True)
        self._filter_edit.setText(text)
        self._filter_edit.blockSignals(False)
        self._apply_filter(text)

    def _apply_filter(self, text):
        """Apply the filter or restore from filter."""
        self._filter_text = text.strip()
        if self._filter_text:
            # Filter mode: show matching files and their ancestors, all expanded
            self._proxy.setFilterRegularExpression(
                QRegularExpression(self._filter_text, Qt.CaseInsensitive)
            )
            # Find all matches and expand them
            self._expand_matches()
        else:
            # Clear filter mode
            self._proxy.setFilterRegularExpression("")
            # Restore previous expansion
            for path in self._previous_expansion:
                self._view_expand_path(path)

    def _expand_matches(self):
        """Expand all folders that lead to matching files."""
        # Load the whole tree first (if not already fully loaded)
        self._load_all_visible()
        # Expand all matching paths
        source_root = self._model.index(0, 0)
        self._match_expand_recursive(source_root, "")

    def _load_all_visible(self):
        """Load all children recursively (for filter to work)."""
        if not self._root or not os.path.isdir(self._root):
            return
        self._load_recursive(self._root, self._model.index(0, 0))

    def _match_expand_recursive(self, source_parent, parent_path):
        """Expand rows that match the filter, along with their ancestors."""
        row_count = self._model.rowCount(source_parent)
        for row in range(row_count):
            source_idx = self._model.index(row, 0, source_parent)
            item = self._model.itemFromIndex(source_idx)
            if item is None:
                continue
            path = str(item.data(Qt.UserRole))
            name = os.path.basename(path) if path else ""
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if not proxy_idx.isValid():
                continue
            if self._filter_text.lower() in name.lower():
                self._view.expand(proxy_idx)
                self._expanded_paths.add(path)
                # Load children
                if os.path.isdir(path):
                    self._load_children(path)
                    self._match_expand_recursive(source_idx, path)
            else:
                if os.path.isdir(path):
                    self._match_expand_recursive(source_idx, path)

    def _view_expand_path(self, path):
        """Expand a folder in the view, loading its children if needed."""
        source_idx = self._find_index(path)
        if source_idx.isValid():
            proxy_idx = self._proxy.mapFromSource(source_idx)
            if proxy_idx.isValid():
                self._view.expand(proxy_idx)
                self._expanded_paths.add(path)
                if path not in self._watcher.directories():
                    self._watcher.addPath(path)

    def _apply_theme_qss(self, theme):
        """Apply theme-specific styling to the tree."""
        if theme == "light":
            self.setStyleSheet("""
                QTreeView {
                    background: #ffffff;
                    color: #000000;
                    border: 1px solid #cccccc;
                    font-size: 12px;
                }
                QTreeView::item {
                    padding: 2px 0px;
                }
                QTreeView::item:selected {
                    background: #d0e0ff;
                    color: #000000;
                }
                QTreeView::item:hover {
                    background: #e8e8e8;
                }
                QTreeView::branch {
                    background: #ffffff;
                }
                QTreeView::branch:has-children {
                    image: none;
                }
                QTreeView::branch:closed:has-children {
                    image: none;
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
                QTreeView {
                    background: #1e1e1e;
                    color: #cccccc;
                    border: 1px solid #3c3c3c;
                    font-size: 12px;
                }
                QTreeView::item {
                    padding: 2px 0px;
                }
                QTreeView::item:selected {
                    background: #094771;
                    color: #ffffff;
                }
                QTreeView::item:hover {
                    background: #2a2d2e;
                }
                QTreeView::branch {
                    background: #1e1e1e;
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

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._apply_theme_qss(theme)

    # -------------------------------------------------------------------- private helpers

    def _find_index(self, path):
        """Find a QStandardItemModel index by path value."""
        return self._find_recursive(self._model.index(0, 0), path)

    def _find_recursive(self, source_parent, path):
        """Recursively find an item by path."""
        row_count = self._model.rowCount(source_parent)
        for row in range(row_count):
            idx = self._model.index(row, 0, source_parent)
            item = self._model.itemFromIndex(idx)
            if item:
                if str(item.data(Qt.UserRole)) == path:
                    return idx
                # Recurse into children
                child = self._find_recursive(idx, path)
                if child.isValid():
                    return child
        return self._model.index(-1, 0)

    def _build_root(self, path):
        """Build the initial tree for `path`."""
        self._model.setColumnCount(1)
        self._model.setHorizontalHeaderLabels([""])
        self._load_children(path, parent_item=None, is_root=True)

    def _load_children(self, path, parent_item=None, is_root=False):
        """Load children of `path` into the model.
        
        parent_item: the QStandardItem parent (None for root)
        is_root: if True, the model is empty and we're building from scratch
        """
        if parent_item is None:
            parent_item = self._model.invisibleRootItem()

        # Check if children already loaded
        if parent_item.rowCount() > 0 and not is_root:
            # Check if this is a placeholder item (just "..." loaded previously)
            first_child = parent_item.child(0, 0)
            if first_child and first_child.text() == "...":
                # Remove placeholder
                parent_item.removeRow(0)
            else:
                # Already loaded, skip
                return

        try:
            entries = []
            with os.scandir(path) as it:
                for entry in it:
                    if entry.name in IGNORED_DIRS:
                        continue
                    entries.append(entry)
        except OSError:
            return

        # Separate folders and files, sort each group case-insensitively
        folders = []
        files = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    folders.append((entry.name, True, entry.path))
                else:
                    files.append((entry.name, False, entry.path))
            except OSError:
                continue

        folders.sort(key=lambda x: x[0].lower())
        files.sort(key=lambda x: x[0].lower())

        # Clear existing children first (if rebuilding)
        if is_root:
            parent_item.removeRows(0, parent_item.rowCount())
        else:
            # Only clear if this is being reloaded (not initial load)
            pass

        # Add folders first, then files
        for name, is_dir, full_path in folders:
            item = QStandardItem(name)
            item.setData(full_path, Qt.UserRole)
            if is_dir:
                # Add a placeholder so the expand arrow shows
                placeholder = QStandardItem("...")
                placeholder.setEnabled(False)
                item.appendRow(placeholder)
            parent_item.appendRow(item)

        for name, is_dir, full_path in files:
            item = QStandardItem(name)
            item.setData(full_path, Qt.UserRole)
            parent_item.appendRow(item)

        # Track expanded folders
        for name, is_dir, full_path in folders:
            if is_dir and full_path in self._expanded_paths:
                self._load_children(full_path, item=None, is_root=False)

    def _load_recursive(self, path, source_parent):
        """Load all children recursively (for filter loading)."""
        # Check if already loaded
        row_count = self._model.rowCount(source_parent)
        if row_count > 0:
            first = self._model.itemFromIndex(self._model.index(0, 0, source_parent))
            if first and first.text() != "...":
                return  # Already loaded

        item = self._model.itemFromIndex(source_parent)
        # Load children
        self._load_children(path, parent_item=source_parent)

        # Recurse into folders
        row_count = self._model.rowCount(source_parent)
        for row in range(row_count):
            child_idx = self._model.index(row, 0, source_parent)
            child_item = self._model.itemFromIndex(child_idx)
            if child_item:
                child_path = str(child_item.data(Qt.UserRole))
                if child_path and os.path.isdir(child_path):
                    self._load_recursive(child_path, child_idx)

    def _show_context_menu(self, pos):
        """Show the context menu on right-click."""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtGui import QAction

        index = self._view.indexAt(pos)
        source_idx = self._proxy.mapToSource(index) if index.isValid() else None

        menu = QMenu(self)

        new_file_action = QAction("New file...", self)
        new_file_action.triggered.connect(lambda: self._new_item(is_file=True))
        menu.addAction(new_file_action)

        new_folder_action = QAction("New folder...", self)
        new_folder_action.triggered.connect(lambda: self._new_item(is_file=False))
        menu.addAction(new_folder_action)

        if source_idx and source_idx.isValid():
            item = self._model.itemFromIndex(source_idx)
            if item:
                path = str(item.data(Qt.UserRole))
                if path and os.path.exists(path):
                    menu.addSeparator()

                    rename_action = QAction("Rename...", self)
                    rename_action.triggered.connect(lambda: self._rename_item(path))
                    menu.addAction(rename_action)

                    delete_action = QAction("Delete", self)
                    delete_action.triggered.connect(lambda: self._delete_item(path))
                    menu.addAction(delete_action)

                    menu.addSeparator()

                    copy_action = QAction("Copy path", self)
                    copy_action.triggered.connect(lambda: self._copy_path(path))
                    menu.addAction(copy_action)

                    reveal_action = QAction("Reveal in file manager", self)
                    reveal_action.triggered.connect(lambda: self._reveal_item(path))
                    menu.addAction(reveal_action)

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _new_item(self, is_file=True):
        """Create a new file or folder from the context menu."""
        # Determine the directory
        index = self._view.selectionModel().currentIndex()
        source_idx = self._proxy.mapToSource(index) if index.isValid() else None
        directory = self._root

        if source_idx and source_idx.isValid():
            item = self._model.itemFromIndex(source_idx)
            if item:
                path = str(item.data(Qt.UserRole))
                if path and os.path.isdir(path):
                    directory = path

        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "New Item",
                                         "Name:" if is_file else "Folder name:")
        if ok and text:
            try:
                if is_file:
                    self.new_file(directory, text)
                else:
                    self.new_folder(directory, text)
            except (ValueError, FileExistsError) as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", str(e))

    def _rename_item(self, path):
        """Rename an item from the context menu."""
        name = os.path.basename(path)
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Rename",
                                         "New name:", text=name)
        if ok and text and text != name:
            try:
                self.rename(path, text)
            except (ValueError, FileExistsError) as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", str(e))

    def _delete_item(self, path):
        """Delete an item from the context menu."""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "Delete",
                                      f"Delete {os.path.basename(path)}?",
                                      QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                self.delete(path)
            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _copy_path(self, path):
        """Copy a path to the clipboard."""
        from PySide6.QtGui import QClipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(path)

    def _reveal_item(self, path):
        """Reveal a file/folder in the native file manager."""
        import subprocess
        import sys
        parent = path if os.path.isdir(path) else os.path.dirname(path)
        if sys.platform == "win32":
            os.startfile(parent)
        elif sys.platform == "darwin":
            subprocess.call(["open", parent])
        else:
            subprocess.call(["xdg-open", parent])

    @property
    def view(self):
        return self._view

    @property
    def filter_edit(self):
        return self._filter_edit

    @property
    def empty_label(self):
        return self._empty_label


