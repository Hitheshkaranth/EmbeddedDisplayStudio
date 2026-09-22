"""designer/ui/code_editor.py -- the Code window's editor (W2 gate).

FROZEN: the tests below are the minimum W2 must pass; add more below them,
never change these.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ui.code_editor import CodeEditor, JsonHighlighter, QmlHighlighter  # noqa: E402

QML = "\n".join(f"Item {{ id: item{i}; width: {i} }}" for i in range(1, 121)) + "\n"


class CodeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_set_code_does_not_emit_codeEdited(self):
        editor = CodeEditor()
        edits = []
        editor.codeEdited.connect(lambda: edits.append(1))
        editor.set_language("qml")
        editor.set_code(QML)
        self.assertEqual(editor.code(), QML)
        self.assertEqual(edits, [])
        editor.textCursor().insertText("// typed\n")
        self.assertEqual(len(edits), 1)

    def test_read_only_view_blocks_typing_keeps_copy(self):
        editor = CodeEditor()
        editor.set_code("a\nb\n")
        editor.set_read_only_view(True)
        self.assertTrue(editor.isReadOnly())
        editor.selectAll()
        self.assertEqual(editor.textCursor().selectedText().replace(" ", "\n"), "a\nb\n")
        editor.set_read_only_view(False)
        self.assertFalse(editor.isReadOnly())

    def test_keep_scroll_and_go_to_line(self):
        editor = CodeEditor()
        editor.resize(400, 200)
        editor.set_code(QML)
        editor.go_to_line(100)
        self.assertEqual(editor.textCursor().blockNumber(), 99)
        editor.set_code(QML.replace("width: 100", "width: 1000"), keep_scroll=True)
        self.assertEqual(editor.textCursor().blockNumber(), 99)
        editor.set_code("short\n", keep_scroll=True)     # line no longer exists: no crash
        self.assertLess(editor.textCursor().blockNumber(), 2)

    def test_find_wraps(self):
        editor = CodeEditor()
        editor.set_code(QML)
        self.assertTrue(editor.find_next("item120"))
        self.assertEqual(editor.textCursor().blockNumber(), 119)
        self.assertTrue(editor.find_next("item1;"))        # wraps to the top
        self.assertEqual(editor.textCursor().blockNumber(), 0)
        self.assertTrue(editor.find_next("item120", backwards=True))
        self.assertFalse(editor.find_next("not-there"))

    def test_languages_and_theme(self):
        editor = CodeEditor()
        for language in ("qml", "json", "plain"):
            editor.set_language(language)
        editor.set_language("qml")
        self.assertIsInstance(editor.document().findChild(QmlHighlighter) or _highlighter(editor), QmlHighlighter)
        editor.set_language("json")
        self.assertIsInstance(_highlighter(editor), JsonHighlighter)
        for theme in ("dark", "light"):
            editor.apply_theme(theme)
        editor.set_code('{"a": 1}\n')
        self.assertEqual(editor.code(), '{"a": 1}\n')

    def test_line_numbers_gutter_exists(self):
        editor = CodeEditor()
        editor.set_code(QML)
        editor.resize(400, 200)
        editor.show()
        self.app.processEvents()
        # The gutter takes room at the left: the viewport starts right of the widget's left edge.
        self.assertGreater(editor.viewportMargins().left(), 20)


def _highlighter(editor):
    from PySide6.QtGui import QSyntaxHighlighter
    return next((c for c in editor.document().children() if isinstance(c, QSyntaxHighlighter)), None)


if __name__ == "__main__":
    unittest.main()
