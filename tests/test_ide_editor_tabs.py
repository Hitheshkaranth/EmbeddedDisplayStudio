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


if __name__ == "__main__":
    unittest.main()
