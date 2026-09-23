"""designer/ide/agent_backend.py -- what the agent panel talks to.

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). AgentBackend, ScriptedBackend,
build_prompt and SYSTEM_PROMPT are done (skeleton); OpencodeBackend's bodies
are W3's. See docs/CODE_SECTION.md.

A backend runs one conversation with a coding agent about one project
folder. Everything it reports arrives as `event(dict)` in the agent event
vocabulary (designer.ide.opencode_client.EventNormalizer lists it), always
on the GUI thread. The panel never blocks: every method returns at once and
network work happens elsewhere.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from designer.ide.opencode_client import ModelRef

STOPPED, STARTING, READY, ERROR = "stopped", "starting", "ready", "error"

SYSTEM_PROMPT = (
    "You are the coding agent inside EmbeddedDisplay Studio, working in the project folder "
    "of an embedded HMI panel application. project.edsui is the screen design as JSON: the "
    "panel runs it directly, so keep it valid JSON and keep widget ids unique. manifest.json "
    "describes the bundle. Make focused changes with the edit tool, keep the existing style, "
    "and say briefly what you changed and why."
)


def build_prompt(text: str, context: dict | None) -> str:
    """The prompt sent for a user message: the text, then -- when the panel
    passes the editor's selection_context() -- a short block naming the open
    file and cursor line, and the selected lines in a fenced block."""
    text = (text or "").strip()
    if not context or not context.get("path"):
        return text
    name = context.get("relative") or context["path"]
    lines = [text, "", f"(Open in the editor: {name}, cursor on line {context.get('cursor_line', 1)}.)"]
    selected = context.get("text") or ""
    if selected:
        lines += [f"Selected lines {context.get('start_line')}-{context.get('end_line')}:",
                  "```" + (context.get("language") or ""), selected, "```"]
    return "\n".join(lines)


class AgentBackend(QObject):
    """The interface. Subclasses override the methods; the base class keeps
    the state and emits the signals.

    Signals:
        event(dict): one agent event (see module docstring).
        stateChanged(str, str): state (STOPPED, STARTING, READY, ERROR), detail
            -- the detail is shown under the panel's header (the server URL
            when ready, the error sentence on error).
        modelsChanged(list): list[ModelRef] available; emitted when known.
    """

    event = Signal(dict)
    stateChanged = Signal(str, str)
    modelsChanged = Signal(list)

    name = "agent"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = STOPPED
        self._detail = ""
        self._models: list[ModelRef] = []
        self._default: ModelRef | None = None

    # -- state

    def state(self) -> str:
        return self._state

    def detail(self) -> str:
        return self._detail

    def models(self) -> list:
        return list(self._models)

    def default_model(self):
        return self._default

    def _set_state(self, state: str, detail: str = "") -> None:
        if (state, detail) != (self._state, self._detail):
            self._state, self._detail = state, detail
            self.stateChanged.emit(state, detail)

    def _set_models(self, models, default=None) -> None:
        self._models, self._default = list(models), default
        self.modelsChanged.emit(list(self._models))

    # -- the interface

    def start(self, directory: str) -> None:
        """Gets ready to work on `directory` (STARTING then READY or ERROR).
        Starting again with another directory ends the old conversation."""
        raise NotImplementedError

    def stop(self) -> None:
        """Ends the conversation and releases what start acquired; STOPPED."""
        raise NotImplementedError

    def send(self, text: str, model=None, context: dict | None = None) -> None:
        """Sends a user message (model: a ModelRef or None for the default;
        context: EditorTabs.selection_context()). Emits busy ... idle, with
        the reply's events in between, or an error event."""
        raise NotImplementedError

    def abort(self) -> None:
        """Stops the reply in progress (an idle event follows)."""
        raise NotImplementedError

    def reply_permission(self, permission_id: str, reply: str) -> None:
        """'once', 'always' or 'reject' to a permission event."""
        raise NotImplementedError

    def new_session(self) -> None:
        """Forgets the conversation; the next send starts a new one."""
        raise NotImplementedError


