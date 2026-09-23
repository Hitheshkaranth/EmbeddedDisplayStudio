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

import functools
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal

from designer.ide.opencode_client import ModelRef
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

try:
    from ui.python.shadcn import color as _shadcn_color, icon as _shadcn_icon
except ImportError:
    _FALLBACK_TOKENS = {
        "dark": {"background": "#09090b", "card": "#18181b", "border": "#27272a",
                 "foreground": "#fafafa", "mutedForeground": "#a1a1aa", "primary": "#fafafa",
                 "destructive": "#ef4444", "muted": "#27272a"},
        "light": {"background": "#ffffff", "card": "#ffffff", "border": "#e4e4e7",
                  "foreground": "#09090b", "mutedForeground": "#71717a", "primary": "#18181b",
                  "destructive": "#dc2626", "muted": "#f4f4f5"},
    }
    def _shadcn_color(name, theme="dark"):
        return _FALLBACK_TOKENS.get(theme, _FALLBACK_TOKENS["dark"]).get(name, "#000000")
    def _shadcn_icon(_name, _size=16, _color=None):
        from PySide6.QtGui import QIcon
        return QIcon()

SETTINGS_MODEL_KEY = "codeSection/agentModel"
BLOCK_KINDS = ("user", "assistant", "reasoning", "tool", "permission", "error", "notice")


class _BlockFrame(QFrame):
    """Base class for transcript block widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def plain_text(self) -> str:
        """Return the block's plain text for blocks()."""
        raise NotImplementedError


class _UserBlock(_BlockFrame):
    """User message block - plain text."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._label = QLabel(text)
        self._label.setTextFormat(Qt.MarkdownText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._label.setOpenExternalLinks(False)
        layout.addWidget(self._label)

    def plain_text(self) -> str:
        return self._label.text()


class _AssistantBlock(_BlockFrame):
    """Assistant message block - Markdown rendered, delta-appended."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._text = ""
        self._label = QLabel()
        self._label.setTextFormat(Qt.MarkdownText)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._label.setOpenExternalLinks(False)
        self._label.linkActivated.connect(self._on_link)
        layout.addWidget(self._label)
        self._render_timer: QTimer | None = None

    def _schedule_render(self) -> None:
        if self._render_timer is None:
            self._render_timer = QTimer(self)
            self._render_timer.setSingleShot(True)
            self._render_timer.timeout.connect(self._do_render)
        self._render_timer.start(50)

    def _do_render(self) -> None:
        self._label.setText(self._text)

    def append_delta(self, delta: str) -> None:
        self._text += delta
        self._schedule_render()

    def plain_text(self) -> str:
        return self._text

    def _on_link(self, href: str) -> None:
        pass


class _ReasoningBlock(_BlockFrame):
    """Reasoning/thinking block - collapsible by default."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._collapsed = True
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._header = QLabel("Thinking...")
        self._header.setStyleSheet("font-weight: bold;")
        self._header.mousePressEvent = lambda e: self._toggle()  # type: ignore
        self._header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout.addWidget(self._header)
        self._body = QLabel("")
        self._body.setTextFormat(Qt.MarkdownText)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._body.setOpenExternalLinks(False)
        self._body.setVisible(False)
        self._layout.addWidget(self._body)

    def _toggle(self) -> None:
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._update_header()

    def _update_header(self) -> None:
        if self._text:
            words = len(self._text.split())
            self._header.setText(f"Thought ({words} words)")
        else:
            self._header.setText("Thinking...")

    def append_delta(self, delta: str) -> None:
        self._text += delta
        self._update_header()

    def plain_text(self) -> str:
        return self._text


class _ToolBlock(_BlockFrame):
    """Tool call block with status, input/output, and file links."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tool = ""
        self._title = ""
        self._status = ""
        self._input = ""
        self._output = ""
        self._error = ""
        self._expanded = False
        self._file_path = ""
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._header = QLabel("tool title ...")
        self._header.mousePressEvent = lambda e: self._toggle()  # type: ignore
        self._layout.addWidget(self._header)
        self._detail = QLabel("")
        self._detail.setVisible(False)
        self._detail.setTextFormat(Qt.RichText)
        self._detail.setWordWrap(True)
        self._detail.setTextInteractionFlags(Qt.TextBrowserInteraction)
        
        self._layout.addWidget(self._detail)

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        self._update_detail()

    def update(self, tool: str, title: str, status: str,
               input_data: dict | str, output: str, error: str) -> None:
        self._tool = tool
        self._title = title
        self._status = status
        if isinstance(input_data, dict):
            self._input = str(input_data)
        else:
            self._input = str(input_data)
        self._output = output
        self._error = error
        # Extract file path from input
        try:
            d = input_data if isinstance(input_data, dict) else {}
            self._file_path = d.get("filePath") or d.get("path") or ""
        except Exception:
            self._file_path = ""
        self._update_header()
        self._update_detail()

    def _update_header(self) -> None:
        if self._status == "running":
            status_str = "..."
        elif self._status == "completed":
            status_str = "done"
        elif self._status == "error":
            status_str = f"error: {self._error}"
        else:
            status_str = self._status or "pending"
        self._header.setText(f"{self._tool} {self._title} {status_str}")

    def _update_detail(self) -> None:
        parts = []
        if self._file_path:
            parts.append(f'<a href="{self._file_path}">{self._file_path}</a>')
        if self._input:
            parts.append(f"Input:\n{self._input}")
        if self._output:
            parts.append(f"Output:\n{self._output[:4000]}")
        self._detail.setText("\n\n".join(parts) if parts else "")

    def plain_text(self) -> str:
        status_map = {"pending": "pending", "running": "...",
                      "completed": "completed", "error": "error"}
        st = status_map.get(self._status, self._status or "pending")
        return f"{self._tool} {self._title} {st}"


