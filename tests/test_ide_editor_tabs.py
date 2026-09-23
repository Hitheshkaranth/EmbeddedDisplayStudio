"""designer/ide/editor_tabs.py and the Python highlighter -- W2's gate.

FROZEN: the tests below are the minimum W2 must pass; add more in a class
below them, never change these.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from designer.ide.editor_tabs import EditorTabs  # noqa: E402
from designer.ui.code_editor import CodeEditor, DARK_PALETTE, PythonHighlighter  # noqa: E402


def _type(editor, text):
    editor.setFocus()
    QTest.keyClicks(editor, text)


class EditorTabsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-tabs-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.tabs = EditorTabs()
        self.tabs.resize(800, 500)
        self.tabs.show()
        self.addCleanup(self.tabs.deleteLater)
        self.tabs.set_root(self.dir)
        self.messages = []
        self.tabs.message.connect(self.messages.append)
        self.pinned_calls = []
        self.pinned = QLabel("design")
        self.tabs.add_pinned(self.pinned, "Design", handlers={
            "save": lambda: self.pinned_calls.append("save") or True,
            "undo": lambda: self.pinned_calls.append("undo"),
            "redo": lambda: self.pinned_calls.append("redo"),
        })

    def _file(self, rel, data: bytes):
        path = os.path.join(self.dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_open_file_and_language(self):
        c = self._file("src/main.c", b"int main(void)\n{\n  return 0;\n}\n")
        editor = self.tabs.open_file(c, line=3)
        self.assertIsInstance(editor, CodeEditor)
        self.assertEqual(editor.code(), "int main(void)\n{\n  return 0;\n}\n")
        self.assertEqual(editor._language, "c")
        self.assertEqual(editor.textCursor().blockNumber(), 2)
        self.assertEqual(self.tabs.current_path(), c)
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "main.c")
        self.assertEqual(self.tabs.tabToolTip(self.tabs.currentIndex()), "src/main.c")
        # Opening again switches, no second tab.
        self.tabs.setCurrentWidget(self.pinned)
        self.assertIs(self.tabs.open_file(c), editor)
        self.assertEqual(self.tabs.open_paths(), [c])
        self.assertEqual(self.tabs.count(), 2)

    def test_refuses_binary_and_outside(self):
        png = self._file("logo.png", b"\x89PNG\x00\x00")
        self.assertIsNone(self.tabs.open_file(png))
        self.assertTrue(self.messages)
        outside = tempfile.NamedTemporaryFile(suffix=".c", delete=False)
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        self.assertIsNone(self.tabs.open_file(outside.name))
        self.assertEqual(self.tabs.open_paths(), [])

    def test_dirty_title_and_back_to_clean(self):
        path = self._file("a.py", b"x = 1\n")
        editor = self.tabs.open_file(path)
        changes = []
        self.tabs.dirtyChanged.connect(lambda p, d: changes.append((p, d)))
        editor.moveCursor(QTextCursor.End)
        _type(editor, "y")
        self.assertTrue(self.tabs.is_dirty(path))
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "a.py *")
        QTest.keyClick(editor, Qt.Key_Backspace)
        self.assertFalse(self.tabs.is_dirty(path))
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "a.py")
        self.assertEqual(changes, [(path, True), (path, False)])

    def test_ctrl_s_saves_keeping_newlines(self):
        path = self._file("w.c", b"one\r\ntwo\r\n")
        editor = self.tabs.open_file(path)
        saved = []
        self.tabs.fileSaved.connect(saved.append)
        editor.moveCursor(QTextCursor.End)
        _type(editor, "three")
        QTest.keyClick(editor, Qt.Key_S, Qt.ControlModifier)
        self.assertEqual(self._read(path), b"one\r\ntwo\r\nthree")
        self.assertFalse(self.tabs.is_dirty(path))
        self.assertEqual(saved, [path])

    def test_ctrl_z_and_ctrl_y(self):
        path = self._file("u.txt", b"abc")
        editor = self.tabs.open_file(path)
        editor.moveCursor(QTextCursor.End)
        _type(editor, "d")
        self.assertEqual(editor.code(), "abcd")
        QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(editor.code(), "abc")
        self.assertFalse(self.tabs.is_dirty(path))
        QTest.keyClick(editor, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(editor.code(), "abcd")
        QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(editor.code(), "abcd")
        self.assertEqual(self.pinned_calls, [], "keys in a file editor never reach the pinned tab")

    def test_undo_history_survives_save_and_tab_switch(self):
        a = self._file("a.txt", b"a")
        b = self._file("b.txt", b"b")
        ea = self.tabs.open_file(a)
        ea.moveCursor(QTextCursor.End)
        _type(ea, "1")
        self.assertTrue(self.tabs.save())
        self.tabs.open_file(b)
        self.tabs.open_file(a)
        self.tabs.undo()
        self.assertEqual(ea.code(), "a")
        self.assertTrue(self.tabs.is_dirty(a))
        self.tabs.redo()
        self.assertEqual(ea.code(), "a1")

    def test_pinned_tab_keys_run_handlers(self):
        self.tabs.setCurrentWidget(self.pinned)
        self.pinned.setFocus()
        self.assertEqual(self.tabs.current_path(), "")
        QTest.keyClick(self.pinned, Qt.Key_S, Qt.ControlModifier)
        QTest.keyClick(self.pinned, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(self.pinned, Qt.Key_Y, Qt.ControlModifier)
        QTest.keyClick(self.pinned, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual(self.pinned_calls, ["save", "undo", "redo", "redo"])
        self.assertTrue(self.tabs.save())
        self.assertFalse(self.tabs.tabBar().tabButton(0, self.tabs.tabBar().RightSide) is not None
                         and self.tabs.tabBar().tabButton(0, self.tabs.tabBar().RightSide).isVisible(),
                         "the pinned tab has no close button")

    def test_close_dirty_asks(self):
        path = self._file("c.txt", b"c")
        editor = self.tabs.open_file(path)
        _type(editor, "x")
        answers = [EditorTabs.CANCEL, EditorTabs.SAVE]
        self.tabs._ask_unsaved = lambda p: answers.pop(0)
        self.assertFalse(self.tabs.close_file(path))
        self.assertEqual(self.tabs.open_paths(), [path])
        self.assertTrue(self.tabs.close_file(path))
        self.assertEqual(self.tabs.open_paths(), [])
        self.assertEqual(self._read(path), b"xc")
        editor = self.tabs.open_file(path)
        _type(editor, "y")
        self.tabs._ask_unsaved = lambda p: EditorTabs.DISCARD
        self.assertTrue(self.tabs.close_file(path))
        self.assertEqual(self._read(path), b"xc")

    def test_external_change_reloads_clean_tab(self):
        path = self._file("ext.c", b"old\n")
        editor = self.tabs.open_file(path)
        with open(path, "wb") as f:
            f.write(b"new\n")
        self.tabs.file_changed_on_disk(path)
        self.assertEqual(editor.code(), "new\n")
        self.assertFalse(self.tabs.is_dirty(path))
        self.assertFalse(self.tabs.has_banner(path))

    def test_external_change_detected_by_watcher(self):
        path = self._file("watch.c", b"old\n")
        editor = self.tabs.open_file(path)
        with open(path, "wb") as f:
            f.write(b"watched\n")
        waited = 0
        while editor.code() != "watched\n" and waited < 3000:
            QTest.qWait(100)
            waited += 100
        self.assertEqual(editor.code(), "watched\n")

    def test_external_change_on_dirty_tab_shows_banner(self):
        path = self._file("d.c", b"disk\n")
        editor = self.tabs.open_file(path)
        editor.moveCursor(QTextCursor.End)
        _type(editor, "mine")
        with open(path, "wb") as f:
            f.write(b"theirs\n")
        self.tabs.file_changed_on_disk(path)
        self.assertTrue(self.tabs.has_banner(path))
        self.assertEqual(editor.code(), "disk\nmine")
        self.tabs.resolve_banner(path, reload=False)
        self.assertFalse(self.tabs.has_banner(path))
        self.assertTrue(self.tabs.is_dirty(path))
        with open(path, "wb") as f:
            f.write(b"theirs again\n")
        self.tabs.file_changed_on_disk(path)
        self.tabs.resolve_banner(path, reload=True)
        self.assertEqual(editor.code(), "theirs again\n")
        self.assertFalse(self.tabs.is_dirty(path))

    def test_own_save_is_not_an_external_change(self):
        path = self._file("s.c", b"a\n")
        editor = self.tabs.open_file(path)
        editor.moveCursor(QTextCursor.End)
        _type(editor, "b")
        self.tabs.save()
        self.tabs.file_changed_on_disk(path)
        QTest.qWait(300)
        self.assertFalse(self.tabs.has_banner(path))
        self.assertEqual(editor.code(), "a\nb")

    def test_rename_and_delete(self):
        path = self._file("r.c", b"r\n")
        self.tabs.open_file(path)
        new = os.path.join(self.dir, "renamed.c")
        os.rename(path, new)
        self.tabs.file_renamed(path, new)
        self.assertEqual(self.tabs.open_paths(), [new])
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "renamed.c")
        os.remove(new)
        self.tabs.file_deleted(new)
        self.assertEqual(self.tabs.open_paths(), [])

    def test_folder_rename_retargets_children(self):
        path = self._file("pkg/m.py", b"m\n")
        self.tabs.open_file(path)
        old_dir, new_dir = os.path.join(self.dir, "pkg"), os.path.join(self.dir, "lib")
        os.rename(old_dir, new_dir)
        self.tabs.file_renamed(old_dir, new_dir)
        self.assertEqual(self.tabs.open_paths(), [os.path.join(new_dir, "m.py")])

    def test_selection_context(self):
        path = self._file("src/sel.c", b"l1\nl2\nl3\nl4\n")
        editor = self.tabs.open_file(path, line=2)
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["path"], ctx["relative"], ctx["language"]), (path, "src/sel.c", "c"))
        self.assertEqual((ctx["cursor_line"], ctx["start_line"], ctx["end_line"], ctx["text"]), (2, 2, 2, ""))
        cursor = editor.textCursor()
        cursor.setPosition(editor.document().findBlockByNumber(1).position())
        cursor.setPosition(editor.document().findBlockByNumber(2).position() + 2, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["start_line"], ctx["end_line"], ctx["text"]), (2, 3, "l2\nl3"))
        self.tabs.setCurrentWidget(self.pinned)
        self.assertEqual(self.tabs.selection_context(), {})

    def test_current_file_changed_signal(self):
        a = self._file("a.c", b"a")
        got = []
        self.tabs.currentFileChanged.connect(got.append)
        self.tabs.open_file(a)
        self.tabs.setCurrentWidget(self.pinned)
        self.assertEqual(got[-2:], [a, ""])

    def test_save_all(self):
        a, b = self._file("a.c", b"a"), self._file("b.c", b"b")
        for p in (a, b):
            _type(self.tabs.open_file(p), "+")
        self.assertEqual(sorted(self.tabs.dirty_paths()), sorted([a, b]))
        self.assertTrue(self.tabs.save_all())
        self.assertEqual((self._read(a), self._read(b)), (b"+a", b"+b"))
        self.assertEqual(self.tabs.dirty_paths(), [])

    def test_themes(self):
        self._file("t.c", b"t")
        self.tabs.open_file(os.path.join(self.dir, "t.c"))
        self.tabs.apply_theme("light")
        self.tabs.apply_theme("dark")


class PythonHighlighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _formats(self, text):
        editor = CodeEditor()
        self.addCleanup(editor.deleteLater)
        editor.set_language("python")
        editor.set_code(text)
        self.assertIsInstance(editor._highlighter, PythonHighlighter)
        out = []
        block = editor.document().begin()
        while block.isValid():
            spans = {}
            for r in block.layout().formats():
                spans[block.text()[r.start:r.start + r.length]] = r.format.foreground().color().name()
            out.append(spans)
            block = block.next()
        return out

    def test_tokens(self):
        spans = self._formats('@dataclass\ndef f(x):  # note "q"\n    return "a # b" if x else None\n')
        self.assertEqual(spans[0].get("@dataclass"), DARK_PALETTE["property"])
        self.assertEqual(spans[1].get("def"), DARK_PALETTE["keyword"])
        self.assertEqual(spans[1].get('# note "q"'), DARK_PALETTE["comment"])
        self.assertEqual(spans[2].get('"a # b"'), DARK_PALETTE["string"])
        self.assertEqual(spans[2].get("return"), DARK_PALETTE["keyword"])

    def test_triple_quoted_spans_lines(self):
        spans = self._formats('x = """one\ntwo # not a comment\nthree"""\ny = 1\n')
        self.assertEqual(spans[1].get("two # not a comment"), DARK_PALETTE["string"])
        self.assertEqual(spans[3].get("1"), DARK_PALETTE["number"])



