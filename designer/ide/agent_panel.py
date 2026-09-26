"""designer/ide/agent_panel.py -- the chat with the coding agent.

See docs/CODE_SECTION.md.

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

import html
import json
import os
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget,
)

from designer.ide.agent_backend import ERROR, READY, STARTING, STOPPED
from designer.ide.opencode_client import ModelRef

try:
    from ui.python.shadcn import color, icon
except ImportError:
    from PySide6.QtGui import QIcon

    _FALLBACK_TOKENS = {
        "dark": {"background": "#09090b", "card": "#18181b", "border": "#27272a",
                 "foreground": "#fafafa", "mutedForeground": "#a1a1aa", "primary": "#fafafa",
                 "destructive": "#ef4444", "muted": "#27272a"},
        "light": {"background": "#ffffff", "card": "#ffffff", "border": "#e4e4e7",
                  "foreground": "#09090b", "mutedForeground": "#71717a", "primary": "#18181b",
                  "destructive": "#dc2626", "muted": "#f4f4f5"},
    }

    def icon(_name, _size=16, _color=None): return QIcon()

    def color(name, theme="dark"): return _FALLBACK_TOKENS[theme][name]

SETTINGS_MODEL_KEY = "codeSection/agentModel"
BLOCK_KINDS = ("user", "assistant", "reasoning", "tool", "permission", "error", "notice")

# Markdown re-render period while a reply streams: often enough to read as
# live, rare enough that a long reply is not re-laid-out per token.
_RENDER_MS = 50
_OUTPUT_CHARS = 4000
_STATUS_MARKS = {"pending": "...", "running": "...", "completed": "✓", "error": "✗"}


def _label(text: str = "", fmt=Qt.PlainText, name: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(fmt)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextBrowserInteraction if fmt != Qt.PlainText
                                  else Qt.TextSelectableByMouse)
    label.setOpenExternalLinks(False)
    if name:
        label.setObjectName(name)
    return label


class _Block(QFrame):
    """One transcript entry. `kind` is its BLOCK_KINDS name; plain_text() is
    what AgentPanel.blocks() reports for it."""

    kind = ""

    def __init__(self, parent=None, kind: str = ""):
        super().__init__(parent)
        if kind:
            self.kind = kind
        self.setObjectName(f"agentBlock_{self.kind}")
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(8, 6, 8, 6)
        self._column.setSpacing(4)

    def plain_text(self) -> str:
        raise NotImplementedError


class _TextBlock(_Block):
    """A block whose text is fixed when it is made: user, error, notice."""

    def __init__(self, kind: str, text: str, parent=None):
        super().__init__(parent, kind)
        # What the user typed is shown as typed: '*' and '<' are not markup.
        self._label = _label(text, Qt.PlainText, f"agentText_{kind}")
        self._column.addWidget(self._label)

    def plain_text(self) -> str:
        return self._label.text()


class _StreamBlock(_Block):
    """Text that arrives in deltas and renders as Markdown, throttled: the
    first delta starts a timer and later ones only append, so a fast stream
    still repaints every _RENDER_MS instead of waiting for a pause."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._body = _label("", Qt.MarkdownText, f"agentBody_{self.kind}")
        self._body.linkActivated.connect(self._open_link)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_RENDER_MS)
        self._timer.timeout.connect(self._render)

    def append(self, delta: str) -> None:
        self._text += delta
        if not self._timer.isActive():
            self._timer.start()

    def flush(self) -> None:
        self._timer.stop()
        self._render()

    def _render(self) -> None:
        self._body.setText(self._text)

    def plain_text(self) -> str:
        return self._text

    @staticmethod
    def _open_link(href: str) -> None:
        QDesktopServices.openUrl(QUrl(href))


class _AssistantBlock(_StreamBlock):
    kind = "assistant"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._column.addWidget(self._body)


