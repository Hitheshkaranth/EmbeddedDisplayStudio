"""designer/ui/code_editor.py -- the Code window's editor widget.

FROZEN CONTRACT (Code window swarm, 2026-09-22). Owner: W2. Public names,
signatures and signals below are the contract; W2 fills them in and may add
private helpers and private classes.

A QPlainTextEdit with what a code view needs and nothing more: line numbers
in a gutter, current-line highlight, a monospace font, QML and JSON syntax
colouring that follows the Studio theme, a read-only mode that still allows
selection and copying, and a small find bar (Ctrl+F, Enter/Shift+Enter for
next/previous, Esc closes).
"""
from __future__ import annotations

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontDatabase, QKeySequence, QPainter, QSyntaxHighlighter, QTextCharFormat,
    QTextCursor, QTextDocument, QTextFormat, QTransform,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit, QToolButton, QWidget,
)

try:
    from ui.python.shadcn import icon as _tabler_icon
except ImportError:                                     # Studio icons are a nicety, not a need
    from PySide6.QtGui import QIcon
    def _tabler_icon(_name, _size=16, _color=None): return QIcon()

LANGUAGES = ("qml", "json", "plain")

# Editor surfaces and token colours per Studio theme. The surface keys are
# the editor's; the token keys (keyword ... property) are the highlighter
# `set_palette` contract. Both live here as module constants so the Code
# window can paint its own chrome (preview frame, splitter) to match.
DARK_PALETTE = {
    "background": "#0b0f14",
    "text": "#e6edf3",
    "gutter": "#0b0f14",
    "gutter_text": "#4b5563",
    "gutter_text_dim": "#343b47",
    "gutter_current": "#c9d1d9",
    "current_line": "#131a24",
    "current_line_dim": "#0f151d",
    "selection": "#264f78",
    "selection_text": "#e6edf3",
    "border": "#303036",
    "bar": "#18181b",
    "bar_text": "#ecedee",
    "muted": "#a1a1aa",
    "field": "#0b0f14",
    "missing": "#f87171",
    "keyword": "#ff7b72",
    "type": "#ffa657",
    "string": "#a5d6ff",
    "number": "#79c0ff",
    "comment": "#8b949e",
    "property": "#7ee787",
}

LIGHT_PALETTE = {
    "background": "#ffffff",
    "text": "#020817",
    "gutter": "#ffffff",
    "gutter_text": "#94a3b8",
    "gutter_text_dim": "#cbd5e1",
    "gutter_current": "#334155",
    "current_line": "#f1f5f9",
    "current_line_dim": "#f8fafc",
    "selection": "#bfdbfe",
    "selection_text": "#020817",
    "border": "#e2e8f0",
    "bar": "#f8fafc",
    "bar_text": "#020817",
    "muted": "#64748b",
    "field": "#ffffff",
    "missing": "#dc2626",
    "keyword": "#cf222e",
    "type": "#953800",
    "string": "#0a3069",
    "number": "#0550ae",
    "comment": "#6e7781",
    "property": "#116329",
}

_MONO_FAMILIES = ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "monospace")
_FONT_PX = 12
_TAB_SPACES = 4
_GUTTER_PAD = 6          # px either side of the digits
_MIN_DIGITS = 3          # the gutter does not jitter when a file crosses 99 lines

_IN_COMMENT = 1          # block state: an unterminated /* */ comment runs into the next line


def _format(colour: str, italic: bool = False, bold: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(colour))
    if italic:
        fmt.setFontItalic(True)
    if bold:
        fmt.setFontWeight(QFont.DemiBold)
    return fmt