class _PermissionBlock(_BlockFrame):
    """Permission request block with Allow/Always/Reject buttons."""

    permission_replied = Signal(str, str)  # (id, reply)

    def __init__(self, id_: str, permission: str, title: str, parent=None):
        super().__init__(parent)
        self._id = id_
        self._title = title
        self._answered: str | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._label = QLabel(title)
        self._label.setStyleSheet("font-weight: bold;")
        self._layout.addWidget(self._label)
        btn_h = QHBoxLayout()
        self._once_btn = QPushButton("Allow once")
        self._always_btn = QPushButton("Always")
        self._reject_btn = QPushButton("Reject")
        for btn in (self._once_btn, self._always_btn, self._reject_btn):
            btn.clicked.connect(self._on_click)
            btn_h.addWidget(btn)
        self._layout.addLayout(btn_h)

    def _on_click(self) -> None:
        btn = self.sender()
        if btn is self._once_btn:
            reply = "once"
        elif btn is self._always_btn:
            reply = "always"
        else:
            reply = "reject"
        self._answered = reply
        self._button_click(reply)
        self.permission_replied.emit(self._id, reply)

    def _button_click(self, reply: str) -> None:
        # Remove buttons from layout and show answer
        for btn in (self._once_btn, self._always_btn, self._reject_btn):
            btn.setVisible(False)
        self._label.setText(f"{self._title} -> {reply}")

    def plain_text(self) -> str:
        if self._answered:
            return f"{self._title} -> {self._answered}"
        return self._title


