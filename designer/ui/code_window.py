"""designer/ui/code_window.py -- the Studio's Code window.

FROZEN CONTRACT (Code window swarm, 2026-09-22). Owner: W3. Public names,
signatures and signals below are the contract; W3 fills them in and may add
private helpers and private classes.

A separate, non-modal window ("Code") beside the Studio that shows the code
of what is selected in the Designer and follows the selection live:

    toolbar   Scope: [Selected widget | Whole screen]   Format: [QML | Design JSON]
              [Preview] toggle   ...   [Apply] [Copy] [Save as...]
    body      left: title line + CodeEditor (designer/ui/code_editor.py)
              right (when Preview is on): the same section rendered, using
              the workspace's QmlPreviewRenderer (workspace.scene.qml_previews)
              for a widget, or that renderer over an "Item" wrapper holding
              the page's widgets for the whole screen. Fitted to the pane,
              aspect kept, re-rendered when the design changes.
    status    a line for messages: 'Applied', an error from CodeError, etc.

Behaviour:
  * Follows workspace.scene.selectionIdsChanged (widget scope shows the first
    selected widget; none selected -> the "nothing selected" section), and
    workspace.designChanged / page changes (refreshes the text; the editor
    keeps its scroll position).
  * QML sections are read-only. Design JSON sections are editable; while the
    text differs from the model's, the title gets a ' *' and Apply is enabled.
    Apply parses with designer.code.parse_widget_edsui / parse_page_edsui and
    calls workspace.replace_widget / workspace.replace_page (one undo step);
    a CodeError goes to the status line and the editor jumps to the line
    when the message names one.
  * Switching scope/format while edited asks Discard/Keep (Keep stays).
  * Closing the window hides it (the workspace keeps one instance).
  * apply_theme follows the workspace's theme.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow


class CodeWindow(QMainWindow):
    """The Code window bound to one DesignerWorkspace.

    Signals:
        sectionChanged(str, str): (scope, fmt) after the view switched.

    Public attributes (part of the contract; tests use them):
        editor: the CodeEditor.
        preview: the preview pane widget (a QWidget; hidden when off).
    """

    sectionChanged = Signal(str, str)

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    # ---------------------------------------------------------------- API

    @property
    def scope(self) -> str:
        """'widget' or 'page'."""
        raise NotImplementedError

    @property
    def fmt(self) -> str:
        """'qml' or 'edsui'."""
        raise NotImplementedError

    def show_section(self, scope: str, fmt: str) -> None:
        """Switches the view (asks about unapplied edits first)."""
        raise NotImplementedError

    def refresh(self) -> None:
        """Re-reads the model into the editor and preview (called on
        selection/design changes; safe to call at any time)."""
        raise NotImplementedError

    def set_preview_visible(self, visible: bool) -> None:
        raise NotImplementedError

    def preview_visible(self) -> bool:
        raise NotImplementedError

    def is_edited(self) -> bool:
        """True while the editor text differs from the model's JSON."""
        raise NotImplementedError

    def apply(self) -> bool:
        """Parses and applies an edited design JSON. True on success."""
        raise NotImplementedError

    def status_text(self) -> str:
        """What the status line says (tests read it)."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        raise NotImplementedError