class _RuleHighlighter(QSyntaxHighlighter):
    """Regex rules applied in order, then a scanner for string and comment
    literals so a `//` inside a string, or a keyword inside a comment, never
    colours the wrong thing. Subclasses fill `_rules` (pattern, token key).

    Kept private: the two public highlighters below are the contract; how
    they share code is not.
    """

    _rules: tuple[tuple[str, str], ...] = ()
    _comments = False
    _quotes = '"'
    _key_before_colon = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self._formats: dict[str, QTextCharFormat] = {}
        self._compiled = [(QRegularExpression(pattern), key) for pattern, key in self._rules]
        self._palette_only(DARK_PALETTE)

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette_only(palette)
        self.rehighlight()

    def _palette_only(self, palette: dict[str, str]) -> None:
        self._formats = {
            "keyword": _format(palette["keyword"], bold=True),
            "type": _format(palette["type"]),
            "string": _format(palette["string"]),
            "number": _format(palette["number"]),
            "comment": _format(palette["comment"], italic=True),
            "property": _format(palette["property"]),
        }

    def highlightBlock(self, text: str) -> None:
        for regex, key in self._compiled:
            fmt = self._formats[key]
            matches = regex.globalMatch(text)
            while matches.hasNext():
                m = matches.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
        self._highlight_literals(text)

    def _highlight_literals(self, text: str) -> None:
        comment = self._formats["comment"]
        n = len(text)
        i = 0
        self.setCurrentBlockState(0)
        if self._comments and self.previousBlockState() == _IN_COMMENT:
            end = text.find("*/")
            if end < 0:
                self.setFormat(0, n, comment)
                self.setCurrentBlockState(_IN_COMMENT)
                return
            self.setFormat(0, end + 2, comment)
            i = end + 2
        while i < n:
            ch = text[i]
            if ch in self._quotes:
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                length = min(j + 1, n) - i
                self._format_string(text, i, length)
                i += length
            elif self._comments and text.startswith("//", i):
                self.setFormat(i, n - i, comment)
                return
            elif self._comments and text.startswith("/*", i):
                end = text.find("*/", i + 2)
                if end < 0:
                    self.setFormat(i, n - i, comment)
                    self.setCurrentBlockState(_IN_COMMENT)
                    return
                self.setFormat(i, end + 2 - i, comment)
                i = end + 2
            else:
                i += 1

    def _format_string(self, text: str, start: int, length: int) -> None:
        key = "string"
        if self._key_before_colon:
            rest = text[start + length:].lstrip()
            if rest.startswith(":"):
                key = "property"
        self.setFormat(start, length, self._formats[key])


class QmlHighlighter(_RuleHighlighter):
    """Keywords (import, property, signal, function, if/else, true/false...),
    type names (a capitalised identifier before `{`), strings, numbers,
    // and /* */ comments, property names before ':'. Colours come from
    `set_palette` so light and dark both read well."""

    _KEYWORDS = (
        "import", "as", "property", "signal", "function", "readonly", "alias", "default",
        "required", "if", "else", "for", "while", "return", "var", "let", "const", "true",
        "false", "null", "undefined", "on", "int", "real", "string", "bool", "color", "list",
    )
    _rules = (
        # Property names first so `id`, `width`, `onClicked` keep their colour
        # when they are also, say, the `on` keyword's prefix.
        (r"\b[a-z_][A-Za-z0-9_.]*(?=\s*:)", "property"),
        (r"\b[A-Z][A-Za-z0-9_]*(?=\s*\{)", "type"),
        (r"\b(?:" + "|".join(_KEYWORDS) + r")\b", "keyword"),
        (r"\b(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b", "number"),
    )
    _comments = True
    _quotes = "\"'`"

    def set_palette(self, palette: dict[str, str]) -> None:
        """palette keys: keyword, type, string, number, comment, property,
        each a '#rrggbb'. Re-highlights the document."""
        super().set_palette(palette)


