"""designer/ide/project_files.py -- the project folder: file helpers and the tree.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W1. Public names,
signatures, signals and docstrings are the contract; W1 fills in the bodies
and may add private helpers and private classes. See docs/CODE_SECTION.md.
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass

from PySide6.QtCore import (
    QEvent, QFileSystemWatcher, QObject, QSortFilterProxyModel, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QColor, QDesktopServices, QGuiApplication, QStandardItem, QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QStyle, QTreeView,
    QVBoxLayout, QWidget,
)

try:
    from ui.python.shadcn import color
except ImportError:
    _FALLBACK_TOKENS = {
        "dark": {"background": "#09090b", "card": "#18181b", "border": "#27272a",
                 "foreground": "#fafafa", "mutedForeground": "#a1a1aa", "primary": "#fafafa"},
        "light": {"background": "#ffffff", "card": "#ffffff", "border": "#e4e4e7",
                  "foreground": "#09090b", "mutedForeground": "#71717a", "primary": "#18181b"},
    }

    def color(name, theme="dark"): return _FALLBACK_TOKENS[theme][name]

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

_PATH_ROLE = Qt.UserRole
_IS_DIR_ROLE = Qt.UserRole + 1
_LOADED_ROLE = Qt.UserRole + 2
# Coalesces the burst of directoryChanged a save or a checkout produces.
_WATCH_DELAY_MS = 200
# Filtering loads the whole tree; a project that vendors a large SDK must not
# stall the UI thread on a keystroke.
_FILTER_MAX_ENTRIES = 5000
_BAD_NAME_CHARS = '/\\:<>"|?*'


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
    return EXTENSION_LANGUAGES.get(os.path.splitext(path)[1].lower(), "plain")


def is_binary(path: str) -> bool:
    """True when the first BINARY_SNIFF_BYTES bytes contain a NUL byte."""
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return False


def read_text(path: str) -> TextFile:
    """Reads a text file for editing. Raises FileReadError when the path is
    not a file, is larger than MAX_TEXT_BYTES, is binary (is_binary), or
    cannot be read. Tries UTF-8 (detecting a BOM -> 'utf-8-sig'), falls back
    to latin-1."""
    name = os.path.basename(path) or path
    if not os.path.isfile(path):
        raise FileReadError(f"{name} is not a file.")
    try:
        # One bounded read: the size check and the content cannot disagree
        # when the file grows in between.
        with open(path, "rb") as f:
            raw = f.read(MAX_TEXT_BYTES + 1)
    except OSError as exc:
        raise FileReadError(f"{name} cannot be read ({exc.strerror or exc}).") from exc
    if len(raw) > MAX_TEXT_BYTES:
        raise FileReadError(f"{name} is larger than {MAX_TEXT_BYTES // (1024 * 1024)} MiB.")
    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        raise FileReadError(f"{name} is a binary file.")
    first_lf = raw.find(b"\n")
    newline = "\r\n" if first_lf > 0 and raw[first_lf - 1] == 0x0D else "\n"
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text, encoding = raw.decode("latin-1"), "latin-1"
    return TextFile(text.replace("\r\n", "\n").replace("\r", "\n"), encoding, newline)


def write_text(path: str, text: str, encoding: str = "utf-8", newline: str = "\n") -> None:
    """Writes atomically: to a temporary file in the same directory, then
    os.replace over path. text uses "\\n"; each is written as `newline`.
    Parent directories must exist. Raises OSError on failure, leaving the
    original file untouched and no temporary file behind."""
    try:
        # Encoded before anything touches the disk, so an unknown codec or
        # text the codec cannot hold leaves nothing behind.
        data = text.replace("\n", newline).encode(encoding)
    except (LookupError, UnicodeError) as exc:
        raise OSError(f"{os.path.basename(path)} cannot be saved as {encoding}: {exc}") from exc
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mode = None
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               prefix="." + os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates the file 0600; a saved file keeps its permissions.
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _is_under(root: str, path: str) -> bool:
    """Lexical containment of two _norm'ed paths."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def is_inside(root: str, path: str) -> bool:
    """True when path (after os.path.realpath) is root or lies below it.
    Guards every path that reaches the file system from an agent or a name
    typed by the user."""
    if not root or not path:
        return False
    return _is_under(_norm(os.path.realpath(root)), _norm(os.path.realpath(path)))


