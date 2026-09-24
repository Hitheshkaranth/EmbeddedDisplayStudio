"""designer/ide/opencode_client.py -- talk to an opencode server (no Qt here).

Standard library only (urllib, subprocess, threading, json) -- no requests,
no Qt. See docs/CODE_SECTION.md, "opencode integration" and "The agent event
vocabulary".

opencode (https://opencode.ai, `npm i -g opencode-ai`) is a coding agent
with a headless HTTP server, `opencode serve`. The endpoints used here (all
take the query parameter `directory=<project root>`, which scopes sessions,
tools and events to that folder):

    GET  /config/providers           {"providers":[{"id","name","models":{id:{...,"name"}}}],
                                      "default":{providerID: modelID}}
    POST /session                    body {"title"} -> {"id": "ses_...", ...}
    POST /session/{id}/prompt_async  body {"parts":[{"type":"text","text"}],
                                      "model":{"providerID","modelID"}?, "system"?}
                                      -> 204, the reply streams on /event
    POST /session/{id}/abort         -> true
    POST /permission/{requestID}/reply  body {"reply":"once"|"always"|"reject"}
    GET  /event                      text/event-stream, one JSON object per
                                      `data:` line: {"id","type","properties"}

A real recording of one prompt that edited a file is in
tests/fixtures/opencode_events_edit.sse -- read it (grep it; it is ~250 events)
before writing EventNormalizer.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

# The line `opencode serve` prints once it listens, e.g.
# "opencode server listening on http://127.0.0.1:4096".
LISTENING_PREFIX = "opencode server listening on "
INSTALL_HINT = "opencode is not installed: run  npm i -g opencode-ai  and reopen the Code section"

_TAIL_LINES = 50
_BODY_EXCERPT = 300
# opencode sends a heartbeat every ~10 s; a stream silent for this long is
# treated as dead and reopened by the caller.
_STREAM_IDLE_TIMEOUT = 60.0
_REPLIES = ("once", "always", "reject")


class OpencodeError(Exception):
    """Anything that went wrong talking to opencode; the message is a
    sentence fit for the agent panel (HTTP status and body excerpt
    included for HTTP errors)."""


@dataclass(frozen=True)
class ModelRef:
    """provider_id/model_id as opencode names them; label is what the model
    picker shows: 'provider_id/model_id'."""
    provider_id: str
    model_id: str

    @property
    def label(self) -> str:
        return f"{self.provider_id}/{self.model_id}"

    @staticmethod
    def parse(text: str) -> Optional["ModelRef"]:
        """'provider/model/with/slashes' -> ModelRef('provider', 'model/with/slashes');
        None when there is no '/' or either side is empty."""
        provider, sep, model = (text or "").partition("/")
        return ModelRef(provider, model) if sep and provider and model else None


def find_opencode() -> Optional[str]:
    """The opencode executable: $OPENCODE_BIN when it names a file, else
    shutil.which('opencode') (which finds opencode.cmd on Windows), else
    %APPDATA%\\npm\\opencode.cmd on Windows; None when none exists."""
    configured = os.environ.get("OPENCODE_BIN")
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("opencode")
    if found:
        return found
    if os.name == "nt":
        shim = os.path.join(os.environ.get("APPDATA", ""), "npm", "opencode.cmd")
        if os.path.isfile(shim):
            return shim
    return None


class OpencodeServer:
    """One `opencode serve --hostname 127.0.0.1 --port <port>` child process.

    `command` is the argv prefix to run instead of [find_opencode()] (tests
    pass [sys.executable, 'fake_server.py']); the arguments 'serve',
    '--hostname', '127.0.0.1', '--port', str(port) are appended. The child
    runs with cwd=`cwd`, stdout and stderr merged into one pipe that a daemon
    thread keeps draining (so the child never blocks on a full pipe) and
    whose last 50 lines are kept for error messages. On Windows the child is
    started with CREATE_NO_WINDOW.
    """

    def __init__(self, command: Optional[Sequence[str]] = None, cwd: Optional[str] = None,
                 port: int = 0):
        self._command = list(command) if command else None
        self._cwd = cwd
        self._port = port
        self._proc: Optional[subprocess.Popen] = None
        self._url: Optional[str] = None
        self._listening: Optional[str] = None
        self._tail: collections.deque[str] = collections.deque(maxlen=_TAIL_LINES)
        self._lock = threading.Lock()
        self._heard = threading.Event()

    def start(self, timeout: float = 30.0) -> str:
        """Starts the child and waits for the LISTENING_PREFIX line; returns
        the base URL (no trailing slash) and sets `url`. Raises OpencodeError
        -- INSTALL_HINT when there is no executable; the child's output tail
        when it exits or does not listen within `timeout` (the child is
        stopped then). Calling start on a running server returns its url."""
        if self.running:
            return self._url
        self.stop()
        prefix = self._command
        if prefix is None:
            executable = find_opencode()
            if executable is None:
                raise OpencodeError(INSTALL_HINT)
            prefix = [executable]
        argv = list(prefix) + ["serve", "--hostname", "127.0.0.1", "--port", str(self._port)]
        self._tail.clear()
        self._heard.clear()
        self._listening = None
        try:
            self._proc = subprocess.Popen(
                argv, cwd=self._cwd or None, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # opencode prints UTF-8 whatever the console code page is.
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        except OSError as exc:
            raise OpencodeError(f"Could not start opencode ({argv[0]}): {exc}") from exc
        threading.Thread(target=self._drain, args=(self._proc,), name="opencode-output",
                         daemon=True).start()
        deadline = time.monotonic() + timeout
        # Wait in short steps so a child that dies early is reported at once
        # rather than after the whole timeout.
        while not self._heard.wait(0.1):
            if self._proc.poll() is not None:
                self._heard.wait(0.3)       # let the drain thread catch the last lines
                if self._listening is None:
                    code = self._proc.returncode
                    self.stop()
                    raise OpencodeError(self._failure(f"opencode exited (code {code}) before listening"))
                break
            if time.monotonic() > deadline:
                self.stop()
                raise OpencodeError(self._failure(f"opencode did not start listening within {timeout:g} s"))
        self._url = self._listening
        return self._url

    def stop(self) -> None:
        """Terminates the child (and on Windows its process tree, since
        opencode.cmd starts node which starts the server), waits up to 3 s,
        then kills. Idempotent; url becomes None."""
        proc, self._proc, self._url = self._proc, None, None
        if proc is None:
            return
        if proc.poll() is not None:
            _close_pipe(proc)
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.terminate()
        try:
            proc.wait(3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(3)
        _close_pipe(proc)

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._url is not None

    @property
    def url(self) -> Optional[str]:
        return self._url if self.running else None

    def output_tail(self) -> str:
        """The last lines the child printed, joined with newlines."""
        with self._lock:
            return "\n".join(self._tail)

    def _drain(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            with self._lock:
                self._tail.append(line)
            if self._listening is None and LISTENING_PREFIX in line:
                self._listening = line.split(LISTENING_PREFIX, 1)[1].strip().rstrip("/")
                self._heard.set()

    def _failure(self, sentence: str) -> str:
        tail = self.output_tail().strip()
        return f"{sentence}:\n{tail}" if tail else sentence


class OpencodeClient:
    """Blocking HTTP calls to one server for one project directory. Every
    request adds ?directory=<directory> (URL-encoded). Methods raise
    OpencodeError on connection errors, HTTP >= 400 and bad JSON."""

    def __init__(self, base_url: str, directory: str, timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._directory = directory
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def directory(self) -> str:
        return self._directory

    def providers(self) -> tuple[list[ModelRef], Optional[ModelRef]]:
        """Every model of every provider (providers in the order given,
        models sorted by id) and the default: the model opencode's own
        config names (GET /config "model", what `opencode run` uses) when it
        is listed, else the first provider in the `default` map that is also
        listed, else None."""
        configured = ModelRef.parse(self._configured_model())
        data = self._call("GET", "/config/providers")
        if not isinstance(data, dict):
            raise OpencodeError("opencode sent no provider list")
        models, listed = [], set()
        for provider in data.get("providers") or []:
            pid = provider.get("id") or ""
            for mid in sorted(provider.get("models") or {}):
                models.append(ModelRef(pid, mid))
                listed.add((pid, mid))
        # The per-provider `default` map starts with whichever provider
        # sorts first (on this bench an OpenRouter image model); the user's
        # configured model is what they expect the agent to use.
        if configured is not None and (configured.provider_id, configured.model_id) in listed:
            return models, configured
        for pid, mid in (data.get("default") or {}).items():
            if (pid, mid) in listed:
                return models, ModelRef(pid, mid)
        return models, None

    def create_session(self, title: str = "Studio") -> str:
        """Returns the new session id."""
        data = self._call("POST", "/session", {"title": title})
        sid = data.get("id") if isinstance(data, dict) else None
        if not sid:
            raise OpencodeError("opencode created a session without an id")
        return sid

    def prompt(self, session_id: str, text: str, model: Optional[ModelRef] = None,
               system: Optional[str] = None) -> None:
        """POST prompt_async; returns as soon as the server accepted it."""
        body: dict = {"parts": [{"type": "text", "text": text}]}
        if model is not None:
            body["model"] = {"providerID": model.provider_id, "modelID": model.model_id}
        if system:
            body["system"] = system
        self._call("POST", f"/session/{urllib.parse.quote(session_id)}/prompt_async", body)

    def abort(self, session_id: str) -> None:
        self._call("POST", f"/session/{urllib.parse.quote(session_id)}/abort")

    def reply_permission(self, permission_id: str, reply: str) -> None:
        """reply is 'once', 'always' or 'reject' (ValueError otherwise)."""
        if reply not in _REPLIES:
            raise ValueError(f"reply must be one of {_REPLIES}, not {reply!r}")
        self._call("POST", f"/permission/{urllib.parse.quote(permission_id)}/reply", {"reply": reply})

    def events(self, stop: Optional[threading.Event] = None) -> Iterator[dict]:
        """Opens GET /event and yields each event dict as it arrives. Returns
        when the stream ends or `stop` is set (checked at least once a second:
        use a socket timeout of <= 1 s and keep reading on timeout). SSE
        framing: lines starting 'data:' carry JSON (several data lines of one
        event are joined with '\\n'); a blank line ends an event; lines
        starting ':' are comments; malformed JSON is skipped."""
        # A read that times out leaves Python's socket file unusable, so the
        # stream is read blocking and `stop` is honoured by a watcher that
        # shuts the socket down, which ends the blocked read at once.
        request = urllib.request.Request(self._url("/event"), headers={"Accept": "text/event-stream"})
        try:
            response = urllib.request.urlopen(request, timeout=_STREAM_IDLE_TIMEOUT)
        except (urllib.error.URLError, OSError) as exc:
            raise OpencodeError(self._unreachable(exc)) from exc
        done = threading.Event()
        stop = stop or threading.Event()

        def watch():
            while not done.is_set():
                if stop.wait(0.25):
                    _shutdown(response)
                    return
        threading.Thread(target=watch, name="opencode-events-stop", daemon=True).start()
        data: list[str] = []
        try:
            while not stop.is_set():
                try:
                    raw = response.readline()
                except (OSError, ValueError):
                    return                      # shut down by stop(), or the stream died
                if not raw:
                    return
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                    continue
                if line == "" and data:
                    payload, data = "\n".join(data), []
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and not stop.is_set():
                        yield event
        finally:
            done.set()
            response.close()

    # ------------------------------------------------------------ private

    def _configured_model(self) -> str:
        try:
            config = self._call("GET", "/config")
        except OpencodeError:
            return ""                   # older servers: fall back to the default map
        return (config or {}).get("model") or "" if isinstance(config, dict) else ""

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}?{urllib.parse.urlencode({'directory': self._directory})}"

    def _call(self, method: str, path: str, body: Optional[dict] = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self._url(path), data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            excerpt = exc.read(_BODY_EXCERPT).decode("utf-8", "replace").strip()
            raise OpencodeError(f"opencode answered HTTP {exc.code} to {method} {path}"
                                + (f": {excerpt}" if excerpt else "")) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise OpencodeError(self._unreachable(exc)) from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise OpencodeError(f"opencode sent something that is not JSON for {method} {path}") from exc

    def _unreachable(self, exc: Exception) -> str:
        reason = getattr(exc, "reason", exc)
        return f"Cannot reach opencode at {self._base_url}: {reason}"


def _close_pipe(proc: subprocess.Popen) -> None:
    # The drain thread ends on EOF; closing our end releases the handle even
    # when a grandchild (node under opencode.cmd) still holds the pipe.
    try:
        proc.stdout.close()
    except (AttributeError, OSError, ValueError):
        pass


def _shutdown(response) -> None:
    """Ends a blocked read on an HTTP response from another thread."""
    try:
        sock = response.fp.raw._sock
        sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        try:
            response.close()
        except Exception:
            pass


class EventNormalizer:
    """Turns opencode's raw bus events into the agent event vocabulary for
    one session (docs/CODE_SECTION.md has the table):

        {"type": "busy"}  {"type": "idle"}
        {"type": "text", "id": part_id, "delta": str}
        {"type": "reasoning", "id": part_id, "delta": str}
        {"type": "tool", "id": part_id, "tool": str, "status": str,
         "title": str, "input": dict, "output": str, "error": str}
        {"type": "file_edited", "path": str}
        {"type": "permission", "id": str, "permission": str,
         "patterns": list[str], "title": str}
        {"type": "usage", "input": int, "output": int, "reasoning": int}
        {"type": "error", "message": str}

    Rules:
      * Events with a sessionID other than `session_id` are dropped (the id
        is in properties.sessionID, properties.part.sessionID or
        properties.info.sessionID / properties.info.id for session.*).
      * message.updated records each message's role; parts of a 'user'
        message are dropped (that is the echo of our own prompt).
      * text/reasoning: message.part.delta with field 'text' -> a delta
        event of the part's type. A delta for a part not yet seen is held
        until message.part.updated tells its type -- or emitted as 'text'
        when the part's message is known to be the assistant's and no
        type arrives. message.part.updated with a text longer than what was
        emitted for that part emits the missing suffix (servers that do
        not stream deltas still work); never re-emits text already sent.
      * tool: one event per (part id, status) the first time that status is
        seen; title from state.title (else the tool name), input from
        state.input, output from state.output, error from state.error
        ('' / {} when absent).
      * busy: session.status with status.type 'busy' or 'retry'; idle:
        session.idle or session.status 'idle'. Consecutive duplicates are
        collapsed (busy, busy -> one busy).
      * usage: message.part.updated of type 'step-finish' ->
        tokens.input / tokens.output / tokens.reasoning.
      * permission: 'permission.asked' (or 'permission.updated'); title is
        '<permission>: <patterns joined with ", ">'.
      * error: 'session.error' -> properties.error.data.message, else
        properties.error.name, else 'Unknown error'. A MessageAbortedError
        (the user pressed Stop) gives no error event.
      * file.edited -> file_edited with properties.file (no session filter).
      * Everything else gives no event.
    """

    def __init__(self, session_id: str):
        self.set_session(session_id)

    def set_session(self, session_id: str) -> None:
        """Switches to another session and forgets all per-part state."""
        self._session = session_id
        self._roles: dict[str, str] = {}          # message id -> role
        self._types: dict[str, str] = {}          # part id -> 'text' | 'reasoning' | ...
        self._part_message: dict[str, str] = {}   # part id -> message id
        self._sent: dict[str, str] = {}           # part id -> text emitted so far
        self._held: dict[str, list[str]] = {}     # part id -> deltas before its type is known
        self._tool_states: set[tuple[str, str]] = set()
        self._state = ""                          # last 'busy' / 'idle' emitted

    def feed(self, raw: dict) -> list[dict]:
        """The agent events for one raw event (often none)."""
        kind = raw.get("type") if isinstance(raw, dict) else None
        props = raw.get("properties") if isinstance(raw, dict) else None
        if not kind or not isinstance(props, dict):
            return []
        if kind == "file.edited":
            path = props.get("file")
            return [{"type": "file_edited", "path": path}] if path else []
        if self._session_of(props) != self._session:
            return []
        if kind == "message.updated":
            info = props.get("info") or {}
            if info.get("id"):
                self._roles[info["id"]] = info.get("role", "")
            return []
        if kind == "message.part.delta":
            return self._delta(props)
        if kind == "message.part.updated":
            return self._part(props.get("part") or {})
        if kind == "session.status":
            status = (props.get("status") or {}).get("type")
            if status in ("busy", "retry"):
                return self._switch("busy")
            if status == "idle":
                return self._switch("idle")
            return []
        if kind == "session.idle":
            return self._switch("idle")
        if kind in ("permission.asked", "permission.updated"):
            patterns = [str(p) for p in props.get("patterns") or []]
            permission = props.get("permission") or props.get("type") or "permission"
            return [{"type": "permission", "id": props.get("id", ""), "permission": permission,
                     "patterns": patterns,
                     "title": f"{permission}: {', '.join(patterns)}" if patterns else permission}]
        if kind == "session.error":
            error = props.get("error") or {}
            if error.get("name") == "MessageAbortedError":
                return []
            message = (error.get("data") or {}).get("message") or error.get("name") or "Unknown error"
            return [{"type": "error", "message": str(message)}]
        return []

    # ------------------------------------------------------------ private

    @staticmethod
    def _session_of(props: dict) -> Optional[str]:
        if props.get("sessionID"):
            return props["sessionID"]
        part = props.get("part")
        if isinstance(part, dict) and part.get("sessionID"):
            return part["sessionID"]
        info = props.get("info")
        if isinstance(info, dict):
            return info.get("sessionID") or info.get("id")
        return None

    def _switch(self, state: str) -> list[dict]:
        if state == self._state:
            return []
        self._state = state
        # A reply is over: text still held for want of a part type is the
        # assistant's answer (its message said role 'assistant').
        out = self._release_untyped() if state == "idle" else []
        return out + [{"type": state}]

    def _emit(self, part_id: str, kind: str, delta: str) -> list[dict]:
        if not delta:
            return []
        self._sent[part_id] = self._sent.get(part_id, "") + delta
        return [{"type": kind, "id": part_id, "delta": delta}]

    def _delta(self, props: dict) -> list[dict]:
        if props.get("field", "text") != "text":
            return []
        part_id, delta = props.get("partID") or "", props.get("delta") or ""
        message_id = props.get("messageID") or self._part_message.get(part_id, "")
        if not part_id or not delta or self._roles.get(message_id) == "user":
            return []
        if message_id:
            self._part_message[part_id] = message_id
        kind = self._types.get(part_id)
        if kind in ("text", "reasoning"):
            return self._emit(part_id, kind, delta)
        if kind is not None:
            return []                             # a tool part's field; not transcript text
        self._held.setdefault(part_id, []).append(delta)
        return []

    def _release_untyped(self) -> list[dict]:
        out: list[dict] = []
        for part_id in list(self._held):
            if self._roles.get(self._part_message.get(part_id, "")) == "assistant":
                out += self._emit(part_id, "text", "".join(self._held.pop(part_id)))
        return out

    def _part(self, part: dict) -> list[dict]:
        part_id, kind, message_id = part.get("id") or "", part.get("type") or "", part.get("messageID") or ""
        if message_id:
            self._part_message[part_id] = message_id
        if self._roles.get(message_id) == "user":
            self._held.pop(part_id, None)
            return []
        self._types[part_id] = kind
        if kind in ("text", "reasoning"):
            out = self._emit(part_id, kind, "".join(self._held.pop(part_id, [])))
            text, sent = part.get("text") or "", self._sent.get(part_id, "")
            if len(text) > len(sent) and text.startswith(sent):
                out += self._emit(part_id, kind, text[len(sent):])
            return out
        if kind == "tool":
            state = part.get("state") or {}
            status = state.get("status") or "pending"
            if (part_id, status) in self._tool_states:
                return []
            self._tool_states.add((part_id, status))
            tool = part.get("tool") or "tool"
            return [{"type": "tool", "id": part_id, "tool": tool, "status": status,
                     "title": str(state.get("title") or tool),
                     "input": state.get("input") if isinstance(state.get("input"), dict) else {},
                     "output": str(state.get("output") or ""),
                     "error": str(state.get("error") or "")}]
        if kind == "step-finish":
            tokens = part.get("tokens") or {}
            return [{"type": "usage", "input": int(tokens.get("input") or 0),
                     "output": int(tokens.get("output") or 0),
                     "reasoning": int(tokens.get("reasoning") or 0)}]
        return []


def read_sse_file(path: str) -> list[dict]:
    """The raw events of a recorded stream (the fixture format: 'data: {json}'
    lines separated by blank lines). For tests and replay."""
    events, data = [], []
    with open(path, encoding="utf-8") as stream:
        for line in list(stream) + [""]:
            line = line.rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line.strip() and data:
                try:
                    event = json.loads("\n".join(data))
                except ValueError:
                    event = None
                if isinstance(event, dict):
                    events.append(event)
                data = []
    return events
