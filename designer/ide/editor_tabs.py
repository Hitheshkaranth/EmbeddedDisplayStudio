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

import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QTabBar, QTabWidget, QVBoxLayout, QWidget,
)

from designer.ui.code_editor import CodeEditor


def relative_path(root: str, path: str) -> str:
    """path relative to root with '/' separators."""
    try:
        from designer.ide.project_files import relative_path as _rp
        return _rp(root, path)
    except ImportError:
        try:
            return os.path.relpath(path, root).replace(os.sep, "/")
        except ValueError:
            return path.replace(os.sep, "/")


def _is_inside_safe(root: str, path: str) -> bool:
    """Check path is under root using realpath."""
    try:
        from designer.ide.project_files import is_inside as _is
        return _is(root, path)
    except ImportError:
        try:
            real_root = os.path.realpath(root)
            real_path = os.path.realpath(path)
            return real_path == real_root or real_path.startswith(real_root + os.sep)
        except (ValueError, TypeError):
            return False


class _Banner(QWidget):
    """A banner above the editor showing a disk-change notice."""

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self._filename = filename
        self._reload_button = None
        self._keep_button = None
        self._label = QLabel(f"{filename} changed on disk.")
        self._reload_button = QLabel("[Reload]")
        self._reload_button.setCursor(Qt.PointingHandCursor)
        self._keep_button = QLabel("[Keep mine]")
        self._keep_button.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._label)
        layout.addStretch()
        layout.addWidget(self._keep_button)
        layout.addWidget(self._reload_button)
        self.setStyleSheet("background: #2d1f00; color: #e6a800; padding: 2px 6px; font-size: 11px;")

    def reloadClicked(self):
        pass

    def keepClicked(self):
        pass