class _ErrorBlock(_BlockFrame):
    """Error message block."""

    def __init__(self, message: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(message)
        self._label.setStyleSheet("color: #ef4444;")
        layout.addWidget(self._label)

    def plain_text(self) -> str:
        return self._label.text()


class _NoticeBlock(_BlockFrame):
    """Quiet one-line note."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(text)
        self._label.setStyleSheet("color: #a1a1aa; font-style: italic;")
        layout.addWidget(self._label)

    def plain_text(self) -> str:
        return self._label.text()


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
        self._backend = backend
        self._directory: str = ""
        self._context_provider: Callable[[], dict | None] | None = None
        self._blocks: list[_BlockFrame] = []
        self._part_ids: dict[str, str] = {}  # (type, id) -> block index
        self.context_check: QCheckBox
        self.input: QPlainTextEdit
        self.send_button: QPushButton
        self.stop_button: QPushButton
        self.new_chat_button: QToolButton
        self.model_combo: QComboBox
        self.state_label: QLabel

        self._reply_usage_input: int = 0
        self._reply_usage_output: int = 0

        self._build_ui()
        self._connect_backend()
        self.apply_theme("dark")

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(6)

        # ---- header ----
        header = QHBoxLayout()
        header.setSpacing(6)

        caption = QLabel("Agent")
        caption.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(caption)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(120)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        header.addWidget(self.model_combo)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        header.addWidget(spacer)

        self.new_chat_button = QToolButton()
        self.new_chat_button.setText("+")
        self.new_chat_button.clicked.connect(self.new_chat)
        header.addWidget(self.new_chat_button)

        main.addLayout(header)

        # ---- state line ----
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        self.state_label.setVisible(False)
        main.addWidget(self.state_label)

        # ---- transcript ----
        self._transcript_scroll = QScrollArea()
        self._transcript_scroll.setWidgetResizable(True)
        self._transcript_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._transcript_widget = QWidget()
        self._transcript_layout = QVBoxLayout(self._transcript_widget)
        self._transcript_layout.setContentsMargins(0, 0, 0, 0)
        self._transcript_layout.setSpacing(6)
        self._transcript_scroll.setWidget(self._transcript_widget)
        main.addWidget(self._transcript_scroll)

        # ---- composer ----
        composer = QVBoxLayout()
        composer.setSpacing(4)

        # Context checkbox
        self.context_check = QCheckBox("Include open file")
        self.context_check.setChecked(True)
        composer.addWidget(self.context_check)

        # Input
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Message...")
        self.input.installEventFilter(self)
        composer.addWidget(self.input)

        # Buttons
        btn_row = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._do_send)
        self.send_button.setMinimumWidth(60)
        btn_row.addWidget(self.send_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setVisible(False)
        self.stop_button.setMinimumWidth(60)
        btn_row.addWidget(self.stop_button)

        btn_row.addStretch()
        composer.addLayout(btn_row)

        main.addLayout(composer)

        self._scrolled_to_bottom = True

    def _connect_backend(self) -> None:
        self._backend.stateChanged.connect(self._on_state_changed)
        self._backend.modelsChanged.connect(self._on_models_changed)
        self._backend.event.connect(self._on_event)

    def _on_model_changed(self, index: int) -> None:
        model = self.selected_model()
        self._save_model(model)

    def _on_models_changed(self, models: list) -> None:
        self._populate_models(models)

    def _populate_models(self, models: list) -> None:
        saved = self._get_saved_model()
        current_index = self.model_combo.currentIndex()
        current_text = self.model_combo.currentText() if current_index >= 0 else ""

        self.model_combo.clear()
        for m in models:
            self.model_combo.addItem(m.label)

        if saved and any(m.label == saved for m in models):
            for i, m in enumerate(models):
                if m.label == saved:
                    self.model_combo.setCurrentIndex(i)
                    return
        elif current_text and any(m.label == current_text for m in models):
            for i, m in enumerate(models):
                if m.label == current_text:
                    self.model_combo.setCurrentIndex(i)
                    return

        default = self._backend.default_model()
        if default:
            for i, m in enumerate(models):
                if m.label == default.label:
                    self.model_combo.setCurrentIndex(i)
                    return
        elif models:
            self.model_combo.setCurrentIndex(0)

    def _get_saved_model(self) -> str | None:
        from PySide6.QtCore import QSettings
        settings = QSettings("MIL-HMI", "Deployer")
        val = settings.value(SETTINGS_MODEL_KEY, "", type=str)
        if val:
            return val
        return None

    def _save_model(self, model) -> None:
        from PySide6.QtCore import QSettings
        if model is not None:
            settings = QSettings("MIL-HMI", "Deployer")
            settings.setValue(SETTINGS_MODEL_KEY, model.label)

    def _on_state_changed(self, state: str, detail: str) -> None:
        if state == "ready":
            self.state_label.setText(detail)
            self.state_label.setVisible(False)
        elif state == "starting":
            self.state_label.setText(detail)
            self.state_label.setVisible(True)
        elif state == "error":
            self.state_label.setText(detail)
            self.state_label.setVisible(True)

    def _on_event(self, event: dict) -> None:
        etype = event.get("type")
        if etype == "busy":
            self._on_busy()
        elif etype == "idle":
            self._on_idle()
        elif etype == "text":
            self._on_text(event)
        elif etype == "reasoning":
            self._on_reasoning(event)
        elif etype == "tool":
            self._on_tool(event)
        elif etype == "permission":
            self._on_permission(event)
        elif etype == "error":
            self._on_error(event)
        elif etype == "usage":
            self._on_usage(event)
        elif etype == "file_edited":
            path = event.get("path", "")
            if path:
                self.fileEdited.emit(path)
        # else: unknown type, ignored

    def _on_busy(self) -> None:
        self.send_button.setEnabled(False)
        self.stop_button.setVisible(True)
        self._reply_usage_input = 0
        self._reply_usage_output = 0

    def _on_idle(self) -> None:
        self.send_button.setEnabled(True)
        self.stop_button.setVisible(False)

    def _on_text(self, event: dict) -> None:
        pid = event.get("id", "")
        delta = event.get("delta", "")
        idx = self._part_ids.get(("text", pid))
        if idx is None:
            block = _AssistantBlock()
            self._blocks.append(block)
            self._part_ids[("text", pid)] = len(self._blocks) - 1
            self._transcript_layout.addWidget(block)
            idx = len(self._blocks) - 1
        self._blocks[idx].append_delta(delta)
        self._ensure_bottom()

    def _on_reasoning(self, event: dict) -> None:
        pid = event.get("id", "")
        delta = event.get("delta", "")
        idx = self._part_ids.get(("reasoning", pid))
        if idx is None:
            block = _ReasoningBlock()
            self._blocks.append(block)
            self._part_ids[("reasoning", pid)] = len(self._blocks) - 1
            self._transcript_layout.addWidget(block)
            idx = len(self._blocks) - 1
        self._blocks[idx].append_delta(delta)
        self._ensure_bottom()

    def _on_tool(self, event: dict) -> None:
        pid = event.get("id", "")
        tool = event.get("tool", "")
        status = event.get("status", "pending")
        title = event.get("title", tool)
        input_data = event.get("input", {})
        output = event.get("output", "")
        error = event.get("error", "")

        idx = self._part_ids.get(("tool", pid))
        if idx is None:
            block = _ToolBlock()
            self._blocks.append(block)
            self._part_ids[("tool", pid)] = len(self._blocks) - 1
            self._transcript_layout.addWidget(block)
            block._detail.linkActivated.connect(lambda href, p=self: p.openFileRequested.emit(href, 0))
            idx = len(self._blocks) - 1
        self._blocks[idx].update(tool, title, status, input_data, output, error)

        if status == "completed" or status == "error":
            self._ensure_bottom()

    def _on_permission(self, event: dict) -> None:
        pid = event.get("id", "")
        permission = event.get("permission", "")
        title = event.get("title", permission)
        block = _PermissionBlock(pid, permission, title)
        block.permission_replied.connect(self._backend.reply_permission)
        self._blocks.append(block)
        self._transcript_layout.addWidget(block)
        self._ensure_bottom()

    def _on_error(self, event: dict) -> None:
        message = event.get("message", "Unknown error")
        block = _ErrorBlock(message)
        self._blocks.append(block)
        self._transcript_layout.addWidget(block)
        self._ensure_bottom()

    def _on_usage(self, event: dict) -> None:
        self._reply_usage_input += event.get("input", 0)
        self._reply_usage_output += event.get("output", 0)
        self.state_label.setText(
            f"in {self._reply_usage_input} / out {self._reply_usage_output} tokens"
        )

    def _ensure_bottom(self) -> None:
        if not self._scrolled_to_bottom:
            return
        bar = self._transcript_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_scroll(self) -> None:
        bar = self._transcript_scroll.verticalScrollBar()
        self._scrolled_to_bottom = bar.value() >= bar.maximum() - 10

    def _do_send(self) -> None:
        self.send(self.input.toPlainText())

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == event.Type.KeyPress:
            key = event.key()
            mod = event.modifiers()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if mod & Qt.ShiftModifier:
                    return False  # let it through (newline)
                self._do_send()
                return True  # consume
        return super().eventFilter(obj, event)

    def backend(self):
        return self._backend

    def set_context_provider(self, provider: Callable[[], dict] | None) -> None:
        """A function returning EditorTabs.selection_context(), called at send."""
        self._context_provider = provider

    def set_directory(self, path: str) -> None:
        """The project folder: backend.start(path) when it differs from the
        current one ('' -> backend.stop()). Adds a 'notice' block naming the
        folder when a conversation was already on screen."""
        if path == "":
            self._backend.stop()
            self._directory = ""
            return

        if path != self._directory:
            if self._blocks:
                notice = _NoticeBlock(f"Switched to {path}")
                self._blocks.append(notice)
                self._transcript_layout.addWidget(notice)
            self._backend.start(path)
            self._directory = path
            self._populate_models(self._backend.models())

    def directory(self) -> str:
        return self._directory

    def send(self, text: str) -> bool:
        """What pressing Send does with `text`; False (nothing sent) when the
        text is blank, the backend is not READY, or a reply is in progress."""
        text = text.strip()
        if not text:
            return False
        if self._backend.state() != "ready":
            return False
        if self.is_busy():
            return False

        context = None
        if self.context_check.isChecked() and self._context_provider:
            context = self._context_provider()

        model = self.selected_model()
        self._backend.send(text, model=model, context=context)
        # Add a user block to the transcript
        user_block = _UserBlock(text)
        self._blocks.append(user_block)
        self._transcript_layout.addWidget(user_block)
        self.input.setPlainText("")
        return True

    def stop(self) -> None:
        """What pressing Stop does: backend.abort() and a 'notice' "Stopped"."""
        self._backend.abort()
        notice = _NoticeBlock("Stopped")
        self._blocks.append(notice)
        self._transcript_layout.addWidget(notice)

    def new_chat(self) -> None:
        """What New chat does."""
        self._blocks.clear()
        while self._transcript_layout.count():
            item = self._transcript_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._part_ids.clear()
        self._backend.new_session()

    def is_busy(self) -> bool:
        return self._backend.state() in ("starting", "ready") and self.stop_button.isVisible()

    def selected_model(self):
        """The ModelRef picked in the combo, or None."""
        text = self.model_combo.currentText()
        return ModelRef.parse(text) if text else None

    def blocks(self) -> list[tuple[str, str]]:
        """The transcript as (kind, plain text) pairs, top to bottom."""
        result = []
        for b in self._blocks:
            if isinstance(b, _UserBlock):
                result.append(("user", b.plain_text()))
            elif isinstance(b, _AssistantBlock):
                result.append(("assistant", b.plain_text()))
            elif isinstance(b, _ReasoningBlock):
                result.append(("reasoning", b.plain_text()))
            elif isinstance(b, _ToolBlock):
                result.append(("tool", b.plain_text()))
            elif isinstance(b, _PermissionBlock):
                result.append(("permission", b.plain_text()))
            elif isinstance(b, _ErrorBlock):
                result.append(("error", b.plain_text()))
            elif isinstance(b, _NoticeBlock):
                result.append(("notice", b.plain_text()))
        return result

    def transcript_text(self) -> str:
        """blocks() as 'kind: text' lines."""
        lines = []
        for kind, text in self.blocks():
            lines.append(f"{kind}: {text}")
        return "\n".join(lines)

    def apply_theme(self, theme: str) -> None:
        """'dark' or 'light'."""
        theme = "light" if theme == "light" else "dark"
        c = lambda name: _shadcn_color(name, theme)

        self.setStyleSheet(f"""
            QWidget#agentPanel {{ background: {c('background')}; }}
            QLabel#agentCaption {{ background: transparent; color: {c('mutedForeground')}; font-weight: bold; font-size: 13px; }}
            QLabel#agentState {{ background: transparent; color: {c('foreground')}; }}
            QScrollArea#agentTranscript {{ border: none; background: transparent; }}
            QWidget#agentTranscriptWidget {{ background: transparent; }}
            QPlainTextEdit {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 6px;
                padding: 4px 8px; font-size: 12px;
            }}
            QPlainTextEdit:focus {{ border-color: {c('primary')}; }}
            QPushButton {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 6px;
                padding: 4px 12px; font-size: 12px;
            }}
            QPushButton:hover {{ background: {c('muted')}; }}
            QPushButton:disabled {{ color: {c('mutedForeground')}; }}
            QToolButton {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 6px;
                padding: 2px 8px; font-size: 14px;
            }}
            QToolButton:hover {{ background: {c('muted')}; }}
            QComboBox {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')}; border-radius: 5px;
                padding: 2px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {c('card')}; color: {c('foreground')};
                border: 1px solid {c('border')};
                selection-background-color: {c('muted')};
            }}
            QScrollBar:vertical {{ background: {c('muted')}; width: 8px; border-radius: 4px; }}
            QScrollBar::handle:vertical {{ background: {c('border')}; border-radius: 4px; min-height: 20px; }}
            QCheckBox {{ color: {c('foreground')}; font-size: 12px; }}
            QLabel {{ color: {c('foreground')}; font-size: 12px; }}
        """)