# ------------------------------------------------------------ W2 QC tests
# Below the frozen classes: added by the W2 QC pass, not part of the gate's
# minimum.

import tempfile as _tempfile  # noqa: E402

from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QTabBar, QTabWidget  # noqa: E402

from designer.ide import project_files as _pf  # noqa: E402
from designer.ui.code_editor import LIGHT_PALETTE  # noqa: E402

_REAL_PROJECT_FILES = {}


# STAND-IN until W1 lands: minimal, correct versions of the project_files
# helpers EditorTabs uses. setUpModule installs one only while the real
# function still raises NotImplementedError, so the real module wins as soon
# as it is there.
def _stand_in_language_for(path):
    return _pf.EXTENSION_LANGUAGES.get(os.path.splitext(path)[1].lower(), "plain")


def _stand_in_is_inside(root, path):
    root, path = os.path.realpath(root), os.path.realpath(path)
    try:
        return os.path.normcase(os.path.commonpath([root, path])) == os.path.normcase(root)
    except ValueError:                      # different drives
        return False


def _stand_in_relative_path(root, path):
    if _stand_in_is_inside(root, path):
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root)).replace(os.sep, "/")
    return os.path.abspath(path).replace(os.sep, "/")


def _stand_in_read_text(path):
    name = os.path.basename(path)
    if not os.path.isfile(path):
        raise _pf.FileReadError(f"Cannot open {name}: not a file")
    if os.path.getsize(path) > _pf.MAX_TEXT_BYTES:
        raise _pf.FileReadError(f"Cannot open {name}: larger than 2 MiB")
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        raise _pf.FileReadError(f"Cannot open {name}: {exc.strerror}") from exc
    if b"\0" in raw[:_pf.BINARY_SNIFF_BYTES]:
        raise _pf.FileReadError(f"Cannot open {name}: binary file")
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding, text = "latin-1", raw.decode("latin-1")
    first = text.find("\n")
    newline = "\r\n" if first > 0 and text[first - 1] == "\r" else "\n"
    return _pf.TextFile(text.replace("\r\n", "\n").replace("\r", "\n"), encoding, newline)