class _FileWatcher(QWidget):
    """A QWidget that holds a QFileSystemWatcher and exposes a fileChanged
    Signal so EditorTabs can connect without importing Qt internals."""

    fileChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QFileSystemWatcher
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(
            lambda p: self.fileChanged.emit(p)
        )

    def addFile(self, path: str) -> None:
        try:
            if path not in self._watcher.files():
                self._watcher.addPath(path)
        except RuntimeError:
            pass

    def removeFile(self, path: str) -> None:
        try:
            self._watcher.removePath(path)
        except (RuntimeError, AttributeError):
            pass

    def files(self):
        try:
            return self._watcher.files()
        except AttributeError:
            return []


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
        self.setTabsClosable(True)
        self._root: str = ""
        self._path_to_index: dict[str, int] = {}
        self._saved: dict[str, str] = {}
        self._pinned_handlers: dict[int, dict] = {}
        self._watcher = _FileWatcher(self)
        self._watcher.fileChanged.connect(self.file_changed_on_disk)
        self._last_save_time: float = 0.0
        self._banners: dict[str, _Banner] = {}
        self._tab_page_map: dict[int, QWidget] = {}
        self.tabCloseRequested.connect(self._on_tab_close)

        _save = QShortcut(QKeySequence("Ctrl+S"), self)
        _save.setContext(Qt.WidgetWithChildrenShortcut)
        _save.activated.connect(self.save)
        _save_all = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        _save_all.setContext(Qt.WidgetWithChildrenShortcut)
        _save_all.activated.connect(self.save_all)
        _close = QShortcut(QKeySequence("Ctrl+W"), self)
        _close.setContext(Qt.WidgetWithChildrenShortcut)
        _close.activated.connect(lambda: self.close_file(self.current_path()))
        _undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        _undo.setContext(Qt.WidgetWithChildrenShortcut)
        _undo.activated.connect(self.undo)
        _redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        _redo.setContext(Qt.WidgetWithChildrenShortcut)
        _redo.activated.connect(self.redo)
        _redo2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        _redo2.setContext(Qt.WidgetWithChildrenShortcut)
        _redo2.activated.connect(self.redo)

    # ---------------------------------------------------------- project

    def set_root(self, root: str) -> None:
        old_root = self._root
        self._root = os.path.realpath(root) if root else ""
        self._path_to_index.clear()
        self._saved.clear()
        self._pinned_handlers.clear()
        self._banners.clear()
        self._tab_page_map.clear()
        if old_root:
            for p in list(self._watcher.files()):
                self._watcher.removeFile(p)
        if self._root:
            self._watcher.addFile(self._root)
        self.currentFileChanged.emit("")

    def root(self) -> str:
        return self._root

    # ---------------------------------------------------------- tabs

    def add_pinned(self, widget, title: str, icon_name: str = "",
                   handlers: dict | None = None) -> int:
        idx = self.count()
        self.insertTab(idx, widget, title)
        self._path_to_index[""] = idx
        self._saved[""] = ""
        if handlers is not None:
            self._pinned_handlers[idx] = handlers
        tabBar = self.tabBar()
        for i in range(self.count()):
            tabBar.setTabButton(i, QTabBar.RightSide, None)
            tabBar.setTabButton(i, QTabBar.LeftSide, None)
        return idx

    def open_file(self, path: str, line: int = 0):
        path = os.path.realpath(path)
        if path in self._path_to_index:
            self.setCurrentIndex(self._path_to_index[path])
            return self.editor_for(path)
        if self._root and not _is_inside_safe(self._root, path):
            self.message.emit(f"{os.path.basename(path)} is outside the project root")
            return None
        try:
            from designer.ide.project_files import read_text, language_for
            tf = read_text(path)
        except Exception as exc:
            self.message.emit(f"Cannot open {os.path.basename(path)}: {exc}")
            return None
        editor = CodeEditor()
        editor.set_language(language_for(path))
        editor.set_code(tf.text, keep_scroll=True)
        page = self._make_tab_page(editor)
        idx = self.count()
        self.insertTab(idx, page, os.path.basename(path))
        self._tab_page_map[idx] = page
        self.setTabToolTip(idx, relative_path(self._root, path) if self._root else path)
        self._path_to_index[path] = idx
        self._saved[path] = tf.text
        self._watcher.addFile(path)
        self.setCurrentIndex(idx)
        if line >= 1:
            editor.go_to_line(line)
        return editor

    def _make_tab_page(self, editor):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(editor)
        return page

    def editor_for(self, path: str):
        idx = self._path_to_index.get(path)
        if idx is not None:
            w = self.widget(idx)
            if w is not None and isinstance(w, QWidget) and w.layout() is not None:
                if w.layout().count() > 0:
                    child = w.layout().itemAt(0)
                    if child is not None:
                        return child.widget()
            return w
        return None

    def open_paths(self) -> list[str]:
        return [p for p, i in self._path_to_index.items() if p != "" and i < self.count()]

    def current_path(self) -> str:
        idx = self.currentIndex()
        if idx < 0:
            return ""
        for p, i in self._path_to_index.items():
            if i == idx:
                return p
        return ""

    def is_dirty(self, path: str) -> bool:
        saved = self._saved.get(path)
        if saved is None:
            return False
        editor = self.editor_for(path)
        if editor is None:
            return False
        return editor.code() != saved

    def dirty_paths(self) -> list[str]:
        return [p for p in self._path_to_index if p and self.is_dirty(p)]

    def save(self, path: str | None = None) -> bool:
        if path is None:
            path = self.current_path()
        if path == "":
            idx = self._path_to_index.get("")
            if idx is not None and idx < self.count():
                h = self._pinned_handlers.get(idx, {})
                fn = h.get("save")
                if fn is not None:
                    return bool(fn())
            return False
        editor = self.editor_for(path)
        if editor is None:
            return False
        text = editor.code()
        saved = self._saved.get(path)
        if saved == text:
            return True
        try:
            from designer.ide.project_files import write_text
            write_text(path, text)
            self._saved[path] = text
            self._last_save_time = time.monotonic()
            self._update_tab_title(path)
            self.dirtyChanged.emit(path, False)
            self.fileSaved.emit(path)
            return True
        except Exception as exc:
            self.message.emit(f"Cannot save {os.path.basename(path)}: {exc}")
            return False

    def save_all(self) -> bool:
        paths = self.dirty_paths()
        if not paths:
            return True
        all_ok = True
        for p in paths:
            if not self.save(p):
                all_ok = False
        return all_ok

    def close_file(self, path: str, force: bool = False) -> bool:
        if path == "":
            return False
        idx = self._path_to_index.get(path)
        if idx is None or idx >= self.count():
            return True
        if self.is_dirty(path) and not force:
            ans = self._ask_unsaved(path)
            if ans == self.CANCEL:
                return False
            if ans == self.SAVE:
                if not self.save(path):
                    return False
        self._remove_tab(idx, path)
        return True

    def close_all(self, force: bool = False) -> bool:
        file_paths = list(self._path_to_index.keys())
        for p in file_paths:
            if p == "":
                continue
            idx = self._path_to_index.get(p)
            if idx is None or idx >= self.count():
                continue
            if self.is_dirty(p) and not force:
                ans = self._ask_unsaved(p)
                if ans == self.CANCEL:
                    return False
                if ans == self.SAVE:
                    if not self.save(p):
                        return False
        file_paths = list(self._path_to_index.keys())
        for p in file_paths:
            if p == "":
                continue
            idx = self._path_to_index.get(p)
            if idx is not None and idx < self.count():
                self._remove_tab(idx, p)
        return True

    def undo(self) -> None:
        path = self.current_path()
        if path:
            editor = self.editor_for(path)
            if editor is not None:
                editor.undo()
        else:
            idx = self._path_to_index.get("")
            if idx is not None and idx < self.count():
                h = self._pinned_handlers.get(idx, {})
                fn = h.get("undo")
                if fn is not None:
                    fn()

    def redo(self) -> None:
        path = self.current_path()
        if path:
            editor = self.editor_for(path)
            if editor is not None:
                editor.redo()
        else:
            idx = self._path_to_index.get("")
            if idx is not None and idx < self.count():
                h = self._pinned_handlers.get(idx, {})
                fn = h.get("redo")
                if fn is not None:
                    fn()

    # ---------------------------------------------------------- disk events

    def file_changed_on_disk(self, path: str) -> None:
        if path not in self._path_to_index:
            return
        if not os.path.isfile(path):
            return
        elapsed = time.monotonic() - self._last_save_time
        if elapsed < 2.0:
            self._last_save_time = 0.0
        try:
            from designer.ide.project_files import read_text
            tf = read_text(path)
        except Exception:
            return
        disk_text = tf.text
        saved = self._saved.get(path)
        if saved == disk_text:
            return
        idx = self._path_to_index.get(path)
        if idx is None or idx >= self.count():
            return
        if self.is_dirty(path):
            if path not in self._banners:
                self._show_banner(path)
        else:
            self._saved[path] = disk_text
            editor = self.editor_for(path)
            if editor is not None:
                editor.set_code(disk_text, keep_scroll=True)

    def has_banner(self, path: str) -> bool:
        return path in self._banners

    def resolve_banner(self, path: str, reload: bool) -> None:
        banner = self._banners.pop(path, None)
        if banner is not None:
            idx = self._path_to_index.get(path)
            if idx is not None:
                page = self._tab_page_map.get(idx)
                if page is not None and page.layout() is not None:
                    while page.layout().count():
                        child = page.layout().takeAt(0)
                        if child.widget() is not None:
                            child.widget().deleteLater()
            banner.deleteLater()
        if reload:
            try:
                from designer.ide.project_files import read_text
                tf = read_text(path)
                self._saved[path] = tf.text
                editor = self.editor_for(path)
                if editor is not None:
                    editor.set_code(tf.text, keep_scroll=True)
            except Exception:
                pass
            else:
                self.dirtyChanged.emit(path, False)
        else:
            if path in self._path_to_index:
                editor = self.editor_for(path)
                if editor is not None:
                    self._saved[path] = editor.code()
                    if not self.is_dirty(path):
                        self.dirtyChanged.emit(path, False)

    def file_renamed(self, old: str, new: str) -> None:
        old = os.path.realpath(old)
        new = os.path.realpath(new)
        idx = self._path_to_index.get(old)
        if idx is not None and idx < self.count():
            self._retarget_tab(old, new, idx)
        else:
            retargeted = []
            for p in list(self._path_to_index.keys()):
                if p == old or (self._root and p.startswith(old + os.sep)):
                    if p == old:
                        new_p = new
                    else:
                        rel = os.path.relpath(p, old)
                        new_p = os.path.join(new, rel)
                    retargeted.append((p, new_p))
            for p, new_p in retargeted:
                self._retarget_tab(p, new_p, self._path_to_index[p])

    def _retarget_tab(self, old: str, new: str, idx: int) -> None:
        del self._path_to_index[old]
        self._path_to_index[new] = idx
        self._saved[new] = self._saved.pop(old, "")
        self._watcher.removeFile(old)
        self._watcher.addFile(new)
        self._banners.pop(old, None)
        self.setTabText(idx, os.path.basename(new))
        self.setTabToolTip(idx, relative_path(self._root, new) if self._root else new)

    def file_deleted(self, path: str) -> None:
        path = os.path.realpath(path)
        for p in list(self._path_to_index.keys()):
            if p != path:
                continue
            idx = self._path_to_index.get(p)
            if idx is not None and idx < self.count():
                if not self.is_dirty(p):
                    self._watcher.removeFile(p)
                    self._remove_tab(idx, p)
                else:
                    self._saved[p] = "DELETED_MARKER"

    # ---------------------------------------------------------- agent context

    def selection_context(self) -> dict:
        path = self.current_path()
        if path == "":
            return {}
        editor = self.editor_for(path)
        if editor is None:
            return {}
        cursor = editor.textCursor()
        selected = cursor.selectedText()
        if selected:
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            start_block = cursor.document().findBlock(start).blockNumber()
            end_block = cursor.document().findBlock(end).blockNumber()
        else:
            line_num = cursor.blockNumber()
            start_block = line_num
            end_block = line_num
        ctx = {
            "path": path,
            "relative": relative_path(self._root, path) if self._root else path,
            "language": editor._language,
            "cursor_line": cursor.blockNumber() + 1,
            "start_line": start_block + 1,
            "end_line": end_block + 1,
            "text": selected,
        }
        return ctx

    def apply_theme(self, theme: str) -> None:
        dark = theme == "dark"
        for p, idx in self._path_to_index.items():
            if p == "":
                continue
            editor = self.editor_for(p)
            if editor is not None:
                editor.apply_theme(theme)
        for banner in self._banners.values():
            if dark:
                banner.setStyleSheet(
                    "background: #2d1f00; color: #e6a800; padding: 2px 6px; font-size: 11px;"
                )
            else:
                banner.setStyleSheet(
                    "background: #fff8e1; color: #7c6900; padding: 2px 6px; font-size: 11px;"
                )
        self.setStyleSheet(
            "QTabWidget::pane { border: none; background: transparent; }"
            "QTabBar::tab { background: #1a1e28; color: #8b949e; padding: 4px 12px; }"
            "QTabBar::tab:selected { background: #0b0f14; color: #e6edf3; }"
            "QTabBar::tab:!selected { margin-top: 2px; }"
            "QLabel { color: inherit; }"
            if dark else
            "QTabBar::tab { background: #f3f4f6; color: #6b7280; padding: 4px 12px; }"
            "QTabBar::tab:selected { background: #ffffff; color: #111827; }"
            "QTabBar::tab:!selected { margin-top: 2px; }"
            "QLabel { color: inherit; }"
        )

    # ---------------------------------------------------------- hooks

    def _ask_unsaved(self, path: str) -> str:
        return self.DISCARD

    # ---------------------------------------------------------- private

    def _on_tab_close(self, idx: int) -> None:
        path = ""
        for p, i in self._path_to_index.items():
            if i == idx:
                path = p
                break
        if path and path != "":
            self.close_file(path)

    def _remove_tab(self, idx: int, path: str) -> None:
        self._watcher.removeFile(path)
        self._watcher.removeFile(self._root)
        self._banners.pop(path, None)
        del self._path_to_index[path]
        page = self._tab_page_map.pop(idx, None)
        if page is not None:
            page.deleteLater()
        self.removeTab(idx)
        self.currentFileChanged.emit(self.current_path())
        for p, saved in self._saved.items():
            if saved == "DELETED_MARKER":
                if not self.is_dirty(p):
                    continue

    def _update_tab_title(self, path: str) -> None:
        idx = self._path_to_index.get(path)
        if idx is not None:
            self.setTabText(idx, os.path.basename(path))

    def _show_banner(self, path: str) -> None:
        if path in self._banners:
            return
        idx = self._path_to_index.get(path)
        if idx is None:
            return
        page = self._tab_page_map.get(idx)
        if page is None or page.layout() is None:
            return
        editor = self.editor_for(path)
        if editor is None:
            return
        filename = os.path.basename(path)
        banner = _Banner(filename, page)
        reload_clicked = lambda b=banner: (
            self.resolve_banner(path, True),
            b.deleteLater()
        )
        keep_clicked = lambda b=banner: (
            self.resolve_banner(path, False),
            b.deleteLater()
        )
        banner._reload_button.clicked.connect(reload_clicked)
        banner._keep_button.clicked.connect(keep_clicked)
        layout = page.layout()
        layout.insertWidget(0, banner)
        self._banners[path] = banner

    def _find_page_for(self, path: str) -> QWidget | None:
        idx = self._path_to_index.get(path)
        if idx is not None:
            return self._tab_page_map.get(idx)
        return None

    def _now(self) -> float:
        return time.monotonic()