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
    raise NotImplementedError


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
        raise NotImplementedError

    def start(self, timeout: float = 30.0) -> str:
        """Starts the child and waits for the LISTENING_PREFIX line; returns
        the base URL (no trailing slash) and sets `url`. Raises OpencodeError
        -- INSTALL_HINT when there is no executable; the child's output tail
        when it exits or does not listen within `timeout` (the child is
        stopped then). Calling start on a running server returns its url."""
        raise NotImplementedError

    def stop(self) -> None:
        """Terminates the child (and on Windows its process tree, since
        opencode.cmd starts node which starts the server), waits up to 3 s,
        then kills. Idempotent; url becomes None."""
        raise NotImplementedError

    @property
    def running(self) -> bool:
        raise NotImplementedError

    @property
    def url(self) -> Optional[str]:
        raise NotImplementedError

    def output_tail(self) -> str:
        """The last lines the child printed, joined with newlines."""
        raise NotImplementedError


class OpencodeClient:
    """Blocking HTTP calls to one server for one project directory. Every
    request adds ?directory=<directory> (URL-encoded). Methods raise
    OpencodeError on connection errors, HTTP >= 400 and bad JSON."""

    def __init__(self, base_url: str, directory: str, timeout: float = 15.0):
        raise NotImplementedError

    @property
    def base_url(self) -> str:
        raise NotImplementedError

    @property
    def directory(self) -> str:
        raise NotImplementedError

    def providers(self) -> tuple[list[ModelRef], Optional[ModelRef]]:
        """Every model of every provider (providers in the order given,
        models sorted by id) and the default: the first provider in the
        `default` map that is also listed, else None."""
        raise NotImplementedError

    def create_session(self, title: str = "Studio") -> str:
        """Returns the new session id."""
        raise NotImplementedError

    def prompt(self, session_id: str, text: str, model: Optional[ModelRef] = None,
               system: Optional[str] = None) -> None:
        """POST prompt_async; returns as soon as the server accepted it."""
        raise NotImplementedError

    def abort(self, session_id: str) -> None:
        raise NotImplementedError

    def reply_permission(self, permission_id: str, reply: str) -> None:
        """reply is 'once', 'always' or 'reject' (ValueError otherwise)."""
        raise NotImplementedError

    def events(self, stop: Optional[threading.Event] = None) -> Iterator[dict]:
        """Opens GET /event and yields each event dict as it arrives. Returns
        when the stream ends or `stop` is set (checked at least once a second:
        use a socket timeout of <= 1 s and keep reading on timeout). SSE
        framing: lines starting 'data:' carry JSON (several data lines of one
        event are joined with '\\n'); a blank line ends an event; lines
        starting ':' are comments; malformed JSON is skipped."""
        raise NotImplementedError


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
        raise NotImplementedError

    def set_session(self, session_id: str) -> None:
        """Switches to another session and forgets all per-part state."""
        raise NotImplementedError

    def feed(self, raw: dict) -> list[dict]:
        """The agent events for one raw event (often none)."""
        raise NotImplementedError


def read_sse_file(path: str) -> list[dict]:
    """The raw events of a recorded stream (the fixture format: 'data: {json}'
    lines separated by blank lines). For tests and replay."""
    raise NotImplementedError