def relative_path(root: str, path: str) -> str:
    """path relative to root with '/' separators ('.' for root itself);
    the absolute path, '/'-separated, when it is not inside root."""
    absolute = os.path.abspath(path)
    if not is_inside(root, path):
        return absolute.replace(os.sep, "/")
    base = os.path.abspath(root)
    if not _is_under(_norm(base), _norm(absolute)):
        # Spelled through a symlink on one side only: compare real locations.
        base, absolute = os.path.realpath(root), os.path.realpath(path)
    return os.path.relpath(absolute, base).replace(os.sep, "/")


def validate_name(name: str) -> str:
    """A new file/folder name typed by the user, stripped. Raises ValueError
    (with a readable message) when it is empty, '.' or '..', or contains
    '/', '\\\\', ':' or a character in '<>\"|?*' or a control character."""
    name = (name or "").strip()
    if not name:
        raise ValueError("The name is empty.")
    if name in (".", ".."):
        raise ValueError(f"'{name}' is not a valid name.")
    for ch in name:
        if ch in _BAD_NAME_CHARS:
            raise ValueError(f"A name cannot contain '{ch}'.")
        if ord(ch) < 32 or ord(ch) == 127:
            raise ValueError("A name cannot contain control characters.")
    return name


def _scan(directory: str) -> list[tuple[str, str, bool]]:
    """(name, abs path, is_dir) of a folder's entries in tree order;
    [] when the folder cannot be read."""
    entries = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    is_dir = False
                if is_dir and entry.name in IGNORED_DIRS:
                    continue
                entries.append((entry.name, os.path.join(directory, entry.name), is_dir))
    except OSError:
        return []
    entries.sort(key=lambda e: (not e[2], e[0].lower(), e[0]))
    return entries


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.2f})"


# How often watched paths are stat'ed on Windows (see _PollingWatcher).
_POLL_MS = 1000


class _PollingWatcher(QObject):
    """QFileSystemWatcher's API (addPath(s), removePath(s), files,
    directories, fileChanged, directoryChanged) by polling once a second.

    Used on Windows, where QFileSystemWatcher keeps a handle open on each
    watched folder, and on each watched file's folder: renaming a folder
    above a watched one then fails with "Access is denied" -- for the tree's
    own rename, for git, for the agent -- and so do ~2 % of other programs'
    atomic replaces of a watched file. A stat per path per second holds
    nothing open. A file's stamp is (size, mtime); a folder's is its mtime,
    which NTFS moves whenever an entry is added, removed or renamed."""

    fileChanged = Signal(str)
    directoryChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: dict[str, tuple | None] = {}
        self._dirs: dict[str, int | None] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._poll)

    def addPath(self, path: str) -> bool:
        return not self.addPaths([path])

    def addPaths(self, paths) -> list[str]:
        failed = []
        for path in paths:
            if os.path.isdir(path):
                self._dirs[path] = self._dir_stamp(path)
            elif os.path.isfile(path):
                self._files[path] = self._file_stamp(path)
            else:
                failed.append(path)
        if self._files or self._dirs:
            self._timer.start()
        return failed

    def removePath(self, path: str) -> bool:
        return not self.removePaths([path])

    def removePaths(self, paths) -> list[str]:
        failed = [p for p in paths if self._files.pop(p, False) is False
                  and self._dirs.pop(p, False) is False]
        if not self._files and not self._dirs:
            self._timer.stop()
        return failed

    def files(self) -> list[str]:
        return list(self._files)

    def directories(self) -> list[str]:
        return list(self._dirs)

    @staticmethod
    def _file_stamp(path: str):
        try:
            info = os.stat(path)
        except OSError:
            return None
        return info.st_size, info.st_mtime_ns

    @staticmethod
    def _dir_stamp(path: str):
        try:
            return os.stat(path).st_mtime_ns
        except OSError:
            return None

    def _poll(self) -> None:
        for path, before in list(self._files.items()):
            now = self._file_stamp(path)
            if now != before and path in self._files:
                self._files[path] = now
                self.fileChanged.emit(path)
        for path, before in list(self._dirs.items()):
            now = self._dir_stamp(path)
            if now != before and path in self._dirs:
                self._dirs[path] = now
                self.directoryChanged.emit(path)


