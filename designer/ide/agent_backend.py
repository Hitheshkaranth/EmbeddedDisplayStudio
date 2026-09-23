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

import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from designer.ide.opencode_client import (
    EventNormalizer, ModelRef, OpencodeClient, OpencodeError, OpencodeServer,
)

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

    The reader thread runs client.events(stop) in a loop and hands each raw
    event to the GUI thread, where one EventNormalizer turns it into agent
    events (so new_session never races the reader); when the stream drops it
    reconnects after 0.5, 1, 2, 4... s (max 5 s) until stop().

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

    # (generation, callback, value) from worker threads, delivered queued on
    # the GUI thread. A result whose generation is stale (start/stop/new
    # session happened since) is dropped.
    _posted = Signal(object)

    def __init__(self, server_command=None, parent=None):
        super().__init__(parent)
        self._server_command = server_command
        self._server: OpencodeServer | None = None
        self._client: OpencodeClient | None = None
        self._directory = ""
        self._session = ""
        self._normalizer = EventNormalizer("")
        self._reader_stop: threading.Event | None = None
        self._generation = 0
        self._last_state = ""
        self._posted.connect(self._deliver, Qt.QueuedConnection)

    # ---------------------------------------------------------------- API

    def start(self, directory: str) -> None:
        directory = os.path.abspath(directory) if directory else ""
        if directory == self._directory and self.state() in (STARTING, READY):
            return
        self._stop_reader()
        generation = self._bump()
        self._directory, self._client = directory, None
        self._forget_session()
        self._set_state(STARTING, directory)
        attached = os.environ.get("OPENCODE_URL", "").strip()
        if not attached and self._server is None:
            self._server = OpencodeServer(self._server_command, cwd=directory or None)
        server = None if attached else self._server

        def work():
            url = attached.rstrip("/") if attached else server.start()
            client = OpencodeClient(url, directory)
            models, default = client.providers()
            return client, models, default

        self._run(generation, work, self._started, self._start_failed)

    def stop(self) -> None:
        self._bump()
        self._stop_reader()
        self._client = None
        self._directory = ""
        self._forget_session()
        server, self._server = self._server, None
        if server is not None:
            server.stop()
        self._set_state(STOPPED)

    def send(self, text: str, model=None, context: dict | None = None) -> None:
        self._agent_event({"type": "busy"})
        client = self._client
        if client is None or self.state() != READY:
            self._fail(self.detail() if self.state() == ERROR else "The agent is not ready yet")
            return
        prompt = build_prompt(text, context)
        generation = self._generation

        def send_prompt(session):
            self._run(generation, lambda: client.prompt(session, prompt, model, SYSTEM_PROMPT),
                      lambda _none: None, self._fail)

        if self._session:
            send_prompt(self._session)
            return
        title = os.path.basename(self._directory.rstrip("\\/")) or "Studio"

        def created(session):
            # The session is known here, on the GUI thread, before the prompt
            # goes out: the reply's first events cannot be filtered away.
            self._session = session
            self._normalizer.set_session(session)
            send_prompt(session)

        self._run(generation, lambda: client.create_session(title), created, self._fail)

    def abort(self) -> None:
        client, session = self._client, self._session
        if client is None or not session:
            self._agent_event({"type": "idle"})
            return
        self._run(self._generation, lambda: client.abort(session), lambda _none: None,
                  lambda message: self._agent_event({"type": "error", "message": message}))

    def reply_permission(self, permission_id: str, reply: str) -> None:
        client = self._client
        if client is None:
            return
        self._run(self._generation, lambda: client.reply_permission(permission_id, reply),
                  lambda _none: None,
                  lambda message: self._agent_event({"type": "error", "message": message}))

    def new_session(self) -> None:
        self._forget_session()

    def session_id(self) -> str:
        """The current session id, '' before the first send."""
        return self._session

    # ---------------------------------------------------------------- private

    def _bump(self) -> int:
        self._generation += 1
        return self._generation

    def _forget_session(self) -> None:
        self._session = ""
        self._normalizer.set_session("")
        self._last_state = ""

    def _run(self, generation: int, work, done, failed) -> None:
        """work() on a worker thread; done(result) or failed(sentence) back
        on the GUI thread."""
        def target():
            try:
                self._posted.emit((generation, done, work()))
            except OpencodeError as exc:
                self._posted.emit((generation, failed, str(exc)))
            except Exception as exc:                        # a bug must not kill silently
                self._posted.emit((generation, failed, f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=target, name="opencode-call", daemon=True).start()

    def _deliver(self, posted) -> None:
        generation, callback, value = posted
        if generation == self._generation:
            callback(value)

    def _started(self, result) -> None:
        client, models, default = result
        self._client = client
        self._set_models(models, default)
        self._start_reader(client)
        self._set_state(READY, client.base_url)

    def _start_failed(self, message: str) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.stop()
        self._set_state(ERROR, message)

    def _fail(self, message: str) -> None:
        self._agent_event({"type": "error", "message": message})
        self._agent_event({"type": "idle"})

    def _start_reader(self, client: OpencodeClient) -> None:
        stop = self._reader_stop = threading.Event()
        generation = self._generation
        server = self._server

        def read():
            backoff = 0.5
            while not stop.is_set():
                delivered = False
                try:
                    for raw in client.events(stop):
                        delivered = True
                        self._posted.emit((generation, self._raw_event, raw))
                except OpencodeError:
                    pass
                if stop.is_set():
                    return
                if server is not None and not server.running:
                    self._posted.emit((generation, self._server_died, server.output_tail()))
                    return
                backoff = 0.5 if delivered else min(backoff * 2, 5.0)
                stop.wait(backoff)

        threading.Thread(target=read, name="opencode-events", daemon=True).start()

    def _stop_reader(self) -> None:
        if self._reader_stop is not None:
            self._reader_stop.set()
            self._reader_stop = None

    def _server_died(self, tail: str) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.stop()               # reaps the child and closes its pipe
        self._client = None
        self._set_state(ERROR, "opencode stopped unexpectedly" + (f":\n{tail}" if tail else ""))
        if self._last_state == "busy":
            self._agent_event({"type": "idle"})

    def _raw_event(self, raw: dict) -> None:
        for event in self._normalizer.feed(raw):
            self._agent_event(event)

    def _agent_event(self, event: dict) -> None:
        # The backend says busy the moment Send is pressed and the stream
        # says it again once opencode starts: the panel hears it once.
        kind = event.get("type")
        if kind in ("busy", "idle"):
            if kind == self._last_state:
                return
            self._last_state = kind
        self.event.emit(event)
