"""designer/ide/opencode_client.py -- talk to an opencode server (no Qt here).

FROZEN CONTRACT (Code IDE swarm, 2026-09-23). Owner: W3. Public names,
signatures and docstrings are the contract; W3 fills in the bodies and may
add private helpers. Standard library only (urllib, subprocess, threading,
json) -- no requests, no Qt. See docs/CODE_SECTION.md, "opencode integration"
and "The agent event vocabulary".

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

import threading
from dataclasses import dataclass
from typing import Iterator, Optional, Sequence

# The line `opencode serve` prints once it listens, e.g.
# "opencode server listening on http://127.0.0.1:4096".
LISTENING_PREFIX = "opencode server listening on "
INSTALL_HINT = "opencode is not installed: run  npm i -g opencode-ai  and reopen the Code section"


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
    import os
    import shutil

    env_bin = os.environ.get("OPENCODE_BIN")
    if env_bin and os.path.isfile(env_bin):
        return env_bin

    which = shutil.which("opencode")
    if which:
        return which

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            path = os.path.join(appdata, "npm", "opencode.cmd")
            if os.path.isfile(path):
                return path

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
        self._proc = None
        self._url: Optional[str] = None
        self._output_lines: list[str] = []
        self._ready_event = threading.Event()
        self._lock = threading.Lock()

    def start(self, timeout: float = 30.0) -> str:
        """Starts the child and waits for the LISTENING_PREFIX line; returns
        the base URL (no trailing slash) and sets `url`. Raises OpencodeError
        -- INSTALL_HINT when there is no executable; the child's output tail
        when it exits or does not listen within `timeout` (the child is
        stopped then). Calling start on a running server returns its url."""
        if self._url is not None:
            return self._url

        if self._command is None:
            exe = find_opencode()
            if exe is None:
                raise OpencodeError(INSTALL_HINT)
            self._command = [exe]

        argv = list(self._command) + ["serve", "--hostname", "127.0.0.1", "--port", str(self._port)]

        try:
            import subprocess

            kwargs: dict = dict(
                argv=argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            if self._cwd:
                kwargs["cwd"] = self._cwd
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            self._proc = subprocess.Popen(**kwargs)
        except Exception as exc:
            raise OpencodeError(str(exc))

        self._ready_event.clear()
        self._thread = threading.Thread(target=self._drain_output, daemon=True)
        self._thread.start()

        started = self._ready_event.wait(timeout=timeout)
        if not started:
            self._stop_proc()
            self._proc = None
            tail = "\n".join(self._output_lines[-20:]) if self._output_lines else "timeout"
            raise OpencodeError(tail)

        if self._proc.poll() is not None:
            self._url = None
            tail = "\n".join(self._output_lines[-20:]) if self._output_lines else "child exited"
            raise OpencodeError(tail)

        return self._url

    def _drain_output(self) -> None:
        if self._proc is None or self._proc.stdout is None:
            return
        while True:
            line = self._proc.stdout.readline()
            if not line:
                break
            line = line.rstrip("\n\r")
            with self._lock:
                self._output_lines.append(line)
                if len(self._output_lines) > 50:
                    self._output_lines = self._output_lines[-50:]
            if LISTENING_PREFIX in line:
                url = line.split(LISTENING_PREFIX, 1)[-1].strip()
                with self._lock:
                    self._url = url
                self._ready_event.set()

    def stop(self) -> None:
        """Terminates the child (and on Windows its process tree, since
        opencode.cmd starts node which starts the server), waits up to 3 s,
        then kills. Idempotent; url becomes None."""
        self._stop_proc()
        with self._lock:
            self._url = None

    def _stop_proc(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if os.name == "nt" and proc.pid is not None:
            try:
                import subprocess
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True, timeout=3,
                )
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except Exception:
                pass
        self._proc = None

    @property
    def running(self) -> bool:
        return self._url is not None

    @property
    def url(self) -> Optional[str]:
        return self._url

    def output_tail(self) -> str:
        """The last lines the child printed, joined with newlines."""
        with self._lock:
            return "\n".join(self._output_lines)


class OpencodeClient:
    """Blocking HTTP calls to one server for one project directory. Every
    request adds ?directory=<directory> (URL-encoded). Methods raise
    OpencodeError on connection errors, HTTP >= 400 and bad JSON."""

    def __init__(self, base_url: str, directory: str, timeout: float = 15.0):
        self._base_url = base_url
        self._directory = directory
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def directory(self) -> str:
        return self._directory

    def _url(self, path: str) -> str:
        qs = urllib.parse.urlencode({"directory": self._directory})
        return f"{self._base_url}{path}?{qs}"

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> Optional[dict]:
        import json
        url = self._url(path)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            raw = resp.read()
            if raw:
                return json.loads(raw)
            return None
        except urllib.error.HTTPError as e:
            body_raw = ""
            try:
                body_raw = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            raise OpencodeError(f"{e.code}: {body_raw}")
        except urllib.error.URLError as e:
            raise OpencodeError(str(e.reason))

    def providers(self) -> tuple[list[ModelRef], Optional[ModelRef]]:
        """Every model of every provider (providers in the order given,
        models sorted by id) and the default: the first provider in the
        `default` map that is also listed, else None."""
        data = self._request("GET", "/config/providers")
        if not data:
            raise OpencodeError("empty response")
        providers_list: list[ModelRef] = []
        for prov in data.get("providers", []):
            pid = prov.get("id", "")
            for mid in sorted(prov.get("models", {}).keys()):
                providers_list.append(ModelRef(pid, mid))
        default_map = data.get("default", {})
        default = None
        for prov_id in default_map:
            if any(m.provider_id == prov_id for m in providers_list):
                default = ModelRef(prov_id, default_map[prov_id])
                break
        return (providers_list, default)

    def create_session(self, title: str = "Studio") -> str:
        """Returns the new session id."""
        data = self._request("POST", "/session", {"title": title})
        if not data or "id" not in data:
            raise OpencodeError("missing session id in response")
        return data["id"]

    def prompt(self, session_id: str, text: str, model: Optional[ModelRef] = None,
               system: Optional[str] = None) -> None:
        """POST prompt_async; returns as soon as the server accepted it."""
        parts = [{"type": "text", "text": text}]
        body: dict = {"parts": parts}
        if model is not None:
            body["model"] = {"providerID": model.provider_id, "modelID": model.model_id}
        if system is not None:
            body["system"] = system
        self._request("POST", f"/session/{session_id}/prompt_async", body)

    def abort(self, session_id: str) -> None:
        self._request("POST", f"/session/{session_id}/abort")

    def reply_permission(self, permission_id: str, reply: str) -> None:
        """reply is 'once', 'always' or 'reject' (ValueError otherwise)."""
        if reply not in ("once", "always", "reject"):
            raise ValueError(f"invalid reply: {reply!r}; must be 'once', 'always', or 'reject'")
        self._request("POST", f"/permission/{permission_id}/reply", {"reply": reply})

    def events(self, stop: Optional[threading.Event] = None) -> Iterator[dict]:
        """Opens GET /event and yields each event dict as it arrives. Returns
        when the stream ends or `stop` is set (checked at least once a second:
        use a socket timeout of <= 1 s and keep reading on timeout). SSE
        framing: lines starting 'data:' carry JSON (several data lines of one
        event are joined with '\\n'); a blank line ends an event; lines
        starting ':' are comments; malformed JSON is skipped."""
        import socket
        url = self._url("/event")
        req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
        resp = urllib.request.urlopen(req, timeout=1.0)
        buffer = ""
        while True:
            if stop and stop.is_set():
                return
            try:
                raw_line = resp.readline()
            except (socket.timeout, TimeoutError):
                continue
            if not raw_line:
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
            if line.startswith(":"):
                continue
            if line == "":
                if buffer.strip():
                    try:
                        event = json.loads(buffer.strip())
                        yield event
                    except ValueError:
                        pass
                    buffer = ""
                continue
            if line.startswith("data:"):
                buffer += line[5:]


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
        self._session_id = session_id
        self._message_roles: dict[str, str] = {}
        self._part_types: dict[str, str] = {}
        self._part_accumulated: dict[str, str] = {}
        self._part_emitted: dict[str, str] = {}
        self._buffered: dict[str, list[dict]] = {}
        self._tool_seen: set[tuple[str, str]] = set()
        self._last_state_type: Optional[str] = None

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._message_roles.clear()
        self._part_types.clear()
        self._part_accumulated.clear()
        self._part_emitted.clear()
        self._buffered.clear()
        self._tool_seen.clear()
        self._last_state_type = None

    def _same_session(self, props: dict) -> bool:
        sid = props.get("sessionID")
        if sid:
            return sid == self._session_id
        part = props.get("part")
        if isinstance(part, dict):
            return part.get("sessionID") == self._session_id
        info = props.get("info")
        if isinstance(info, dict):
            return info.get("sessionID") == self._session_id or info.get("id") == self._session_id
        return False

    def feed(self, raw: dict) -> list[dict]:
        etype = raw.get("type", "")
        props = raw.get("properties") or {}
        out: list[dict] = []

        if etype == "file.edited":
            fpath = props.get("file")
            if fpath:
                out.append({"type": "file_edited", "path": fpath})
            return out

        if etype == "permission.asked" or etype == "permission.updated":
            if not self._same_session(props):
                return out
            pid = props.get("id", "")
            perm = props.get("permission", "")
            patterns = props.get("patterns", [])
            title = f"{perm}: {', '.join(patterns)}"
            out.append({"type": "permission", "id": pid, "permission": perm,
                        "patterns": patterns, "title": title})
            return out

        if etype == "session.error":
            if not self._same_session(props):
                return out
            error_obj = props.get("error") or {}
            name = error_obj.get("name", "")
            if name == "MessageAbortedError":
                return out
            data = error_obj.get("data") or {}
            msg = data.get("message")
            if not msg:
                msg = name or "Unknown error"
            out.append({"type": "error", "message": msg})
            return out

        if etype == "session.status":
            if not self._same_session(props):
                return out
            status = props.get("status") or {}
            stype = status.get("type", "")
            if stype in ("busy", "retry"):
                if self._last_state_type != "busy":
                    out.append({"type": "busy"})
                    self._last_state_type = "busy"
            elif stype == "idle":
                if self._last_state_type != "idle":
                    out.append({"type": "idle"})
                    self._last_state_type = "idle"
            return out

        if etype == "session.idle":
            if not self._same_session(props):
                return out
            if self._last_state_type != "idle":
                out.append({"type": "idle"})
                self._last_state_type = "idle"
            return out

        if etype == "message.updated":
            if not self._same_session(props):
                return out
            info = props.get("info") or {}
            mid = info.get("id", "")
            role = info.get("role", "")
            if mid:
                self._message_roles[mid] = role
            return out

        if etype == "message.part.delta":
            if not self._same_session(props):
                return out
            part_id = props.get("partID", "")
            if not part_id:
                return out
            field = props.get("field", "")
            delta = props.get("delta", "")
            if not delta:
                return out
            if field != "text":
                return out
            part_type = self._part_types.get(part_id)
            if part_type:
                old = self._part_emitted.get(part_id, "")
                if old:
                    if len(delta) <= len(old):
                        self._part_accumulated[part_id] = delta
                        return out
                    suffix = delta[len(old):]
                    if suffix:
                        self._part_accumulated[part_id] = delta
                        out.append({"type": part_type, "id": part_id, "delta": suffix})
                else:
                    self._part_accumulated[part_id] = delta
                    out.append({"type": part_type, "id": part_id, "delta": delta})
            else:
                self._buffered.setdefault(part_id, []).append(
                    {"type": "text", "id": part_id, "delta": delta})
            return out

        if etype == "message.part.updated":
            if not self._same_session(props):
                return out
            part = props.get("part")
            if not isinstance(part, dict):
                return out
            mid = part.get("messageID", "")
            if mid:
                role = part.get("_role_hint") or self._message_roles.get(mid, "")
                if role:
                    self._message_roles[mid] = role
            if self._message_roles.get(mid) == "user":
                return out
            part_id = part.get("id", "")
            part_type = part.get("type", "")
            full_text = part.get("text", "")

            if part_type in ("text", "reasoning"):
                self._part_types[part_id] = part_type
                self._part_accumulated[part_id] = full_text
                if full_text:
                    old = self._part_emitted.get(part_id, "")
                    self._part_emitted[part_id] = full_text
                    if old and len(full_text) <= len(old):
                        pass
                    elif old:
                        suffix = full_text[len(old):]
                        if suffix:
                            out.append({"type": part_type, "id": part_id, "delta": suffix})
                    else:
                        out.append({"type": part_type, "id": part_id, "delta": full_text})
                if part_id in self._buffered:
                    buf = self._buffered.pop(part_id)
                    for b in buf:
                        b["type"] = part_type
                        out.append(dict(b))
                return out

            if part_type == "step-finish":
                tokens = (part.get("state") or {}).get("tokens", {})
                if not tokens:
                    tokens = part.get("tokens", {})
                inp = tokens.get("input", 0) or 0
                outp = tokens.get("output", 0) or 0
                rsn = tokens.get("reasoning", 0) or 0
                if inp or outp or rsn:
                    out.append({"type": "usage", "input": inp, "output": outp, "reasoning": rsn})
                return out

            if part_type == "tool":
                state = part.get("state", {}) or {}
                status = state.get("status", "")
                if status and (part_id, status) not in self._tool_seen:
                    self._tool_seen.add((part_id, status))
                    tool_name = part.get("tool", "")
                    title = state.get("title") or tool_name
                    inp = state.get("input", {})
                    output = state.get("output", "")
                    error = state.get("error", "")
                    if inp is None:
                        inp = {}
                    if output is None:
                        output = ""
                    if error is None:
                        error = ""
                    out.append({"type": "tool", "id": part_id, "tool": tool_name,
                                "status": status, "title": str(title),
                                "input": inp, "output": str(output), "error": str(error)})
                return out

            return out

        return out


def read_sse_file(path: str) -> list[dict]:
    result: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("data:"):
                import json
                try:
                    result.append(json.loads(line[5:]))
                except ValueError:
                    pass
    return result