class JsonHighlighter(_RuleHighlighter):
    """Keys, strings, numbers, true/false/null. Same `set_palette` contract."""

    _rules = (
        (r"\b(?:true|false|null)\b", "keyword"),
        (r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b", "number"),
    )
    _key_before_colon = True

    def set_palette(self, palette: dict[str, str]) -> None:
        super().set_palette(palette)


class _Cursor(QTextCursor):
    """A QTextCursor whose selectedText() joins lines with '\\n'.

    Qt's selectedText() separates blocks with U+2029, which is what the clipboard
    never sees and what every caller of a *code* editor trips over when it
    compares against the text it put in. The editor hands out this cursor so
    `editor.textCursor().selectedText()` reads like `code()` does.
    """

    def selectedText(self) -> str:
        return super().selectedText().replace(" ", "\n")


class _Gutter(QWidget):
    """The line-number strip; painting is delegated to the editor, which owns
    the block geometry and the colours."""

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor._gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor._paint_gutter(event)


class _FindField(QLineEdit):
    """Enter / Shift+Enter step through matches, Esc closes the bar."""

    submitted = Signal(bool)          # backwards
    escaped = Signal()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.submitted.emit(bool(event.modifiers() & Qt.ShiftModifier))
            return
        if key == Qt.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(event)


class _FindBar(QWidget):
    """A one-line strip under the text: field, previous/next, close."""

    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.setObjectName("codeFindBar")
        self.setAutoFillBackground(True)
        self.icon = QLabel(objectName="codeFindIcon")
        self.field = _FindField(objectName="codeFindField")
        self.field.setPlaceholderText("Find")
        self.field.setClearButtonEnabled(True)
        self.status = QLabel(objectName="codeFindStatus")
        self.previous = QToolButton(objectName="codeFindPrev", autoRaise=True, toolTip="Previous (Shift+Enter)")
        self.next = QToolButton(objectName="codeFindNext", autoRaise=True, toolTip="Next (Enter)")
        self.close = QToolButton(objectName="codeFindClose", autoRaise=True, toolTip="Close (Esc)")
        for button in (self.previous, self.next, self.close):
            button.setFixedSize(22, 22)
            button.setIconSize(QSize(14, 14))
            button.setFocusPolicy(Qt.NoFocus)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(4)
        layout.addWidget(self.icon)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.previous)
        layout.addWidget(self.next)
        layout.addWidget(self.close)

    def set_missing(self, missing: bool) -> None:
        self.status.setText("No results" if missing else "")
        self.field.setProperty("missing", missing)
        self.field.style().unpolish(self.field)
        self.field.style().polish(self.field)

    def retheme(self, palette: dict[str, str]) -> None:
        muted = palette["muted"]
        self.icon.setPixmap(_tabler_icon("search", 14, muted).pixmap(14, 14))
        down = _tabler_icon("chevron-down", 14, muted)
        self.next.setIcon(down)
        # Tabler ships no chevron-up in the vendored set; a flipped chevron-down
        # is the same glyph.
        up = down.pixmap(14, 14).transformed(QTransform().scale(1, -1))
        self.previous.setIcon(up)
        self.close.setIcon(_tabler_icon("x", 14, muted))


