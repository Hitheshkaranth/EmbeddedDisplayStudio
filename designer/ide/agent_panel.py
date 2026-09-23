"""designer/ide/agent_panel.py -- the chat with the coding agent.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W4. Public names,
signatures, signals and docstrings are the contract; W4 fills in the bodies
and may add private helpers and private classes. See docs/CODE_SECTION.md.

Talks only to the AgentBackend interface (designer/ide/agent_backend.py);
knows nothing about opencode. Layout, top to bottom:

    header      "Agent" title, model combo (backend.models(), labels
                ModelRef.label; the choice persists in QSettings
                "MIL-HMI"/"Deployer" key SETTINGS_MODEL_KEY and is restored
                when that model is offered again, else backend.default_model()),
                New chat button (backend.new_session + clears the transcript)
    state line  backend state and detail ("Starting opencode...", the URL when
                ready, the error sentence -- red -- on ERROR); hidden when READY
                and there is nothing to say
    transcript  a scroll area of blocks, one per thing that happened, kept
                scrolled to the bottom while the user has not scrolled up
    composer    "Include open file" checkbox (context_check, on by default),
                a QPlainTextEdit (input; Enter sends, Shift+Enter is a new
                line), and Send / Stop buttons (Stop visible only while busy)

Blocks (kind strings are what blocks() reports):
    'user'       the message as sent (plain text)
    'assistant'  the reply's text; deltas with the same id append to one
                 block; rendered as Markdown (QTextBrowser.setMarkdown or
                 QLabel with Qt.MarkdownText), re-rendered at most every
                 ~50 ms while streaming; links open with QDesktopServices
    'reasoning'  the model's thinking, same id rule; collapsed by default to a
                 one-line header "Thought (N words)" / "Thinking..." that
                 toggles the text
    'tool'       one block per tool part id, updated in place as its status
                 changes: tool name, title, and a status mark (pending/running
                 show a spinner-like "...", completed a check, error a red
                 cross and the error text). Clicking expands the input (JSON)
                 and output (first 4000 chars). When the input names a file
                 (input["filePath"] or input["path"]), a link opens it:
                 openFileRequested(path, 0).
    'permission' the request title and three buttons Allow once / Always /
                 Reject -> backend.reply_permission(id, 'once'|'always'|
                 'reject'); the buttons are replaced by the answer afterwards
    'error'      the message, in the destructive colour
    'notice'     a quiet one-line note from the panel itself (e.g. "Stopped")
A 'usage' event updates a small counter in the state line ("in 40 452 / out
52 tokens" -- summed for the current reply) and adds no block. 'file_edited'
re-emits fileEdited(path) and adds no block (the tool block already shows
the edit). 'busy'/'idle' switch the Send/Stop buttons and is_busy().
Unknown event types are ignored.

Sending: send(text) with the backend READY and not busy; the context passed
to backend.send is context_provider() when context_check is ticked and a
provider is set, else None. While busy the Send button is disabled and
Enter does nothing (the text stays in the input). The input is cleared on
send.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

SETTINGS_MODEL_KEY = "codeSection/agentModel"
BLOCK_KINDS = ("user", "assistant", "reasoning", "tool", "permission", "error", "notice")


class AgentPanel(QWidget):
    """Signals:
        openFileRequested(str, int): a file link in the transcript (path, line).
        fileEdited(str): the agent changed this file (absolute path).

    Attributes tests rely on: `input` (QPlainTextEdit), `send_button`,
    `stop_button`, `new_chat_button` (QToolButton/QPushButton),
    `model_combo` (QComboBox), `context_check` (QCheckBox),
    `state_label` (QLabel).
    """

    openFileRequested = Signal(str, int)
    fileEdited = Signal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def backend(self):
        raise NotImplementedError

    def set_context_provider(self, provider: Callable[[], dict] | None) -> None:
        """A function returning EditorTabs.selection_context(), called at send."""
        raise NotImplementedError

    def set_directory(self, path: str) -> None:
        """The project folder: backend.start(path) when it differs from the
        current one ('' -> backend.stop()). Adds a 'notice' block naming the
        folder when a conversation was already on screen."""
        raise NotImplementedError

    def directory(self) -> str:
        raise NotImplementedError

    def send(self, text: str) -> bool:
        """What pressing Send does with `text`; False (nothing sent) when the
        text is blank, the backend is not READY, or a reply is in progress."""
        raise NotImplementedError

    def stop(self) -> None:
        """What pressing Stop does: backend.abort() and a 'notice' "Stopped"."""
        raise NotImplementedError

    def new_chat(self) -> None:
        """What New chat does."""
        raise NotImplementedError

    def is_busy(self) -> bool:
        raise NotImplementedError

    def selected_model(self):
        """The ModelRef picked in the combo, or None."""
        raise NotImplementedError

    def blocks(self) -> list[tuple[str, str]]:
        """The transcript as (kind, plain text) pairs, top to bottom. For a
        tool block the text is '<tool> <title> <status>'; for a permission
        block the title plus, once answered, ' -> <reply>'; for reasoning
        the full text (even when collapsed)."""
        raise NotImplementedError

    def transcript_text(self) -> str:
        """blocks() as 'kind: text' lines."""
        raise NotImplementedError

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        raise NotImplementedError
