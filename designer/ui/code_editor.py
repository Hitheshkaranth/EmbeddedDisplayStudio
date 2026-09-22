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

from PySide6.QtCore import Signal
from PySide6.QtGui import QSyntaxHighlighter
from PySide6.QtWidgets import QPlainTextEdit

LANGUAGES = ("qml", "json", "plain")


class QmlHighlighter(QSyntaxHighlighter):
    """Keywords (import, property, signal, function, if/else, true/false...),
    type names (a capitalised identifier before `{`), strings, numbers,
    // and /* */ comments, property names before ':'. Colours come from
    `set_palette` so light and dark both read well."""

    def set_palette(self, palette: dict[str, str]) -> None:
        """palette keys: keyword, type, string, number, comment, property,
        each a '#rrggbb'. Re-highlights the document."""
        raise NotImplementedError


class JsonHighlighter(QSyntaxHighlighter):
    """Keys, strings, numbers, true/false/null. Same `set_palette` contract."""

    def set_palette(self, palette: dict[str, str]) -> None:
        raise NotImplementedError


class CodeEditor(QPlainTextEdit):
    """The editor.

    Signals:
        codeEdited(): the user changed the text (not emitted by set_code).
    """

    codeEdited = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    # ---------------------------------------------------------------- API

    def set_language(self, language: str) -> None:
        """'qml', 'json' or 'plain'. Swaps the highlighter."""
        raise NotImplementedError

    def set_code(self, text: str, keep_scroll: bool = True) -> None:
        """Replaces the text without emitting codeEdited. With keep_scroll the
        vertical scroll position and cursor line are restored when they still
        exist; the undo history of the document is cleared."""
        raise NotImplementedError

    def code(self) -> str:
        """The current text."""
        raise NotImplementedError

    def set_read_only_view(self, read_only: bool) -> None:
        """Read-only keeps selection/copy and the find bar working; the
        gutter and current-line colours dim slightly to say so."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light': background, text, gutter and highlighter palette."""
        raise NotImplementedError

    def go_to_line(self, line: int) -> None:
        """1-based; moves the cursor there and centres it."""
        raise NotImplementedError

    def show_find(self) -> None:
        """Opens the find bar with the current selection as the query."""
        raise NotImplementedError

    def find_next(self, query: str, backwards: bool = False) -> bool:
        """Wraps around; True when found."""
        raise NotImplementedError