class _ReasoningBlock(_StreamBlock):
    """Collapsed to one header line by default; the header toggles the text."""

    kind = "reasoning"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = QToolButton()
        self._header.setObjectName("agentReasoningHeader")
        self._header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._header.setCheckable(True)
        self._header.setCursor(Qt.PointingHandCursor)
        self._header.toggled.connect(self._body.setVisible)
        self._body.setVisible(False)
        # While the thought streams, a thinking orb (ui/python/fx/orb.py)
        # sits before the header; it stops when the reply settles (flush).
        from ui.python.fx.orb import ThinkingOrb
        self._orb = ThinkingOrb(state="breathing", size=20)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        head.addWidget(self._orb)
        head.addWidget(self._header, 1)
        self._column.addLayout(head)
        self._column.addWidget(self._body)
        self._update_header()
        self._orb.start()

    def append(self, delta: str) -> None:
        super().append(delta)
        self._update_header()

    def flush(self) -> None:
        super().flush()
        self._orb.stop()
        self._orb.hide()

    def set_theme(self, theme: str) -> None:
        self._orb.set_theme(theme)

    def _update_header(self) -> None:
        words = len(self._text.split())
        self._header.setText(f"Thought ({words} words)" if words else "Thinking...")


class _ToolBlock(_Block):
    """One tool call, updated in place as its status changes. The file it
    touches is a visible link; the header toggles input and output."""

    kind = "tool"

    def __init__(self, open_file: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._event: dict = {}
        self._header = QToolButton()
        self._header.setObjectName("agentToolHeader")
        self._header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._header.setCheckable(True)
        self._header.setCursor(Qt.PointingHandCursor)
        self._link = _label("", Qt.RichText, "agentToolLink")
        self._link.linkActivated.connect(open_file)
        self._link.setVisible(False)
        self._error = _label("", Qt.PlainText, "agentText_error")
        self._error.setVisible(False)
        self._detail = _label("", Qt.PlainText, "agentToolDetail")
        self._detail.setVisible(False)
        self._header.toggled.connect(self._detail.setVisible)
        for widget in (self._header, self._link, self._error, self._detail):
            self._column.addWidget(widget)

    def apply_event(self, event: dict) -> None:
        self._event = dict(event)
        tool, title, status = self._tool(), self._title(), self._status()
        self._header.setText(f"{_STATUS_MARKS.get(status, '')} {tool}  {title}".strip())
        source = event.get("input") or {}
        path = source.get("filePath") or source.get("path") or "" if isinstance(source, dict) else ""
        if path:
            name = html.escape(os.path.basename(path) or path)
            self._link.setText(f'<a href="{html.escape(path, quote=True)}">{name}</a>')
            self._link.setToolTip(path)
        self._link.setVisible(bool(path))
        error = event.get("error") or ""
        self._error.setText(error)
        self._error.setVisible(status == "error" and bool(error))
        try:
            shown_input = json.dumps(source, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            shown_input = str(source)
        output = (event.get("output") or "")[:_OUTPUT_CHARS]
        # Plain text: tool output is whatever a command printed, never markup.
        self._detail.setText(f"Input:\n{shown_input}" + (f"\n\nOutput:\n{output}" if output else ""))

    def _tool(self) -> str:
        return self._event.get("tool") or "tool"

    def _title(self) -> str:
        return self._event.get("title") or self._tool()

    def _status(self) -> str:
        return self._event.get("status") or "pending"

    def plain_text(self) -> str:
        return f"{self._tool()} {self._title()} {self._status()}"


class _PermissionBlock(_Block):
    kind = "permission"

    def __init__(self, event: dict, reply: Callable[[str, str], None], parent=None):
        super().__init__(parent)
        self._id = event.get("id", "")
        self._title = event.get("title") or event.get("permission") or "Permission"
        self._answer = ""
        self._reply = reply
        self._label = _label(self._title, Qt.PlainText, "agentPermissionTitle")
        self._column.addWidget(self._label)
        self._buttons = QWidget()
        row = QHBoxLayout(self._buttons)
        row.setContentsMargins(0, 0, 0, 0)
        for text, answer in (("Allow once", "once"), ("Always", "always"), ("Reject", "reject")):
            button = QPushButton(text)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, a=answer: self._answered(a))
            row.addWidget(button)
        row.addStretch(1)
        self._column.addWidget(self._buttons)

    def _answered(self, answer: str) -> None:
        if self._answer:
            return
        self._answer = answer
        self._buttons.setVisible(False)
        self._label.setText(self.plain_text())
        self._reply(self._id, answer)

    def plain_text(self) -> str:
        return f"{self._title} -> {self._answer}" if self._answer else self._title


class AgentPanel(QWidget):
    """Signals:
        openFileRequested(str, int): a file link in the transcript (path, line).
        fileEdited(str): the agent changed this file (absolute path).

    Attributes tests rely on: `input` (QPlainTextEdit), `send_button`,
    `stop_button`, `new_chat_button` (QToolButton/QPushButton),
    `model_combo` (QComboBox), `context_check` (QCheckBox),
    `state_label` (QLabel), `design_check` (QCheckBox "Include design", on
    by default, beside context_check), `quick_button` (QToolButton).
    """

    openFileRequested = Signal(str, int)
    fileEdited = Signal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("agentPanel")
        self._backend = backend
        self._directory = ""
        self._context_provider: Callable[[], dict] | None = None
        self._design_provider: Callable[[], str] | None = None
        self._quick_actions: list = []
        self._blocks: list[_Block] = []
        self._parts: dict[tuple[str, str], _Block] = {}
        # Busy is the backend's word (busy ... idle), not a widget's
        # visibility: the Code tab is often not on screen.
        self._busy = False
        self._usage = [0, 0]
        self._follow = True
        self._theme = "dark"
        self._filling_models = False
        self._build_ui()
        backend.stateChanged.connect(self._state_changed)
        backend.modelsChanged.connect(self._fill_models)
        backend.event.connect(self._on_event)
        self._fill_models(backend.models())
        self._state_changed(backend.state(), backend.detail())
        self.apply_theme("dark")
        self.avatar.start()

    # ---------------------------------------------------------------- API

    def backend(self):
        return self._backend

    def set_context_provider(self, provider: Callable[[], dict] | None) -> None:
        """A function returning EditorTabs.selection_context(), called at send."""
        self._context_provider = provider

    def set_design_provider(self, provider: Callable[[], str] | None) -> None:
        """A function returning the design brief (agent_context.design_brief),
        called at send. When `design_check` is ticked and it returns a
        non-empty string, send() passes context = {**(editor context or {}),
        "design": brief} to backend.send -- the editor context's keys are
        kept as they are, and "Include open file" unticked still drops them.
        (W4)"""
        self._design_provider = provider

    def set_quick_actions(self, actions: list) -> None:
        """agent_context.QuickAction list (label, prompt) for `quick_button`, a
        QToolButton "Quick actions" (InstantPopup) with a QMenu of one action
        per item, in order; the button is hidden when the list is empty.
        Triggering an item calls send(prompt); when send refuses (busy, not
        ready) the prompt is put in `input` instead, so nothing is lost.
        (W4)"""
        self._quick_actions = list(actions or [])
        menu = self.quick_button.menu()
        menu.clear()
        for action in self._quick_actions:
            item = menu.addAction(action.label)
            item.triggered.connect(lambda _checked=False, label=action.label: self.trigger_quick_action(label))
        self.quick_button.setVisible(bool(self._quick_actions))

    def quick_actions(self) -> list:
        """The list last given to set_quick_actions ([] at first). (W4)"""
        return list(self._quick_actions)

    def trigger_quick_action(self, label: str) -> bool:
        """What choosing the menu item with that label does; False when no
        item has that label. (W4)"""
        for action in self._quick_actions:
            if action.label == label:
                if not self.send(action.prompt):
                    self.input.setPlainText(action.prompt)
                return True
        return False

    def set_directory(self, path: str) -> None:
        """The project folder: backend.start(path) when it differs from the
        current one ('' -> backend.stop()). Adds a 'notice' block naming the
        folder when a conversation was already on screen."""
        if path == self._directory:
            return
        self._directory = path
        if not path:
            self._backend.stop()
            return
        if self._blocks:
            self._add(_TextBlock("notice", f"Now working in {path}"))
        self._backend.start(path)
        self._fill_models(self._backend.models())

    def directory(self) -> str:
        return self._directory

    def send(self, text: str) -> bool:
        """What pressing Send does with `text`; False (nothing sent) when the
        text is blank, the backend is not READY, or a reply is in progress."""
        text = (text or "").strip()
        if not text or self._busy or self._backend.state() != READY:
            return False
        context = None
        if self.context_check.isChecked() and self._context_provider is not None:
            context = self._context_provider() or None
        if self.design_check.isChecked() and self._design_provider is not None:
            brief = self._design_provider()
            if brief:
                context = {**(context or {}), "design": brief}
        self._usage = [0, 0]
        self._follow = True
        self._add(_TextBlock("user", text))
        self.input.clear()
        self._set_busy(True)
        self._backend.send(text, self.selected_model(), context)
        return True

    def stop(self) -> None:
        """What pressing Stop does: backend.abort() and a 'notice' "Stopped"."""
        self._backend.abort()
        self._add(_TextBlock("notice", "Stopped"))

    def new_chat(self) -> None:
        """What New chat does."""
        for block in self._blocks:
            block.setParent(None)
            block.deleteLater()
        self._blocks.clear()
        self._parts.clear()
        self._usage = [0, 0]
        self._backend.new_session()
        self._state_changed(self._backend.state(), self._backend.detail())

    def is_busy(self) -> bool:
        return self._busy

    def selected_model(self):
        """The ModelRef picked in the combo, or None."""
        return ModelRef.parse(self.model_combo.currentText())

    def blocks(self) -> list[tuple[str, str]]:
        """The transcript as (kind, plain text) pairs, top to bottom. For a
        tool block the text is '<tool> <title> <status>'; for a permission
        block the title plus, once answered, ' -> <reply>'; for reasoning
        the full text (even when collapsed)."""
        return [(block.kind, block.plain_text()) for block in self._blocks]

    def transcript_text(self) -> str:
        """blocks() as 'kind: text' lines."""
        return "\n".join(f"{kind}: {text}" for kind, text in self.blocks())

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        self._theme = theme = "light" if theme == "light" else "dark"
        c = lambda name: color(name, theme)  # noqa: E731
        for effect in (self.avatar, self.glow, self._input_beam):
            effect.set_theme(theme)
        for block in self._blocks:
            if hasattr(block, "set_theme"):
                block.set_theme(theme)
        self.setStyleSheet(f"""
            QWidget#agentPanel {{ background: {c('background')}; }}
            QLabel {{ color: {c('foreground')}; font-size: 12px; background: transparent; }}
            QLabel#agentCaption {{ font-weight: 600; font-size: 13px; }}
            QLabel#agentText_notice {{ color: {c('mutedForeground')}; font-style: italic; }}
            QLabel#agentText_error {{ color: {c('destructive')}; }}
            QLabel#agentToolDetail {{ color: {c('mutedForeground')}; font-family: Consolas, monospace; }}
            QFrame#agentBlock_user {{ background: {c('muted')}; border-radius: 8px; }}
            QFrame#agentBlock_tool, QFrame#agentBlock_permission {{
                border: 1px solid {c('border')}; border-radius: 8px; }}
            QToolButton#agentReasoningHeader, QToolButton#agentToolHeader {{
                border: none; background: transparent; color: {c('mutedForeground')};
                text-align: left; padding: 0; }}
            QScrollArea#agentTranscript {{ border: none; background: transparent; }}
            QWidget#agentTranscriptBody {{ background: transparent; }}
            QPlainTextEdit {{ background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 6px; padding: 4px 6px; }}
            QPlainTextEdit:focus {{ border-color: {c('primary')}; }}
            QPushButton, QToolButton#agentNewChat, QComboBox {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 6px; padding: 3px 10px; }}
            QPushButton:hover, QToolButton#agentNewChat:hover {{ background: {c('muted')}; }}
            QPushButton:disabled {{ color: {c('mutedForeground')}; }}
            QCheckBox {{ color: {c('mutedForeground')}; }}
        """)
        self._state_changed(self._backend.state(), self._backend.detail())

    # ---------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)

        header = QHBoxLayout()
        # The agent's face (ui/python/fx/avatar.py, Libraries.dev bot-avatars):
        # working while it runs, asleep when it stopped or failed.
        from ui.python.fx.avatar import BotAvatar
        self.avatar = BotAvatar(shape="clover", size=42, state="default", seed=0.61)
        self.avatar.fps = 30.0
        self.avatar.setToolTip("The coding agent")
        header.addWidget(self.avatar)
        caption = QLabel("Agent")
        caption.setObjectName("agentCaption")
        header.addWidget(caption)
        header.addStretch(1)
        self.model_combo = QComboBox()
        self.model_combo.setObjectName("agentModel")
        self.model_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(14)
        self.model_combo.setToolTip("The model the agent uses")
        self.model_combo.currentIndexChanged.connect(self._model_picked)
        self.new_chat_button = QToolButton()
        self.new_chat_button.setObjectName("agentNewChat")
        self.new_chat_button.setText("New chat")
        self.new_chat_button.setIcon(icon("plus"))
        self.new_chat_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.new_chat_button.clicked.connect(self.new_chat)
        header.addWidget(self.new_chat_button)
        column.addLayout(header)
        # A colour sweep under the header while the agent works.
        from ui.python.fx.glow import WorkingGlow
        self.glow = WorkingGlow(height=6)
        column.addWidget(self.glow)
        # Model ids run long ('provider/vendor/Model-35B-A3B-NVFP4'): a row
        # of their own, the full label on hover.
        column.addWidget(self.model_combo)

        self.state_label = _label("", Qt.PlainText, "agentState")
        self.state_label.setVisible(False)
        column.addWidget(self.state_label)

        self._transcript_scroll = QScrollArea()
        self._transcript_scroll.setObjectName("agentTranscript")
        self._transcript_scroll.setWidgetResizable(True)
        self._transcript_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("agentTranscriptBody")
        self._transcript_layout = QVBoxLayout(body)
        self._transcript_layout.setContentsMargins(0, 0, 0, 0)
        self._transcript_layout.setSpacing(8)
        self._transcript_layout.addStretch(1)
        self._transcript_scroll.setWidget(body)
        bar = self._transcript_scroll.verticalScrollBar()
        # Follow the bottom while the user has not scrolled up; rangeChanged
        # fires after the layout grew, so the new maximum is the real one.
        bar.valueChanged.connect(lambda value: setattr(self, "_follow", value >= bar.maximum() - 16))
        bar.rangeChanged.connect(lambda _lo, hi: self._follow and bar.setValue(hi))
        column.addWidget(self._transcript_scroll, 1)

        self.context_check = QCheckBox("Include open file")
        self.context_check.setChecked(True)
        self.context_check.setToolTip("Tell the agent which file is open and what is selected")
        self.design_check = QCheckBox("Include design")
        self.design_check.setChecked(True)
        self.design_check.setToolTip("Tell the agent the design's pages, widgets, tags and binding issues")
        self.quick_button = QToolButton()
        self.quick_button.setText("Quick actions")
        self.quick_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.quick_button.setMenu(QMenu(self.quick_button))
        self.quick_button.setVisible(False)
        options = QHBoxLayout()
        options.addWidget(self.context_check)
        options.addWidget(self.design_check)
        options.addStretch(1)
        options.addWidget(self.quick_button)
        column.addLayout(options)
        self.input = QPlainTextEdit()
        self.input.setObjectName("agentInput")
        self.input.setPlaceholderText("Ask the agent to change the code... (Enter sends, Shift+Enter new line)")
        self.input.setFixedHeight(84)
        self.input.installEventFilter(self)
        column.addWidget(self.input)
        from ui.python.fx.beam import BorderBeam
        self._input_beam = BorderBeam(self.input, size="md", variant="colorful", radius=6)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(icon("player-stop"))
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setVisible(False)
        buttons.addWidget(self.stop_button)
        self.send_button = QPushButton("Send")
        self.send_button.setIcon(icon("send"))
        self.send_button.clicked.connect(lambda: self.send(self.input.toPlainText()))
        buttons.addWidget(self.send_button)
        column.addLayout(buttons)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress \
                and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                return False
            # Enter never inserts a newline; while busy it does nothing and
            # the text stays for later.
            self.send(self.input.toPlainText())
            return True
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------------- backend

    def _state_changed(self, state: str, detail: str) -> None:
        if state == ERROR:
            self._show_state(detail or "The agent failed to start", error=True)
            self._set_busy(False)
        elif state == STARTING:
            self._show_state("Starting the agent...")
        elif state == STOPPED:
            self._show_state("")
            self._set_busy(False)
        elif any(self._usage):
            self._show_usage()
        else:
            self._show_state("")
        self.send_button.setEnabled(state == READY and not self._busy)
        self.state_label.setToolTip(detail if state == READY else "")
        self._set_mood()

    def _show_state(self, text: str, error: bool = False) -> None:
        self.state_label.setText(text)
        self.state_label.setStyleSheet(f"color: {color('destructive', self._theme)};" if error else "")
        self.state_label.setVisible(bool(text))

    def _show_usage(self) -> None:
        self._show_state(f"in {self._usage[0]:,} / out {self._usage[1]:,} tokens".replace(",", " "))

    def _fill_models(self, models) -> None:
        # Refilling the combo moves its index; that must not overwrite the
        # model the user chose (it may simply not be offered right now).
        saved = ModelRef.parse(QSettings("MIL-HMI", "Deployer").value(SETTINGS_MODEL_KEY, "") or "")
        current = self.selected_model()
        labels = [m.label for m in models]
        self._filling_models = True
        try:
            self.model_combo.clear()
            self.model_combo.addItems(labels)
            for wanted in (saved, current, self._backend.default_model()):
                if wanted is not None and wanted.label in labels:
                    self.model_combo.setCurrentIndex(labels.index(wanted.label))
                    break
        finally:
            self._filling_models = False

    def _model_picked(self, _index: int) -> None:
        model = self.selected_model()
        self.model_combo.setToolTip(model.label if model is not None else "The model the agent uses")
        if not self._filling_models and model is not None:
            QSettings("MIL-HMI", "Deployer").setValue(SETTINGS_MODEL_KEY, model.label)

    def _on_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "busy":
            self._set_busy(True)
        elif kind == "idle":
            for block in self._blocks:
                if isinstance(block, _StreamBlock):
                    block.flush()
            self._set_busy(False)
        elif kind in ("text", "reasoning"):
            key = (kind, event.get("id", ""))
            block = self._parts.get(key)
            if block is None:
                block = self._parts[key] = self._add(
                    _AssistantBlock() if kind == "text" else _ReasoningBlock())
            block.append(event.get("delta", ""))
        elif kind == "tool":
            key = ("tool", event.get("id", ""))
            block = self._parts.get(key)
            if block is None:
                block = self._parts[key] = self._add(
                    _ToolBlock(lambda href: self.openFileRequested.emit(href, 0)))
            block.apply_event(event)
        elif kind == "permission":
            self._add(_PermissionBlock(event, self._backend.reply_permission))
        elif kind == "error":
            self._add(_TextBlock("error", event.get("message") or "Unknown error"))
        elif kind == "usage":
            self._usage[0] += int(event.get("input") or 0)
            self._usage[1] += int(event.get("output") or 0)
            self._show_usage()
        elif kind == "file_edited":
            if event.get("path"):
                self.fileEdited.emit(event["path"])

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.stop_button.setVisible(busy)
        self.send_button.setEnabled(not busy and self._backend.state() == READY)
        # The effects say the same thing: the face works, the bar sweeps and
        # the message box glows while a reply is under way.
        (self.glow.start if busy else self.glow.stop)()
        self._input_beam.set_active(busy)
        self._set_mood()

    def _set_mood(self) -> None:
        state = self._backend.state()
        if state in (ERROR, STOPPED):
            self.avatar.set_state("sleeping")
        else:
            self.avatar.set_state("working" if self._busy else "default")

    def _add(self, block: _Block) -> _Block:
        # Blocks go above the trailing stretch so the transcript stays packed
        # at the top.
        self._transcript_layout.insertWidget(self._transcript_layout.count() - 1, block)
        self._blocks.append(block)
        if hasattr(block, "set_theme"):
            block.set_theme(self._theme)
        return block