class CodeEditor(QPlainTextEdit):
    """The editor.

    Signals:
        codeEdited(): the user changed the text (not emitted by set_code).
    """

    codeEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._text = ""            # what the document held when codeEdited last fired
        self._read_only = False
        self._language = "plain"
        self._highlighter: _RuleHighlighter | None = None
        self._palette = DARK_PALETTE
        self._theme = "dark"
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(self._pick_font())
        self.setTabStopDistance(_TAB_SPACES * self.fontMetrics().horizontalAdvance(" "))
        self._gutter = _Gutter(self)
        self._find = _FindBar(self)
        self._find.hide()
        self._find.field.textChanged.connect(self._find_incremental)
        self._find.field.submitted.connect(lambda backwards: self._find_from_bar(backwards))
        self._find.field.escaped.connect(self._hide_find)
        self._find.next.clicked.connect(lambda: self._find_from_bar(False))
        self._find.previous.clicked.connect(lambda: self._find_from_bar(True))
        self._find.close.clicked.connect(self._hide_find)
        self.blockCountChanged.connect(lambda _n: self._update_margins())
        self.updateRequest.connect(self._scroll_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self.document().contentsChanged.connect(self._on_contents_changed)
        self.apply_theme("dark")
        self._update_margins()
        self._highlight_current_line()

    # ---------------------------------------------------------------- API

    def set_language(self, language: str) -> None:
        """'qml', 'json' or 'plain'. Swaps the highlighter."""
        if language not in LANGUAGES:
            raise ValueError(f"unknown language {language!r}; expected one of {LANGUAGES}")
        if language == self._language and (self._highlighter is not None or language == "plain"):
            return
        self._language = language
        if self._highlighter is not None:
            # Detach synchronously: a deleteLater'd highlighter would keep
            # colouring, and stay a child of the document, until the loop spins.
            self._highlighter.setDocument(None)
            self._highlighter.setParent(None)
            self._highlighter = None
        cls = {"qml": QmlHighlighter, "json": JsonHighlighter}.get(language)
        if cls is not None:
            self._highlighter = cls(self.document())
            self._highlighter.set_palette(self._palette)

    def set_code(self, text: str, keep_scroll: bool = True) -> None:
        """Replaces the text without emitting codeEdited. With keep_scroll the
        vertical scroll position and cursor line are restored when they still
        exist; the undo history of the document is cleared."""
        bar = self.verticalScrollBar()
        scroll = bar.value()
        cursor = self.textCursor()
        block, column = cursor.blockNumber(), cursor.positionInBlock()
        self._loading = True
        try:
            self.setPlainText(text)
        finally:
            self._loading = False
        self._text = self.toPlainText()
        self.document().clearUndoRedoStacks()
        if keep_scroll:
            if block < self.blockCount():
                target = self.document().findBlockByNumber(block)
                restored = QTextCursor(target)
                restored.setPosition(target.position() + min(column, target.length() - 1))
                self.setTextCursor(restored)
            bar.setValue(min(scroll, bar.maximum()))
        self._highlight_current_line()

    def code(self) -> str:
        """The current text."""
        return self.toPlainText()

    def set_read_only_view(self, read_only: bool) -> None:
        """Read-only keeps selection/copy and the find bar working; the
        gutter and current-line colours dim slightly to say so."""
        self._read_only = read_only
        self.setReadOnly(read_only)
        # setReadOnly alone drops keyboard selection; a code view that cannot
        # be edited should still let Shift+arrows and Ctrl+A pick text to copy.
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard if read_only
            else Qt.TextEditorInteraction)
        self._highlight_current_line()
        self._gutter.update()

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light': background, text, gutter and highlighter palette."""
        self._theme = "light" if theme == "light" else "dark"
        self._palette = LIGHT_PALETTE if self._theme == "light" else DARK_PALETTE
        p = self._palette
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {p['background']}; color: {p['text']};
                selection-background-color: {p['selection']}; selection-color: {p['selection_text']};
                border: none;
            }}
            QWidget#codeFindBar {{ background: {p['bar']}; border-top: 1px solid {p['border']}; }}
            QLabel#codeFindIcon, QLabel#codeFindStatus {{ background: transparent; }}
            QLabel#codeFindStatus {{ color: {p['muted']}; font-size: 11px; padding: 0 4px; }}
            QLineEdit#codeFindField {{
                background: {p['field']}; color: {p['bar_text']};
                border: 1px solid {p['border']}; border-radius: 4px; padding: 2px 6px; font-size: 12px;
                selection-background-color: {p['selection']}; selection-color: {p['selection_text']};
            }}
            QLineEdit#codeFindField[missing="true"] {{ border-color: {p['missing']}; }}
            QWidget#codeFindBar QToolButton {{ background: transparent; border: none; border-radius: 4px; }}
            QWidget#codeFindBar QToolButton:hover {{ background: {p['current_line']}; }}
        """)
        self._find.retheme(p)
        if self._highlighter is not None:
            self._highlighter.set_palette(p)
        self._highlight_current_line()
        self._gutter.update()

    def go_to_line(self, line: int) -> None:
        """1-based; moves the cursor there and centres it."""
        index = max(0, min(line - 1, self.blockCount() - 1))
        self.setTextCursor(QTextCursor(self.document().findBlockByNumber(index)))
        self.centerCursor()

    def show_find(self) -> None:
        """Opens the find bar with the current selection as the query."""
        selected = self.textCursor().selectedText()
        if selected and "\n" not in selected:
            self._find.field.setText(selected)
        self._find.show()
        self._update_margins()
        self._find.set_missing(False)
        self._find.field.setFocus(Qt.ShortcutFocusReason)
        self._find.field.selectAll()

    def find_next(self, query: str, backwards: bool = False) -> bool:
        """Wraps around; True when found."""
        if not query:
            return False
        flags = QTextDocument.FindFlags()
        if backwards:
            flags |= QTextDocument.FindBackward
        if self.find(query, flags):
            return True
        origin = self.textCursor()
        wrapped = QTextCursor(self.document())
        wrapped.movePosition(QTextCursor.End if backwards else QTextCursor.Start)
        self.setTextCursor(wrapped)
        if self.find(query, flags):
            return True
        self.setTextCursor(origin)
        return False

    # ------------------------------------------------------------ Qt hooks

    def textCursor(self) -> QTextCursor:
        return _Cursor(super().textCursor())

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if event.matches(QKeySequence.Find):
            self.show_find()
            return
        if key == Qt.Key_Escape and self._find.isVisible():
            self._hide_find()
            return
        if key == Qt.Key_F3 and self._find.field.text():
            self._find_from_bar(bool(event.modifiers() & Qt.ShiftModifier))
            return
        if not self.isReadOnly():
            if key == Qt.Key_Tab:
                self.textCursor().insertText(" " * _TAB_SPACES)
                return
            if key in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers():
                # Keep the previous line's indent: the JSON the window edits is
                # nested four deep before the first value.
                line = self.textCursor().block().text()
                indent = line[: len(line) - len(line.lstrip(" \t"))]
                super().keyPressEvent(event)
                if indent:
                    self.textCursor().insertText(indent)
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_children()

    # ------------------------------------------------------------- private

    @staticmethod
    def _pick_font() -> QFont:
        available = set(QFontDatabase.families())
        family = next((f for f in _MONO_FAMILIES if f in available), "monospace")
        font = QFont(family)
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setPixelSize(_FONT_PX)
        return font

    def _on_contents_changed(self) -> None:
        # A highlighter pass ends an edit block too, so the document reports a
        # change on every rehighlight (theme swap, language swap, and the one
        # Qt queues after setDocument). Only a change to the characters counts.
        if self._loading:
            return
        text = self.toPlainText()
        if text == self._text:
            return
        self._text = text
        self.codeEdited.emit()

    def _gutter_width(self) -> int:
        digits = max(_MIN_DIGITS, len(str(max(1, self.blockCount()))))
        return 2 * _GUTTER_PAD + digits * self.fontMetrics().horizontalAdvance("9")

    def _bar_height(self) -> int:
        return self._find.sizeHint().height() if self._find.isVisible() else 0

    def _update_margins(self) -> None:
        self.setViewportMargins(self._gutter_width(), 0, 0, self._bar_height())
        self._layout_children()

    def _layout_children(self) -> None:
        cr = self.contentsRect()
        bar = self._bar_height()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self._gutter_width(), cr.height() - bar))
        if bar:
            self._find.setGeometry(QRect(cr.left(), cr.bottom() - bar + 1, cr.width(), bar))

    def _scroll_gutter(self, rect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margins()

    def _paint_gutter(self, event) -> None:
        p = self._palette
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(p["gutter"]))
        painter.setPen(QColor(p["border"]))
        right = self._gutter.width() - 1
        painter.drawLine(right, event.rect().top(), right, event.rect().bottom())
        painter.setFont(self.font())
        numbers = QColor(p["gutter_text_dim" if self._read_only else "gutter_text"])
        current = QColor(p["gutter_current"] if not self._read_only else p["gutter_text"])
        current_block = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        height = self.fontMetrics().height()
        width = right - _GUTTER_PAD
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and top + height >= event.rect().top():
                painter.setPen(current if block.blockNumber() == current_block else numbers)
                painter.drawText(0, int(top), width, height, Qt.AlignRight | Qt.AlignVCenter,
                                 str(block.blockNumber() + 1))
            top += self.blockBoundingRect(block).height()
            block = block.next()

    def _highlight_current_line(self) -> None:
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(self._palette["current_line_dim" if self._read_only
                                                            else "current_line"]))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])
        self._gutter.update()

    def _hide_find(self) -> None:
        self._find.hide()
        self._update_margins()
        self.setFocus(Qt.OtherFocusReason)

    def _find_from_bar(self, backwards: bool) -> None:
        self._find.set_missing(not self.find_next(self._find.field.text(), backwards))

    def _find_incremental(self, text: str) -> None:
        # Search from where the current match starts so typing one more letter
        # extends the highlight instead of jumping past it.
        cursor = self.textCursor()
        cursor.setPosition(cursor.selectionStart())
        self.setTextCursor(cursor)
        if not text:
            self._find.set_missing(False)
            return
        self._find.set_missing(not self.find_next(text))