def _stand_in_write_text(path, text, encoding="utf-8", newline="\n"):
    data = text.replace("\n", newline).encode(encoding)
    fd, tmp = _tempfile.mkstemp(prefix=".", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _raises_not_implemented(call):
    try:
        call()
    except NotImplementedError:
        return True
    except Exception:                       # implemented: it just did not like the probe
        return False
    return False


def setUpModule():
    nowhere = os.path.join(_tempfile.gettempdir(), "ide-w2-no-such-dir", "f.txt")
    probes = {
        "language_for": (_stand_in_language_for, lambda: _pf.language_for("a.c")),
        "is_inside": (_stand_in_is_inside, lambda: _pf.is_inside(os.sep, os.sep)),
        "relative_path": (_stand_in_relative_path, lambda: _pf.relative_path(os.sep, os.sep)),
        "read_text": (_stand_in_read_text, lambda: _pf.read_text(nowhere)),
        "write_text": (_stand_in_write_text, lambda: _pf.write_text(nowhere, "")),
    }
    for name, (stand_in, probe) in probes.items():
        if _raises_not_implemented(probe):
            _REAL_PROJECT_FILES[name] = getattr(_pf, name)
            setattr(_pf, name, stand_in)


def tearDownModule():
    for name, real in _REAL_PROJECT_FILES.items():
        setattr(_pf, name, real)
    _REAL_PROJECT_FILES.clear()


def _spans(text, theme="dark"):
    """{span text: colour} per line, as the frozen highlighter test reads them."""
    editor = CodeEditor()
    editor.set_language("python")
    editor.apply_theme(theme)
    editor.set_code(text)
    out = []
    block = editor.document().begin()
    while block.isValid():
        spans = {}
        for r in block.layout().formats():
            spans[block.text()[r.start:r.start + r.length]] = r.format.foreground().color().name()
        out.append(spans)
        block = block.next()
    editor.deleteLater()
    return out


class EditorTabsQCTests(unittest.TestCase):
    """W2 QC: the parts of the editor_tabs contract the gate does not pin."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-tabs-qc-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.tabs = EditorTabs()
        self.tabs.resize(800, 500)
        self.tabs.show()
        self.addCleanup(self.tabs.deleteLater)
        self.tabs.set_root(self.dir)
        self.messages = []
        self.tabs.message.connect(self.messages.append)
        self.pinned_calls = []
        self.pinned = QLabel("design")
        self.tabs.add_pinned(self.pinned, "Design", handlers={
            "save": lambda: self.pinned_calls.append("save") or True,
            "undo": lambda: self.pinned_calls.append("undo"),
            "redo": lambda: self.pinned_calls.append("redo"),
        })

    def _file(self, rel, data: bytes):
        path = os.path.join(self.dir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def _replace_atomically(self, path, data: bytes):
        tmp = path + ".other-tool"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def _wait_for(self, predicate, ms=3000):
        waited = 0
        while not predicate() and waited < ms:
            QTest.qWait(50)
            waited += 50
        return predicate()

    # ---- keys

    def test_one_owner_per_key(self):
        shortcuts = self.tabs.findChildren(QShortcut)
        keys = sorted(s.key().toString() for s in shortcuts)
        self.assertEqual(keys, sorted(["Ctrl+S", "Ctrl+Shift+S", "Ctrl+W", "Ctrl+Z", "Ctrl+Y",
                                       "Ctrl+Shift+Z"]))
        for s in shortcuts:
            self.assertIs(s.parent(), self.tabs)
            self.assertEqual(s.context(), Qt.WidgetWithChildrenShortcut)
        editor = self.tabs.open_file(self._file("k.c", b"k"))
        self.assertEqual(editor.findChildren(QShortcut), [], "the editor adds no shortcuts of its own")
        self.assertEqual(len(self.tabs.findChildren(QShortcut)), 6)

    def test_ctrl_w_and_ctrl_shift_s_keys(self):
        a, b = self._file("a.c", b"a"), self._file("b.c", b"b")
        ea = self.tabs.open_file(a)
        _type(ea, "1")
        eb = self.tabs.open_file(b)
        _type(eb, "2")
        QTest.keyClick(eb, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
        self.assertEqual((self._read(a), self._read(b)), (b"1a", b"2b"))
        QTest.keyClick(eb, Qt.Key_W, Qt.ControlModifier)
        self.assertEqual(self.tabs.open_paths(), [a])
        self.tabs.setCurrentWidget(self.pinned)
        self.pinned.setFocus()
        QTest.keyClick(self.pinned, Qt.Key_W, Qt.ControlModifier)
        self.assertEqual(self.tabs.count(), 2, "Ctrl+W on the pinned tab closes nothing")

    def test_pinned_without_handlers_is_a_no_op(self):
        other = QLabel("other")
        self.tabs.add_pinned(other, "Other")
        self.tabs.setCurrentWidget(other)
        self.assertFalse(self.tabs.save())
        self.tabs.undo()
        self.tabs.redo()
        self.assertEqual(self.pinned_calls, [])

    # ---- dirty state

    def test_dirty_changed_only_on_transitions(self):
        path = self._file("t.txt", b"base")
        editor = self.tabs.open_file(path)
        changes = []
        self.tabs.dirtyChanged.connect(lambda p, d: changes.append(d))
        editor.moveCursor(QTextCursor.End)
        _type(editor, "abc")
        self.assertEqual(changes, [True])
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "t.txt *")
        for _ in range(3):
            QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
            if editor.code() == "base":
                break
        self.assertEqual(editor.code(), "base")
        self.assertEqual(changes, [True, False], "undo back to the saved text is clean")
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "t.txt")
        self.assertEqual(self.tabs.dirty_paths(), [])

    # ---- saving

    def test_save_keeps_bom_crlf_and_latin1(self):
        bom = self._file("bom.c", b"\xef\xbb\xbfa\r\nb\r\n")
        latin = self._file("latin.txt", b"caf\xe9\n")
        for path in (bom, latin):
            editor = self.tabs.open_file(path)
            editor.moveCursor(QTextCursor.End)
            _type(editor, "z")
            self.assertTrue(self.tabs.save())
        self.assertEqual(self._read(bom), b"\xef\xbb\xbfa\r\nb\r\nz")
        self.assertEqual(self._read(latin), b"caf\xe9\nz")

    def test_save_goes_through_write_text_and_failure_keeps_dirty(self):
        path = self._file("w.c", b"w\r\n")
        editor = self.tabs.open_file(path)
        _type(editor, "x")
        calls, saved = [], []
        self.tabs.fileSaved.connect(saved.append)
        real = _pf.write_text

        def failing(*args):
            calls.append(args)
            raise PermissionError(13, "Permission denied")
        _pf.write_text = failing
        try:
            self.assertFalse(self.tabs.save())
        finally:
            _pf.write_text = real
        self.assertEqual(calls, [(path, "xw\n", "utf-8", "\r\n")])
        self.assertTrue(self.tabs.is_dirty(path))
        self.assertEqual(saved, [])
        self.assertIn("Permission denied", self.messages[-1])
        # A failed save on close keeps the tab.
        self.tabs._ask_unsaved = lambda p: EditorTabs.SAVE
        _pf.write_text = failing
        try:
            self.assertFalse(self.tabs.close_file(path))
        finally:
            _pf.write_text = real
        self.assertEqual(self.tabs.open_paths(), [path])
        self.assertEqual(self._read(path), b"w\r\n")

    def test_save_of_a_path_not_open_says_so(self):
        self.assertFalse(self.tabs.save(os.path.join(self.dir, "not-open.c")))
        self.assertTrue(self.messages)

    # ---- watcher

    def test_own_saves_never_show_the_banner(self):
        path = self._file("o.c", b"o\n")
        editor = self.tabs.open_file(path)
        for ch in "abc":
            _type(editor, ch)
            self.assertTrue(self.tabs.save())
            _type(editor, "!")               # dirty again when the watcher reports the save
            QTest.qWait(300)
            self.assertFalse(self.tabs.has_banner(path))
            QTest.keyClick(editor, Qt.Key_Backspace)
        self.assertEqual(editor.code(), "abco\n")

    def test_watcher_follows_atomic_replaces(self):
        path = self._file("r.c", b"one\n")
        editor = self.tabs.open_file(path)
        _type(editor, "0")
        self.assertTrue(self.tabs.save())       # our own atomic replace
        QTest.qWait(200)
        for text in (b"two\n", b"three\n"):
            self._replace_atomically(path, text)
            self.assertTrue(self._wait_for(lambda: editor.code() == text.decode()),
                            f"watcher missed {text!r}")
        self.assertFalse(self.tabs.is_dirty(path))

    def test_deleted_on_disk_keeps_a_dirty_tab(self):
        path = self._file("gone.c", b"keep me\n")
        self.tabs.open_file(path)
        changes = []
        self.tabs.dirtyChanged.connect(lambda p, d: changes.append(d))
        os.remove(path)
        self.tabs.file_changed_on_disk(path)
        self.assertEqual(self.tabs.open_paths(), [path])
        self.assertTrue(self.tabs.is_dirty(path))
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "gone.c *")
        self.assertEqual(changes, [True])
        self.assertTrue(self.tabs.save())
        self.assertEqual(self._read(path), b"keep me\n")
        self.assertFalse(self.tabs.is_dirty(path))

    def test_deleted_by_watcher_keeps_a_dirty_tab(self):
        path = self._file("gone2.c", b"x\n")
        self.tabs.open_file(path)
        os.remove(path)
        self.assertTrue(self._wait_for(lambda: self.tabs.is_dirty(path)))
        self.assertEqual(self.tabs.open_paths(), [path])

    def test_file_deleted_slot_keeps_dirty_tab_dirty(self):
        path = self._file("d.c", b"d")
        clean = self._file("clean.c", b"c")
        editor = self.tabs.open_file(path)
        self.tabs.open_file(clean)
        self.tabs.open_file(path)
        _type(editor, "x")
        os.remove(path)
        os.remove(clean)
        self.tabs.file_deleted(path)
        self.tabs.file_deleted(clean)
        self.assertEqual(self.tabs.open_paths(), [path])
        QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(editor.code(), "d")
        self.assertTrue(self.tabs.is_dirty(path), "its text exists nowhere else now")

    def test_keep_mine_then_same_disk_text_does_not_ask_again(self):
        path = self._file("k.c", b"disk\n")
        editor = self.tabs.open_file(path)
        editor.moveCursor(QTextCursor.End)
        _type(editor, "mine")
        with open(path, "wb") as f:
            f.write(b"theirs\n")
        self.tabs.file_changed_on_disk(path)
        self.assertTrue(self.tabs.has_banner(path))
        self.assertEqual(self.tabs.tabText(self.tabs.currentIndex()), "k.c *")
        self.tabs.resolve_banner(path, reload=False)
        self.tabs.file_changed_on_disk(path)
        self.assertFalse(self.tabs.has_banner(path))
        self.assertEqual(editor.code(), "disk\nmine")
        self.assertTrue(self.tabs.is_dirty(path))

    def test_clean_reload_keeps_cursor_line(self):
        path = self._file("c.c", b"1\n2\n3\n4\n")
        editor = self.tabs.open_file(path, line=3)
        with open(path, "wb") as f:
            f.write(b"1\n2\n3\n4\n5\n")
        self.tabs.file_changed_on_disk(path)
        self.assertEqual(editor.code(), "1\n2\n3\n4\n5\n")
        self.assertEqual(editor.textCursor().blockNumber(), 2)

    # ---- rename / close / pinned

    def test_folder_rename_retargets_every_tab_under_it_only(self):
        m = self._file("pkg/m.py", b"m\n")
        n = self._file("pkg/n.c", b"n\n")
        trap = self._file("pkg2/t.c", b"t\n")    # shares the 'pkg' prefix, not the folder
        for p in (m, n, trap):
            self.tabs.open_file(p)
        old_dir, new_dir = os.path.join(self.dir, "pkg"), os.path.join(self.dir, "lib")
        os.rename(old_dir, new_dir)
        self.tabs.file_renamed(old_dir, new_dir)
        new_m, new_n = os.path.join(new_dir, "m.py"), os.path.join(new_dir, "n.c")
        self.assertEqual(self.tabs.open_paths(), [new_m, new_n, trap])
        self.assertEqual(self.tabs.tabToolTip(2), "lib/n.c")
        self.assertIsNotNone(self.tabs.editor_for(new_n))
        self.assertIsNone(self.tabs.editor_for(n))
        # The watcher follows the new path.
        editor = self.tabs.editor_for(new_n)
        with open(new_n, "wb") as f:
            f.write(b"changed\n")
        self.assertTrue(self._wait_for(lambda: editor.code() == "changed\n"))

    def test_folder_rename_reaches_nested_tabs(self):
        # No rename on disk: on Windows Qt's watcher holds the folder of each
        # watched file open, and that blocks renaming its ancestors.
        deep = self._file("a/b/c/deep.c", b"d\n")
        self.tabs.open_file(deep)
        self.tabs.file_renamed(os.path.join(self.dir, "a"), os.path.join(self.dir, "z"))
        self.assertEqual(self.tabs.open_paths(), [os.path.join(self.dir, "z", "b", "c", "deep.c")])
        self.assertEqual(self.tabs.tabToolTip(1), "z/b/c/deep.c")

    def test_rename_changes_language(self):
        path = self._file("x.txt", b"x = 1\n")
        editor = self.tabs.open_file(path)
        new = os.path.join(self.dir, "x.py")
        os.rename(path, new)
        got = []
        self.tabs.currentFileChanged.connect(got.append)
        self.tabs.file_renamed(path, new)
        self.assertEqual(editor._language, "python")
        self.assertEqual(got, [new])

    def test_close_button_asks_like_close_file(self):
        path = self._file("b.c", b"b")
        editor = self.tabs.open_file(path)
        _type(editor, "x")
        asked = []
        self.tabs._ask_unsaved = lambda p: asked.append(p) or EditorTabs.CANCEL
        self.tabs.tabCloseRequested.emit(self.tabs.indexOf(editor.parentWidget()))
        self.assertEqual((asked, self.tabs.open_paths()), ([path], [path]))
        self.tabs._ask_unsaved = lambda p: EditorTabs.DISCARD
        self.tabs.tabCloseRequested.emit(0)          # the pinned tab: ignored
        self.assertEqual(self.tabs.count(), 2)
        self.assertTrue(self.tabs.close_all())
        self.assertEqual(self.tabs.open_paths(), [])
        self.assertEqual(self._read(path), b"b")

    def test_close_all_stops_at_cancel(self):
        a, b = self._file("a.c", b"a"), self._file("b.c", b"b")
        for p in (a, b):
            _type(self.tabs.open_file(p), "+")
        self.tabs._ask_unsaved = lambda p: EditorTabs.CANCEL
        self.assertFalse(self.tabs.close_all())
        self.assertEqual(self.tabs.open_paths(), [a, b])
        self.assertTrue(self.tabs.close_all(force=True))
        self.assertEqual(self.tabs.open_paths(), [])

    def test_pinned_tabs_have_no_close_button_on_either_side(self):
        second = QLabel("second")
        self.assertEqual(self.tabs.add_pinned(second, "Second"), 1)
        self.tabs.open_file(self._file("f.c", b"f"))
        self.assertEqual(self.tabs.add_pinned(QLabel("third"), "Third"), 2, "pinned tabs come first")
        bar = self.tabs.tabBar()
        for i in range(3):
            for side in (QTabBar.ButtonPosition.LeftSide, QTabBar.ButtonPosition.RightSide):
                self.assertIsNone(bar.tabButton(i, side), f"pinned tab {i}")
        self.assertTrue(any(bar.tabButton(3, side) is not None
                            for side in (QTabBar.ButtonPosition.LeftSide,
                                         QTabBar.ButtonPosition.RightSide)), "file tabs can close")

    def test_open_file_refusals_add_no_tab(self):
        self.assertIsNone(self.tabs.open_file(os.path.join(self.dir, "missing.c")))
        self.assertIsNone(self.tabs.open_file(os.path.join(self.dir, "..", "escape.c")))
        self.assertEqual(self.tabs.count(), 1)
        self.assertEqual(len(self.messages), 2)

    # ---- selection context

    def _select(self, editor, anchor, position):
        cursor = editor.textCursor()
        cursor.setPosition(anchor)
        cursor.setPosition(position, QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)

    def test_selection_context_lines(self):
        path = self._file("s.c", b"l1\nl2\nl3\n")
        editor = self.tabs.open_file(path)
        doc = editor.document()

        def line(n):
            return doc.findBlockByNumber(n - 1).position()
        # Whole lines 1-2 picked with Shift+Down: ends at the start of line 3.
        self._select(editor, line(1), line(3))
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["start_line"], ctx["end_line"], ctx["text"]), (1, 2, "l1\nl2\n"))
        self.assertEqual(ctx["cursor_line"], 3)
        # Backwards selection: same rule, the cursor is at the top.
        self._select(editor, line(3) + 1, line(2))
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["start_line"], ctx["end_line"], ctx["cursor_line"], ctx["text"]),
                         (2, 3, 2, "l2\nl"))
        # Within one line.
        self._select(editor, line(2), line(2) + 2)
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["start_line"], ctx["end_line"], ctx["text"]), (2, 2, "l2"))
        # Only a line break selected (end of line 1 to start of line 2): one line.
        self._select(editor, line(1) + 2, line(2))
        ctx = self.tabs.selection_context()
        self.assertEqual((ctx["start_line"], ctx["end_line"], ctx["text"]), (1, 1, "\n"))
        self.assertEqual(set(ctx), {"path", "relative", "language", "cursor_line", "start_line",
                                    "end_line", "text"})

    # ---- hygiene

    def test_no_qt_method_is_shadowed(self):
        # event and keyPressEvent are virtuals meant to be overridden; staticMetaObject
        # is PySide's own.
        own = [n for n in vars(EditorTabs) if not n.startswith("__")
               and n not in ("event", "keyPressEvent", "staticMetaObject")]
        self.assertEqual([n for n in own if hasattr(QTabWidget, n)], [])

    def test_theme_reaches_open_and_new_editors(self):
        editor = self.tabs.open_file(self._file("th.c", b"t"))
        self.tabs.apply_theme("light")
        self.assertEqual(editor._palette, LIGHT_PALETTE)
        later = self.tabs.open_file(self._file("th2.c", b"t"))
        self.assertEqual(later._palette, LIGHT_PALETTE, "new tabs open in the current theme")


class PythonHighlighterQCTests(unittest.TestCase):
    """W2 QC: the scanner cases the gate does not pin."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_hash_inside_single_quotes(self):
        spans = _spans("s = 'a # b'  # real\n")
        self.assertEqual(spans[0].get("'a # b'"), DARK_PALETTE["string"])
        self.assertEqual(spans[0].get("# real"), DARK_PALETTE["comment"])

    def test_quote_inside_comment_is_comment(self):
        spans = _spans("# it's \"fine\"\nx = 1\n")
        self.assertEqual(spans[0], {"# it's \"fine\"": DARK_PALETTE["comment"]})
        self.assertEqual(spans[1].get("1"), DARK_PALETTE["number"])

    def test_scan_continues_after_closing_triple_quote(self):
        spans = _spans('x = """a\nb""" + "c"  # d\ny = 2\n')
        self.assertEqual(spans[1].get('b"""'), DARK_PALETTE["string"])
        self.assertEqual(spans[1].get('"c"'), DARK_PALETTE["string"])
        self.assertEqual(spans[1].get("# d"), DARK_PALETTE["comment"])
        self.assertEqual(spans[2].get("2"), DARK_PALETTE["number"])

    def test_the_opening_quote_decides_the_close(self):
        spans = _spans("x = '''a\n\"\"\" # still string\nb'''\nz = 3\n")
        self.assertEqual(spans[1], {'""" # still string': DARK_PALETTE["string"]})
        self.assertEqual(spans[2], {"b'''": DARK_PALETTE["string"]})
        self.assertEqual(spans[3].get("3"), DARK_PALETTE["number"])

    def test_triple_closes_then_another_opens(self):
        spans = _spans('"""a\nb""" ; y = """c\nd"""\ne = 4\n')
        self.assertEqual(spans[1].get('"""c'), DARK_PALETTE["string"])
        self.assertEqual(spans[2], {'d"""': DARK_PALETTE["string"]})
        self.assertEqual(spans[3].get("4"), DARK_PALETTE["number"])

    def test_escapes_prefixes_and_decorators(self):
        spans = _spans('s = "a\\"b"  # c\nr = rb"\\d+" + f\'{x}\'\n    @property\n')
        self.assertEqual(spans[0].get('"a\\"b"'), DARK_PALETTE["string"])
        self.assertEqual(spans[0].get("# c"), DARK_PALETTE["comment"])
        self.assertEqual(spans[1].get('rb"\\d+"'), DARK_PALETTE["string"])
        self.assertEqual(spans[1].get("f'{x}'"), DARK_PALETTE["string"])
        self.assertEqual(spans[2].get("@property"), DARK_PALETTE["property"])

    def test_types_and_keywords(self):
        spans = _spans("class Foo(Base): return None, len, MAX_SIZE\n")
        self.assertEqual(spans[0].get("Foo"), DARK_PALETTE["type"])
        self.assertEqual(spans[0].get("Base"), DARK_PALETTE["type"])
        self.assertEqual(spans[0].get("None"), DARK_PALETTE["keyword"])
        self.assertEqual(spans[0].get("len"), DARK_PALETTE["type"])
        self.assertNotIn("MAX_SIZE", spans[0], "a constant is not a class")

    def test_light_palette(self):
        spans = _spans("def f(): pass  # x\n", theme="light")
        self.assertEqual(spans[0].get("def"), LIGHT_PALETTE["keyword"])
        self.assertEqual(spans[0].get("# x"), LIGHT_PALETTE["comment"])


if __name__ == "__main__":
    unittest.main()
