"""designer/ui/code_editor.py -- the Code window's editor.
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


# ---------------------------------------------------------------- further tests

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from designer.ui.code_editor import DARK_PALETTE, LIGHT_PALETTE  # noqa: E402

TOKEN_KEYS = ("keyword", "type", "string", "number", "comment", "property")


def _colour_at(editor, line, column):
    """The '#rrggbb' the highlighter gave the character at (line, column), or None."""
    block = editor.document().findBlockByNumber(line)
    for fmt_range in block.layout().formats():
        if fmt_range.start <= column < fmt_range.start + fmt_range.length:
            return fmt_range.format.foreground().color().name()
    return None


class HighlighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _editor(self, language, text, theme="dark"):
        editor = CodeEditor()
        editor.apply_theme(theme)
        editor.set_language(language)
        editor.set_code(text)
        return editor

    def test_palettes_carry_the_highlighter_keys(self):
        for palette in (DARK_PALETTE, LIGHT_PALETTE):
            for key in TOKEN_KEYS:
                self.assertRegex(palette[key], r"^#[0-9a-fA-F]{6}$")

    def test_qml_tokens(self):
        editor = self._editor("qml", 'import QtQuick 2.15\nRectangle {\n    width: 42 // note\n    text: "a: b"\n}\n')
        p = DARK_PALETTE
        self.assertEqual(_colour_at(editor, 0, 0), p["keyword"])    # import
        self.assertEqual(_colour_at(editor, 1, 0), p["type"])       # Rectangle {
        self.assertEqual(_colour_at(editor, 2, 4), p["property"])   # width:
        self.assertEqual(_colour_at(editor, 2, 11), p["number"])    # 42
        self.assertEqual(_colour_at(editor, 2, 14), p["comment"])   # // note
        self.assertEqual(_colour_at(editor, 3, 10), p["string"])    # "a: b"
        self.assertEqual(_colour_at(editor, 3, 12), p["string"])    # the ':' inside the string is not a property

    def test_qml_block_comment_spans_lines(self):
        editor = self._editor("qml", "/* one\nimport two\n*/ Item {\n")
        p = DARK_PALETTE
        self.assertEqual(_colour_at(editor, 1, 0), p["comment"])    # not a keyword inside /* */
        self.assertEqual(_colour_at(editor, 2, 3), p["type"])       # colouring resumes after */

    def test_json_tokens(self):
        editor = self._editor("json", '{"id": "btn", "w": 12.5, "on": true, "x": null}\n')
        p = DARK_PALETTE
        self.assertEqual(_colour_at(editor, 0, 1), p["property"])   # "id" key
        self.assertEqual(_colour_at(editor, 0, 7), p["string"])     # "btn" value
        self.assertEqual(_colour_at(editor, 0, 20), p["number"])    # 12.5
        self.assertEqual(_colour_at(editor, 0, 32), p["keyword"])   # true
        self.assertEqual(_colour_at(editor, 0, 43), p["keyword"])   # null

    def test_theme_swaps_highlighter_palette(self):
        editor = self._editor("qml", "import QtQuick\n")
        editor.apply_theme("light")
        self.assertEqual(_colour_at(editor, 0, 0), LIGHT_PALETTE["keyword"])
        editor.apply_theme("dark")
        self.assertEqual(_colour_at(editor, 0, 0), DARK_PALETTE["keyword"])

    def test_plain_has_no_highlighter(self):
        editor = self._editor("qml", "import QtQuick\n")
        editor.set_language("plain")
        self.assertIsNone(_highlighter(editor))
        self.assertIsNone(_colour_at(editor, 0, 0))

    def test_highlighting_does_not_count_as_an_edit(self):
        editor = CodeEditor()
        edits = []
        editor.codeEdited.connect(lambda: edits.append(1))
        editor.set_code("import QtQuick\n")
        editor.set_language("qml")
        editor.apply_theme("light")
        editor.set_language("json")
        self.app.processEvents()      # the rehighlight Qt queues after setDocument
        self.assertEqual(edits, [])


class EditorBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_set_code_clears_undo(self):
        editor = CodeEditor()
        editor.set_code("one\n")
        editor.textCursor().insertText("two")
        self.assertTrue(editor.document().isUndoAvailable())
        editor.set_code("three\n")
        self.assertFalse(editor.document().isUndoAvailable())
        editor.undo()
        self.assertEqual(editor.code(), "three\n")

    def test_monospace_font_and_tab(self):
        editor = CodeEditor()
        self.assertEqual(editor.font().pixelSize(), 12)
        self.assertEqual(editor.tabStopDistance(), 4 * editor.fontMetrics().horizontalAdvance(" "))
        editor.set_code("")
        QTest.keyClick(editor, Qt.Key_Tab)
        self.assertEqual(editor.code(), "    ")

    def test_return_keeps_indent(self):
        editor = CodeEditor()
        editor.set_code('    "a": 1')
        editor.moveCursor(QTextCursor.End)
        QTest.keyClick(editor, Qt.Key_Return)
        self.assertEqual(editor.code(), '    "a": 1\n    ')

    def test_read_only_view_blocks_keys(self):
        editor = CodeEditor()
        editor.set_code("x\n")
        edits = []
        editor.codeEdited.connect(lambda: edits.append(1))
        editor.set_read_only_view(True)
        QTest.keyClicks(editor, "typed")
        QTest.keyClick(editor, Qt.Key_Tab)
        self.assertEqual(editor.code(), "x\n")
        self.assertEqual(edits, [])

    def test_find_bar_keys(self):
        editor = CodeEditor()
        editor.resize(400, 200)
        editor.show()
        editor.set_code(QML)
        bar = editor._find
        self.assertFalse(bar.isVisible())
        QTest.keyClick(editor, Qt.Key_F, Qt.ControlModifier)
        self.assertTrue(bar.isVisible())
        self.assertGreater(editor.viewportMargins().bottom(), 0)
        bar.field.setText("item12")                      # incremental: lands on the first hit
        self.assertEqual(editor.textCursor().blockNumber(), 11)
        QTest.keyClick(bar.field, Qt.Key_Return)
        self.assertEqual(editor.textCursor().blockNumber(), 119)   # item120
        QTest.keyClick(bar.field, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(editor.textCursor().blockNumber(), 11)
        bar.field.setText("nothing here")
        self.assertEqual(bar.status.text(), "No results")
        QTest.keyClick(bar.field, Qt.Key_Escape)
        self.assertFalse(bar.isVisible())
        self.assertEqual(editor.viewportMargins().bottom(), 0)

    def test_show_find_takes_selection(self):
        editor = CodeEditor()
        editor.set_code(QML)
        self.assertTrue(editor.find_next("item7;"))
        editor.show_find()
        self.assertEqual(editor._find.field.text(), "item7;")

    def test_find_bar_works_read_only(self):
        editor = CodeEditor()
        editor.set_code(QML)
        editor.set_read_only_view(True)
        editor.show_find()
        editor._find.field.setText("item99")
        self.assertEqual(editor.textCursor().blockNumber(), 98)

    def test_go_to_line_clamps(self):
        editor = CodeEditor()
        editor.set_code(QML)
        editor.go_to_line(0)
        self.assertEqual(editor.textCursor().blockNumber(), 0)
        editor.go_to_line(10_000)
        self.assertEqual(editor.textCursor().blockNumber(), editor.blockCount() - 1)

    def test_bad_language_rejected(self):
        with self.assertRaises(ValueError):
            CodeEditor().set_language("cobol")


if __name__ == "__main__":
    unittest.main()