def _file_watcher(parent) -> QObject:
    """The watcher the tree and the editors use: Qt's own, or on Windows the
    poller that locks nothing."""
    return _PollingWatcher(parent) if os.name == "nt" else QFileSystemWatcher(parent)


class _FilterProxy(QSortFilterProxyModel):
    """Keeps the files whose name contains the filter text; a folder stays
    only through recursive filtering, i.e. when something below it matches."""

    def filterAcceptsRow(self, row, parent):
        if not self.filterRegularExpression().pattern():
            return True
        if self.sourceModel().index(row, 0, parent).data(_IS_DIR_ROLE):
            return False
        return super().filterAcceptsRow(row, parent)


class ProjectTree(QWidget):
    """The project folder as a tree, with a filter field on top.

    The model is built synchronously from os.scandir (not QFileSystemModel,
    whose asynchronous loading makes reveal() and tests unreliable): after
    set_root / refresh / new_file / new_folder / rename / delete return,
    visible_paths() already reflects the file system. Folders come first,
    then files, each case-insensitively by name; IGNORED_DIRS are hidden.
    A QFileSystemWatcher (on Windows a poller that locks nothing) on the
    root and the expanded folders calls refresh()
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
        self.setObjectName("projectTree")
        self._root = ""
        self._needle = ""
        # The expansion in place when a filter started; restored when it clears.
        self._saved_expansion: set[str] = set()
        self._dir_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self._file_icon = self.style().standardIcon(QStyle.SP_FileIcon)

        self._model = QStandardItemModel(self)
        self._proxy = _FilterProxy(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setRecursiveFilteringEnabled(True)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("projectTreeFilter")
        self.filter_edit.setPlaceholderText("Filter files")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_text)

        self.view = QTreeView()
        self.view.setObjectName("projectTreeView")
        self.view.setModel(self._proxy)
        self.view.setHeaderHidden(True)
        self.view.setUniformRowHeights(True)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        # Double-click is ours: a file opens, a folder toggles -- once.
        self.view.setExpandsOnDoubleClick(False)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_menu)
        self.view.doubleClicked.connect(self._activate)
        self.view.expanded.connect(self._on_expanded)
        self.view.collapsed.connect(self._sync_watcher)
        # QTreeView.activated is not emitted for Enter by every style.
        self.view.installEventFilter(self)

        self.empty_label = QLabel("No project folder")
        self.empty_label.setObjectName("projectTreeEmpty")
        self.empty_label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty_label, 1)

        self._watcher = _file_watcher(self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_WATCH_DELAY_MS)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)

        self._show_view(False)
        self.apply_theme("dark")

    # ----------------------------------------------------------------- public

    def set_root(self, path: str) -> None:
        """Shows the folder `path` (made absolute); '' or a missing folder
        shows `empty_label` ("No project folder") instead of the view. The
        root's direct children are listed, folders collapsed. Emits
        rootChanged when the root actually changes."""
        root = os.path.abspath(path) if path and os.path.isdir(path) else ""
        changed = root != self._root
        self._refresh_timer.stop()
        self._root = root
        self._needle = ""
        self._saved_expansion = set()
        self.filter_edit.blockSignals(True)
        self.filter_edit.clear()
        self.filter_edit.blockSignals(False)
        self._proxy.setFilterFixedString("")
        self._model.removeRows(0, self._model.rowCount())
        if root:
            self._fill(self._model.invisibleRootItem(), root)
        self._show_view(bool(root))
        self._sync_watcher()
        if changed:
            self.rootChanged.emit(root)

    def root(self) -> str:
        """The absolute root, or ''."""
        return self._root

    def refresh(self) -> None:
        """Re-reads the file system, keeping expansion and selection."""
        if self._root:
            self._rebuild(self._expanded_paths(), self.selected_path())

    def visible_paths(self) -> list[str]:
        """Absolute paths of the rows a user can see right now (the rows of
        collapsed folders are not visible), top to bottom, root excluded."""
        paths: list[str] = []
        if not self._root:
            return paths

        def walk(parent):
            for row in range(self._proxy.rowCount(parent)):
                index = self._proxy.index(row, 0, parent)
                path = index.data(_PATH_ROLE)
                if not path:
                    continue
                paths.append(path)
                if self.view.isExpanded(index):
                    walk(index)

        walk(self.view.rootIndex())
        return paths

    def expand(self, path: str) -> None:
        """Expands the folder `path` (and its ancestors)."""
        target = self._entry_path(path)
        if not target or target == self._root or not os.path.isdir(target):
            return
        chain = []
        while target != self._root:
            chain.append(target)
            target = os.path.dirname(target)
        for folder in reversed(chain):
            item = self._item_for(folder)
            if item is None:
                return
            self._load(item)
            index = self._proxy.mapFromSource(item.index())
            if index.isValid():
                self.view.expand(index)

    def reveal(self, path: str) -> None:
        """Expands the ancestors of `path`, selects it and scrolls to it.
        Paths outside the root or missing are ignored."""
        target = self._entry_path(path)
        if not target or target == self._root or not os.path.lexists(target):
            return
        item = self._item_for(target)
        if item is None:
            return
        if self._needle and not self._proxy.mapFromSource(item.index()).isValid():
            # The filter hides it, and the user asked to see this one.
            self.filter_edit.clear()
            item = self._item_for(target)
        self.expand(os.path.dirname(target))
        index = self._proxy.mapFromSource(item.index())
        if index.isValid():
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)

    def selected_path(self) -> str:
        """The selected row's absolute path, or ''."""
        rows = self.view.selectionModel().selectedRows()
        return (rows[0].data(_PATH_ROLE) or "") if rows else ""

    def new_file(self, directory: str, name: str) -> str:
        """Creates an empty file `name` in `directory` (inside the root),
        reveals it and returns its path. Raises ValueError for a bad name or
        a directory outside the root, FileExistsError when it exists."""
        target = self._new_target(directory, name)
        with open(target, "x", encoding="utf-8"):
            pass
        self.refresh()
        self.reveal(target)
        return target

    def new_folder(self, directory: str, name: str) -> str:
        """Same as new_file for a folder."""
        target = self._new_target(directory, name)
        os.mkdir(target)
        self.refresh()
        self.reveal(target)
        return target

    def rename(self, path: str, new_name: str) -> str:
        """Renames a file or folder in place (same parent), emits fileRenamed
        and returns the new path. ValueError / FileExistsError as above."""
        name = validate_name(new_name)
        source = self._entry_path(path)
        if not source or source == self._root:
            raise ValueError(f"{path} is not inside the project folder.")
        target = os.path.join(os.path.dirname(source), name)
        if target == source:
            return source
        # A case-only rename on a case-insensitive file system finds itself.
        if os.path.lexists(target) and os.path.normcase(target) != os.path.normcase(source):
            raise FileExistsError(f"'{name}' already exists.")
        expanded = {self._moved(p, source, target) for p in self._expanded_paths()}
        selected = self._moved(self.selected_path(), source, target)
        # A watch handle keeps a folder busy on Windows.
        self._unwatch_under(source)
        os.rename(source, target)
        self._rebuild(expanded, selected)
        self.fileRenamed.emit(source, target)
        return target

    def delete(self, path: str) -> None:
        """Deletes a file, or a folder with its contents (no confirmation --
        the context menu asks first), and emits fileDeleted. Refuses the
        root itself and paths outside it with ValueError."""
        target = self._entry_path(path)
        if not target:
            raise ValueError(f"{path} is not inside the project folder.")
        if target == self._root:
            raise ValueError("The project folder itself cannot be deleted.")
        self._unwatch_under(target)
        # A symlink goes, never what it points to.
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)
        self.refresh()
        self.fileDeleted.emit(target)

    def set_filter(self, text: str) -> None:
        """Same as typing `text` into filter_edit."""
        self.filter_edit.setText(text)

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        theme = "light" if theme == "light" else "dark"
        bg, fg, border = color("background", theme), color("foreground", theme), color("border", theme)
        muted, primary = color("mutedForeground", theme), color("primary", theme)
        self.setStyleSheet(f"""
            QWidget#projectTree {{ background: {bg}; }}
            QLineEdit#projectTreeFilter {{
                background: {bg}; color: {fg}; border: none; border-bottom: 1px solid {border};
                padding: 5px 8px; font-size: 12px;
            }}
            QTreeView#projectTreeView {{
                background: {bg}; color: {fg}; border: none; font-size: 12px; outline: 0;
            }}
            QTreeView#projectTreeView::item {{ padding: 2px 0; }}
            QTreeView#projectTreeView::item:hover {{ background: {_rgba(fg, 0.06)}; }}
            QTreeView#projectTreeView::item:selected {{
                background: {_rgba(primary, 0.16)}; color: {fg};
            }}
            QLabel#projectTreeEmpty {{ background: {bg}; color: {muted}; font-size: 12px; }}
        """)

    # ------------------------------------------------------------ the model

    def _make_item(self, name: str, path: str, is_dir: bool) -> QStandardItem:
        item = QStandardItem(self._dir_icon if is_dir else self._file_icon, name)
        item.setEditable(False)
        item.setData(path, _PATH_ROLE)
        item.setData(is_dir, _IS_DIR_ROLE)
        item.setToolTip(path)
        if is_dir:
            # Gives the folder its arrow until it is loaded on expand.
            placeholder = QStandardItem()
            placeholder.setFlags(Qt.NoItemFlags)
            item.appendRow(placeholder)
        return item

    def _fill(self, parent: QStandardItem, directory: str) -> None:
        parent.removeRows(0, parent.rowCount())
        for name, path, is_dir in _scan(directory):
            parent.appendRow(self._make_item(name, path, is_dir))

    def _load(self, item: QStandardItem) -> None:
        if item is self._model.invisibleRootItem() or item.data(_LOADED_ROLE):
            return
        item.setData(True, _LOADED_ROLE)
        self._fill(item, item.data(_PATH_ROLE))

    def _item_for(self, path: str):
        """The model item of a path spelled under the root (loading the
        folders on the way), the invisible root item for the root, or None."""
        item = self._model.invisibleRootItem()
        rel = os.path.relpath(path, self._root)
        if rel == ".":
            return item
        for part in rel.split(os.sep):
            self._load(item)
            wanted = os.path.normcase(part)
            for row in range(item.rowCount()):
                child = item.child(row)
                if child.data(_PATH_ROLE) and os.path.normcase(child.text()) == wanted:
                    item = child
                    break
            else:
                return None
        return item

    def _load_all(self) -> None:
        """Loads folders breadth-first until _FILTER_MAX_ENTRIES rows exist,
        so the filter sees files in folders never expanded."""
        queue = [self._model.invisibleRootItem()]
        count = 0
        while queue and count < _FILTER_MAX_ENTRIES:
            item = queue.pop(0)
            self._load(item)
            for row in range(item.rowCount()):
                child = item.child(row)
                count += 1
                # A symlinked folder could loop; it loads when expanded.
                if child.data(_IS_DIR_ROLE) and not os.path.islink(child.data(_PATH_ROLE)):
                    queue.append(child)

    def _rebuild(self, expanded: set[str], selected: str) -> None:
        scroll = self.view.verticalScrollBar().value()
        self._model.removeRows(0, self._model.rowCount())
        self._fill(self._model.invisibleRootItem(), self._root)
        if self._needle:
            self._load_all()
            self.view.expandAll()
        else:
            self._restore_expansion(expanded)
        if selected and self._entry_path(selected):
            item = self._item_for(selected)
            if item is not None and item is not self._model.invisibleRootItem():
                index = self._proxy.mapFromSource(item.index())
                if index.isValid():
                    self.view.setCurrentIndex(index)
        self._sync_watcher()
        self.view.verticalScrollBar().setValue(scroll)

    def _restore_expansion(self, paths) -> None:
        # Parents first, and without expanding ancestors the user had
        # collapsed: a folder inside a collapsed one stays expanded, hidden.
        for path in sorted(paths, key=len):
            if not self._entry_path(path) or not os.path.isdir(path):
                continue
            item = self._item_for(path)
            if item is None or item is self._model.invisibleRootItem():
                continue
            self._load(item)
            index = self._proxy.mapFromSource(item.index())
            if index.isValid():
                self.view.expand(index)

    def _expanded_paths(self, visible_only: bool = False) -> set[str]:
        """Folders expanded in the view; with visible_only, not those inside
        a collapsed folder."""
        found: set[str] = set()

        def walk(item):
            for row in range(item.rowCount()):
                child = item.child(row)
                if not child.data(_IS_DIR_ROLE) or not child.data(_LOADED_ROLE):
                    continue
                index = self._proxy.mapFromSource(child.index())
                is_expanded = index.isValid() and self.view.isExpanded(index)
                if is_expanded:
                    found.add(child.data(_PATH_ROLE))
                if is_expanded or not visible_only:
                    walk(child)

        if self._root:
            walk(self._model.invisibleRootItem())
        return found

    def _entry_path(self, path: str) -> str:
        """`path` spelled under the root, or '' when it is not in the
        project. Its parent must really be inside the root (realpath), so a
        symlinked folder cannot lead outside; the entry itself may be a
        symlink (deleting or renaming it touches only the link)."""
        if not self._root or not path:
            return ""
        absolute = os.path.abspath(path)
        if not _is_under(_norm(self._root), _norm(absolute)):
            if not is_inside(self._root, absolute):
                return ""
            rel = os.path.relpath(os.path.realpath(absolute), os.path.realpath(self._root))
            absolute = self._root if rel == "." else os.path.join(self._root, rel)
        if _norm(absolute) == _norm(self._root):
            return self._root
        if not is_inside(self._root, os.path.dirname(absolute)):
            return ""
        return absolute

    def _new_target(self, directory: str, name: str) -> str:
        name = validate_name(name)
        if not self._root:
            raise ValueError("No project folder is open.")
        folder = self._entry_path(directory)
        if not folder or not is_inside(self._root, folder):
            raise ValueError(f"{directory} is not inside the project folder.")
        if not os.path.isdir(folder):
            raise ValueError(f"{directory} is not a folder.")
        target = os.path.join(folder, name)
        if os.path.lexists(target):
            raise FileExistsError(f"'{name}' already exists.")
        return target

    @staticmethod
    def _moved(path: str, old: str, new: str) -> str:
        if path == old:
            return new
        if path.startswith(old + os.sep):
            return new + path[len(old):]
        return path

    # ------------------------------------------------------------ watching

    def _sync_watcher(self, *_args) -> None:
        """Watches the root and the folders a user can see into, nothing else."""
        wanted = {_norm(p): p for p in self._expanded_paths(visible_only=True)}
        if self._root:
            wanted[_norm(self._root)] = self._root
        watched = {_norm(p): p for p in self._watcher.directories()}
        stale = [p for key, p in watched.items() if key not in wanted]
        new = [p for key, p in wanted.items() if key not in watched and os.path.isdir(p)]
        if stale:
            self._watcher.removePaths(stale)
        if new:
            self._watcher.addPaths(new)

    def _unwatch_under(self, path: str) -> None:
        base = _norm(path)
        doomed = [p for p in self._watcher.directories() if _is_under(base, _norm(p))]
        if doomed:
            self._watcher.removePaths(doomed)

    def _on_directory_changed(self, _path: str) -> None:
        # Not restarted on every event: a folder that keeps changing (a
        # build writing into it) still refreshes every _WATCH_DELAY_MS.
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _on_refresh_timer(self) -> None:
        self.refresh()

    # ------------------------------------------------------------ the view

    def _show_view(self, has_root: bool) -> None:
        self.view.setVisible(has_root)
        self.filter_edit.setEnabled(has_root)
        self.empty_label.setVisible(not has_root)

    def _on_expanded(self, index) -> None:
        item = self._model.itemFromIndex(self._proxy.mapToSource(index))
        if item is not None:
            self._load(item)
        self._sync_watcher()

    def _on_filter_text(self, text: str) -> None:
        needle = text.strip()
        if needle == self._needle:
            return
        if needle and not self._needle:
            self._saved_expansion = self._expanded_paths()
        self._needle = needle
        if needle:
            self._load_all()
            self._proxy.setFilterFixedString(needle)
            self.view.expandAll()
        else:
            self._proxy.setFilterFixedString("")
            self.view.collapseAll()
            self._restore_expansion(self._saved_expansion)
            self._saved_expansion = set()
        self._sync_watcher()

    def _activate(self, index) -> None:
        path = index.data(_PATH_ROLE)
        if not path:
            return
        if index.data(_IS_DIR_ROLE):
            self.view.setExpanded(index, not self.view.isExpanded(index))
        else:
            self.fileActivated.emit(path)

    def eventFilter(self, watched, event):
        if (watched is self.view and event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self.view.state() != QAbstractItemView.EditingState):
            index = self.view.currentIndex()
            if index.isValid():
                self._activate(index)
                return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------ the context menu

    def _show_menu(self, pos) -> None:
        if not self._root:
            return
        path = self.view.indexAt(pos).data(_PATH_ROLE) or ""
        folder = path if os.path.isdir(path) else (os.path.dirname(path) if path else self._root)
        subject = path or self._root
        shown = subject if os.path.isdir(subject) else os.path.dirname(subject)
        menu = QMenu(self)
        menu.addAction("New file...", lambda: self._ask_new(folder, False))
        menu.addAction("New folder...", lambda: self._ask_new(folder, True))
        if path:
            menu.addSeparator()
            menu.addAction("Rename...", lambda: self._ask_rename(path))
            menu.addAction("Delete", lambda: self._ask_delete(path))
        menu.addSeparator()
        menu.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(subject))
        menu.addAction("Reveal in file manager",
                       lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(shown)))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _ask_new(self, folder: str, is_folder: bool) -> None:
        title = "New folder" if is_folder else "New file"
        name, ok = QInputDialog.getText(self, title, f"Name (in {relative_path(self._root, folder)}):")
        if not ok:
            return
        try:
            (self.new_folder if is_folder else self.new_file)(folder, name)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, title, str(exc))

    def _ask_rename(self, path: str) -> None:
        old = os.path.basename(path)
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=old)
        if not ok or name.strip() == old:
            return
        try:
            self.rename(path, name)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Rename", str(exc))

    def _ask_delete(self, path: str) -> None:
        name = os.path.basename(path)
        what = f"the folder '{name}' and everything in it" if os.path.isdir(path) else f"'{name}'"
        answer = QMessageBox.question(self, "Delete", f"Delete {what}?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            self.delete(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Delete", str(exc))