class ScriptedBackend(AgentBackend):
    """A backend that replays scripted events: for tests and for trying the
    panel without an agent. `script` maps a user text to the list of events
    to emit (key None = any text); each is emitted from the event loop,
    `interval_ms` apart, so the panel sees them arrive over time. Every call
    is recorded in `calls` as (method, args)."""

    name = "scripted"

    def __init__(self, script: dict | None = None, models=None, interval_ms: int = 0, parent=None):
        super().__init__(parent)
        self.script = dict(script or {})
        self.calls: list[tuple] = []
        self.interval_ms = interval_ms
        self._pending: list[dict] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_next)
        self._initial_models = list(models or [ModelRef("fake", "coder"), ModelRef("fake", "big")])

    def start(self, directory: str) -> None:
        self.calls.append(("start", (directory,)))
        self._set_state(STARTING, directory)
        self._set_models(self._initial_models, self._initial_models[0] if self._initial_models else None)
        self._set_state(READY, "scripted")

    def stop(self) -> None:
        self.calls.append(("stop", ()))
        self._pending.clear()
        self._timer.stop()
        self._set_state(STOPPED)

    def send(self, text: str, model=None, context: dict | None = None) -> None:
        self.calls.append(("send", (text, model, context)))
        events = self.script.get(text, self.script.get(None, [{"type": "text", "id": "p1", "delta": "ok"}]))
        self._pending += [{"type": "busy"}] + [dict(e) for e in events]
        if not events or events[-1].get("type") != "idle":
            self._pending.append({"type": "idle"})
        self._timer.start(self.interval_ms)

    def abort(self) -> None:
        self.calls.append(("abort", ()))
        self._pending = [{"type": "idle"}]
        self._timer.start(0)

    def reply_permission(self, permission_id: str, reply: str) -> None:
        self.calls.append(("reply_permission", (permission_id, reply)))

    def new_session(self) -> None:
        self.calls.append(("new_session", ()))

    def _emit_next(self) -> None:
        if not self._pending:
            return
        self.event.emit(self._pending.pop(0))
        if self._pending:
            self._timer.start(self.interval_ms)


class OpencodeBackend(AgentBackend):
    """The real agent: opencode (owner W3).

    start(directory): in a worker thread -- use $OPENCODE_URL when set (an
    already running server), else start one OpencodeServer (cwd=directory)
    and reuse it for later start() calls with other directories (the
    directory is per request, not per server); then client.providers() ->
    _set_models; start the event reader thread; READY with the URL as detail.
    Failures -> ERROR with the OpencodeError sentence (INSTALL_HINT when
    opencode is missing). All results cross to the GUI thread through a
    private queued signal -- never touch Qt objects from a worker thread.

    The reader thread runs client.events(stop) in a loop, feeding each raw
    event to one EventNormalizer and emitting what it returns; when the
    stream drops it reconnects after 0.5, 1, 2, 4... s (max 5 s) until stop().

    send: creates the session on first use (client.create_session with the
    project folder's name as title), then client.prompt(session,
    build_prompt(text, context), model, SYSTEM_PROMPT) in a worker thread;
    emits {"type":"busy"} at once; an OpencodeError becomes an error event
    followed by idle. abort / reply_permission: worker thread, errors ->
    error event. new_session: drops the session id (next send creates one)
    and resets the normalizer. stop(): stops the reader, and the server
    when this backend started it.

    `server_command` is passed to OpencodeServer (tests use a fake server).
    """

    name = "opencode"

    def __init__(self, server_command=None, parent=None):
        super().__init__(parent)
        raise NotImplementedError

    def start(self, directory: str) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def send(self, text: str, model=None, context: dict | None = None) -> None:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError

    def reply_permission(self, permission_id: str, reply: str) -> None:
        raise NotImplementedError

    def new_session(self) -> None:
        raise NotImplementedError

    def session_id(self) -> str:
        """The current session id, '' before the first send."""
        raise NotImplementedError
