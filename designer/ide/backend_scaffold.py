"""designer/ide/backend_scaffold.py -- a working backend for the design's tags.

A Studio design invents tags ("ai.rpm", "do.pump") that no hardware
publishes yet. The Code section's "Generate backend..." writes a small,
runnable backend into the project folder that speaks the panel's wire
protocol (docs/CONTRACT.md section 2) for exactly those tags, with one stub
function per tag for the user -- or the coding agent -- to fill in:

    <project>/backend/
        backend.py   standalone, Python 3.8+ standard library only
        tags.json    the tag catalogue (see render_tags_json)
        tags.h       C constants for the tag names (see render_tags_header)
        README.md    how to run it and point the panel at it

backend.py (render_backend_py) -- the generated program:
  * `TAGS`: dict {tag: {"access": "R"|"W"|"RW"|"", "writable": bool}} in
    tag order (all index.tags()).
  * One function per tag, `read_<ident>()` for every tag, returning a
    placeholder: bool tags ("di."/"do." prefixes) False, "sys.uptime"
    seconds since start, everything else 0.0. `ident` = tag_ident(tag).
  * One function per writable tag, `write_<ident>(value)`, storing the value
    so the next read returns it (the placeholder "hardware"), returning True.
  * Wire protocol, CONTRACT 2:
      - listens for commands on --listen HOST:PORT (default 127.0.0.1:5010;
        5000 belongs to hmi-hwd), one JSON object per datagram, max 8192
        bytes (larger: dropped);
      - "set" {tag, value}: unknown tag -> ack err "unknown_tag"; tag not in
        the writable set -> "not_writable"; value not bool/int/float ->
        "bad_value"; else write_<ident>(value) -> ack ok;
      - "pulse" {tag, ms}: writable check as set, ms int 1..10000 else
        "bad_value"; writes True now and False after ms (a threading.Timer),
        ack ok;
      - "subscribe" {ttl?}: adds the sender to the subscribers for ttl
        seconds (default 5, capped at 60); "unsubscribe" removes it;
      - "list": ack ok with "tags": sorted tag names;
      - "ping": ack ok;
      - anything else: "unknown_cmd"; non-JSON "bad_json"; JSON that is not
        an object "not_an_object";
      - acks {"t":"ack","id":<id>,"ok":bool[,"err":code]} go to the sender,
        only when the command carried an "id" -- except ping and list, which
        are always answered (CONTRACT 2.3).
      - every --period seconds (default 0.1) a telemetry frame
        {"t":"tags","seq":n,"ts":time.time(),"src":"<project slug>-backend",
         "tags":{tag: read_<ident>() for every tag}} goes to the static sink
        --sink HOST:PORT (default 127.0.0.1:5001) and every live subscriber.
        seq starts at 0 and wraps at 2**31. A read_ function that raises
        publishes null for that tag (never omits it).
  * CLI: --listen, --sink, --period, --frames N (exit after N frames; 0 =
    run forever, the default). SIGINT/SIGTERM exit cleanly (exit code 0).
  * No third-party imports; nothing at import time but definitions (the
    program runs under `if __name__ == "__main__": main()`).

The generated functions are the user's to edit, so write_scaffold never
overwrites an existing file unless overwrite=True; files already there are
reported in "skipped".
"""
from __future__ import annotations

import json
import os
import re
import tempfile

from designer.ide.design_index import DesignIndex

BACKEND_DIR = "backend"
FILES = ("backend.py", "tags.json", "tags.h", "README.md")
DEFAULT_LISTEN = "127.0.0.1:5010"
DEFAULT_SINK = "127.0.0.1:5001"

_BACKEND = '''#!/usr/bin/env python3
"""Generated backend for the design's tags (EmbeddedDisplay Studio).

Speaks the panel wire protocol (docs/CONTRACT.md section 2) for exactly the
tags in TAGS, with one read_/write_ stub per tag for you to fill in.
"""
from __future__ import annotations

import argparse
import json
import signal
import socket
import sys
import threading
import time

PROJECT = {project}
TAGS = {tags}

IDENT = {ident}

# writable tags -> their ident.
WRITER = {writer}

LISTEN = {listen}
SINK = {sink}
PERIOD = {period}

_START = time.time()
_STORE = {t: False for t in TAGS}
_LOCK = threading.Lock()
_SUBSCRIBERS = {}
_SEQ = 0
_STOP = threading.Event()
_SOCK = None
_payload = b""


def _read(tag):
    """The placeholder hardware value for one tag (a generated read_)."""
    try:
        return globals()["read_" + IDENT[tag]]()
    except Exception:
        return None


def _frame():
    global _SEQ
    _SEQ = (_SEQ + 1) & ((1 << 31) - 1)
    payload = {"t": "tags", "seq": _SEQ, "ts": time.time(),
               "src": PROJECT + "-backend",
               "tags": {tag: _read(tag) for tag in TAGS}}
    return json.dumps(payload, separators=(",", ":")).encode()


def _publish():
    now = time.monotonic()
    live = [addr for addr, expiry in list(_SUBSCRIBERS.items()) if expiry > now]
    for addr in live:
        try:
            _SOCK.sendto(_payload, addr)
        except OSError:
            pass
    for addr in list(_SUBSCRIBERS):
        if _SUBSCRIBERS[addr] <= now:
            del _SUBSCRIBERS[addr]


def _ack(sock, addr, msg):
    sock.sendto(json.dumps(msg, separators=(",", ":")).encode(), addr)


def _ack_ok(sock, addr, ident=None, extra=None):
    msg = {"t": "ack", "ok": True}
    if ident is not None:
        msg["id"] = ident
    if extra:
        msg.update(extra)
    _ack(sock, addr, msg)


def _ack_err(sock, addr, ident, err):
    msg = {"t": "ack", "ok": False, "err": err}
    if ident is not None:
        msg["id"] = ident
    _ack(sock, addr, msg)


def _cmd(msg, sock, addr):
    if not isinstance(msg, dict):
        _ack_err(sock, addr, None, "not_an_object")
        return
    ident = msg.get("id")
    cmd = msg.get("cmd")
    if cmd == "ping":
        _ack_ok(sock, addr, ident)
    elif cmd == "list":
        _ack_ok(sock, addr, ident, extra={"tags": sorted(TAGS)})
    elif cmd == "set":
        _do_set(msg, sock, addr, ident)
    elif cmd == "pulse":
        _do_pulse(msg, sock, addr, ident)
    elif cmd == "subscribe":
        _do_subscribe(msg, sock, addr, ident)
    elif cmd == "unsubscribe":
        _SUBSCRIBERS.pop(addr, None)
        if ident is not None:
            _ack_ok(sock, addr, ident)
    else:
        _ack_err(sock, addr, ident, "unknown_cmd")


def _do_set(msg, sock, addr, ident):
    tag = msg.get("tag")
    if tag not in TAGS:
        _ack_err(sock, addr, ident, "unknown_tag")
        return
    if tag not in WRITER:
        _ack_err(sock, addr, ident, "not_writable")
        return
    value = msg.get("value")
    if isinstance(value, str) or value is None or not isinstance(value, (bool, int, float)):
        _ack_err(sock, addr, ident, "bad_value")
        return
    try:
        globals()["write_" + WRITER[tag]](value)
        if ident is not None:
            _ack_ok(sock, addr, ident)
    except Exception:
        _ack_err(sock, addr, ident, "hw_error")


def _do_pulse(msg, sock, addr, ident):
    tag = msg.get("tag")
    ms = msg.get("ms")
    if tag not in TAGS:
        _ack_err(sock, addr, ident, "unknown_tag")
        return
    if tag not in WRITER:
        _ack_err(sock, addr, ident, "not_writable")
        return
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        _ack_err(sock, addr, ident, "bad_value")
        return
    if ms < 1 or ms > 10000:
        _ack_err(sock, addr, ident, "bad_value")
        return

    def _release():
        globals()["write_" + WRITER[tag]](False)

    try:
        globals()["write_" + WRITER[tag]](True)
        threading.Timer(ms / 1000.0, _release).start()
        if ident is not None:
            _ack_ok(sock, addr, ident)
    except Exception:
        _ack_err(sock, addr, ident, "hw_error")


def _do_subscribe(msg, sock, addr, ident):
    ttl = msg.get("ttl")
    if ttl is None:
        ttl = 5.0
    try:
        ttl = float(ttl)
    except (TypeError, ValueError):
        ttl = 5.0
    _SUBSCRIBERS[addr] = time.monotonic() + min(max(ttl, 0.0), 60.0)
    if ident is not None:
        _ack_ok(sock, addr, ident)


def main(argv=None):
    global _SOCK, _payload
    parser = argparse.ArgumentParser(description="Generated " + PROJECT + " backend")
    parser.add_argument("--listen", default=LISTEN)
    parser.add_argument("--sink", default=SINK)
    parser.add_argument("--period", type=float, default=PERIOD)
    parser.add_argument("--frames", type=int, default=0)
    args = parser.parse_args(argv)

    _SOCK = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    _SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    host, port = args.listen.split(":")
    _SOCK.bind((host or "0.0.0.0", int(port)))
    _SOCK.settimeout(0.02)

    sink = args.sink.split(":")
    sink_addr = (sink[0] or "127.0.0.1", int(sink[1]))

    def _stop_signal(signum, frame):
        _STOP.set()

    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _stop_signal)
        except (ValueError, OSError):
            pass

    frames_sent = 0
    next_frame = time.monotonic()
    while not _STOP.is_set():
        while True:
            try:
                data, addr = _SOCK.recvfrom(8192)
            except (BlockingIOError, TimeoutError):
                break
            except OSError:
                break
            if len(data) > 8192:
                continue
            try:
                message = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            _cmd(message, _SOCK, addr)
        now = time.monotonic()
        if now >= next_frame:
            next_frame = now + args.period
            _payload = _frame()
            try:
                _SOCK.sendto(_payload, sink_addr)
            except OSError:
                pass
            _publish()
            frames_sent += 1
            if args.frames and frames_sent >= args.frames:
                break
    _SOCK.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- generated placeholder hardware (edit me) ------------------------------

'''


def tag_ident(tag: str) -> str:
    """A Python/C identifier for a tag: lowercase, every run of characters
    other than [a-z0-9] -> "_", stripped of leading/trailing "_"; a leading
    digit gets "t_" prepended. "ai.rpm" -> "ai_rpm", "mb.pump-1.sp" ->
    "mb_pump_1_sp"."""
    lowered = tag.lower()
    ident = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    if ident and ident[0].isdigit():
        ident = "t_" + ident
    return ident


def project_slug(index: DesignIndex) -> str:
    """Lowercase project name with runs of non [a-z0-9] -> "-", stripped;
    "hmi" when that leaves nothing (no project / unnamed)."""
    name = getattr(index.project, "name", "") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "hmi"


def render_backend_py(index: DesignIndex) -> str:
    """The backend.py text. See the module docstring."""
    slug = project_slug(index)
    tags = index.tags()
    tag_names = [t.tag for t in tags]
    ident_map = {t.tag: tag_ident(t.tag) for t in tags}
    writer = {t.tag: ident_map[t.tag] for t in tags if t.writable}
    body = _render_bodies(tags)
    result = (_BACKEND
              .replace("{project}", json.dumps(slug))
              .replace("{tags}", json.dumps(tag_names))
              .replace("{ident}", json.dumps(ident_map))
              .replace("{writer}", json.dumps(writer))
              .replace("{listen}", json.dumps(DEFAULT_LISTEN))
              .replace("{sink}", json.dumps(DEFAULT_SINK))
              .replace("{period}", json.dumps("0.1")))
    return result + body


def _render_read_func(tag: str) -> str:
    """The generated read_ body for one tag's placeholder hardware."""
    ident = tag_ident(tag)
    if tag == "sys.uptime":
        return ("def read_{ident}():\n"
                "    if '{tag}' in _STORE:\n"
                "        return _STORE['{tag}']\n"
                "    return time.time() - _START\n\n").format(ident=ident, tag=tag)
    if tag.startswith(("di.", "do.")):
        return ("def read_{ident}():\n"
                "    if '{tag}' in _STORE:\n"
                "        return _STORE['{tag}']\n"
                "    return False\n\n").format(ident=ident, tag=tag)
    return ("def read_{ident}():\n"
            "    if '{tag}' in _STORE:\n"
            "        return _STORE['{tag}']\n"
            "    return 0.0\n\n").format(ident=ident, tag=tag)


def _render_write_func(tag: str) -> str:
    ident = tag_ident(tag)
    return ("def write_{ident}(value):\n"
            "    with _LOCK:\n"
            "        _STORE['{tag}'] = value\n"
            "    return True\n\n"
            "def read_{ident}():\n"
            "    with _LOCK:\n"
            "        value = _STORE['{tag}']\n"
            "    return value\n\n").format(ident=ident, tag=tag)


def _render_bodies(tags):
    writable = {t.tag for t in tags if t.writable}
    out = []
    for entry in tags:
        if entry.tag in writable:
            out.append(_render_write_func(entry.tag))
        else:
            out.append(_render_read_func(entry.tag))
    return "".join(out)


def render_tags_json(index: DesignIndex) -> str:
    """JSON text, indent 2, trailing newline:
    {"project": <project name>, "tags": [{"tag", "access", "writable",
      "declared", "readers": [widget ids], "writers": [widget ids]}, ...]}
    in index.tags() order; readers/writers without repeats, design order."""
    project_name = getattr(index.project, "name", "") or ""
    entries = []
    for entry in index.tags():
        readers = []
        for wid, _prop in entry.readers:
            if wid and wid not in readers:
                readers.append(wid)
        writers = []
        for wid, _sig in entry.writers:
            if wid and wid not in writers:
                writers.append(wid)
        entries.append({
            "tag": entry.tag,
            "access": entry.access,
            "writable": entry.writable,
            "declared": entry.declared,
            "readers": readers,
            "writers": writers,
        })
    payload = {"project": project_name, "tags": entries}
    return json.dumps(payload, indent=2) + "\n"


def render_tags_header(index: DesignIndex) -> str:
    """C header text:
        /* Generated by EmbeddedDisplay Studio from <project name>. */
        #ifndef <SLUG>_TAGS_H           (slug upper-cased, "-" -> "_")
        #define <SLUG>_TAGS_H
        #define TAG_<IDENT> "<tag>"     (one per tag, IDENT upper-cased)
        #define TAG_COUNT <n>
        #endif
    with a trailing newline."""
    project_name = getattr(index.project, "name", "") or ""
    slug = project_slug(index).upper().replace("-", "_")
    lines = [f"/* Generated by EmbeddedDisplay Studio from {project_name}. */",
             f"#ifndef {slug}_TAGS_H",
             f"#define {slug}_TAGS_H"]
    for entry in index.tags():
        ident = tag_ident(entry.tag).upper()
        lines.append(f'#define TAG_{ident} {json.dumps(entry.tag)}')
    lines.append(f"#define TAG_COUNT {len(index.tags())}")
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def render_readme(index: DesignIndex) -> str:
    """Markdown: what the folder is, `python3 backend.py` usage with every
    CLI option, and how to point the panel's hmi-ui at it
    (HMI_UI_EXTRA_ARGS=--daemon-port 5010 in /etc/default/hmi-ui, as for
    tagsim), then a table of the tags (tag | access | used by)."""
    project_name = getattr(index.project, "name", "") or ""
    lines = [
        f"# Backend for {project_name}",
        "",
        "A standalone backend that publishes the design's tags over the panel's",
        "wire protocol (docs/CONTRACT.md section 2). Edit the `read_*`/`write_*`",
        "functions in `backend.py` to return real hardware values.",
        "",
        "## Run",
        "",
        "```",
        "python3 backend.py",
        "```",
        "",
        "Options:",
        "",
        "```",
        "--listen HOST:PORT   UDP port commands arrive on (default " + DEFAULT_LISTEN + ")",
        "--sink HOST:PORT     where telemetry frames go (default " + DEFAULT_SINK + ")",
        "--period SECONDS     frame cadence (default 0.1)",
        "--frames N           exit 0 after sending N frames (0 = forever)",
        "```",
        "",
        "Point the panel's hmi-ui at it (as for tagsim):",
        "",
        "```",
        "HMI_UI_EXTRA_ARGS=--daemon-port 5010",
        "# in /etc/default/hmi-ui",
        "```",
        "",
        "## Tags",
        "",
        "| Tag | Access | Used by |",
        "| --- | --- | --- |",
    ]
    for entry in index.tags():
        using = sorted({wid for wid, _ in entry.readers} | {wid for wid, _ in entry.writers})
        lines.append(f"| {entry.tag} | {entry.access or '-'} | {', '.join(using) or '-'} |")
    lines.append("")
    return "\n".join(lines)


def write_scaffold(root: str, index: DesignIndex, overwrite: bool = False) -> dict:
    """Writes FILES into <root>/BACKEND_DIR (created when missing).

    Returns {"written": [abs paths], "skipped": [abs paths]} in FILES order.
    An existing file is skipped unless overwrite. Each write is atomic
    (temp file in the same folder + os.replace), UTF-8, "\\n" newlines.
    root must be an existing directory (else ValueError); index with no
    tags still writes a backend that publishes an empty "tags" object."""
    if not os.path.isdir(root):
        raise ValueError(f"root is not a directory: {root!r}")
    backend = os.path.join(root, BACKEND_DIR)
    os.makedirs(backend, exist_ok=True)
    contents = {
        "backend.py": render_backend_py(index),
        "tags.json": render_tags_json(index),
        "tags.h": render_tags_header(index),
        "README.md": render_readme(index),
    }
    written = []
    skipped = []
    for name in FILES:
        dest = os.path.join(backend, name)
        if os.path.exists(dest) and not overwrite:
            skipped.append(os.path.abspath(dest))
            continue
        body = contents[name].encode("utf-8")
        fd, temp = tempfile.mkstemp(dir=backend)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
            os.replace(temp, dest)
        except BaseException:
            try:
                os.remove(temp)
            except OSError:
                pass
            raise
        written.append(os.path.abspath(dest))
    return {"written": written, "skipped": skipped}


__all__ = ["tag_ident", "project_slug", "render_backend_py", "render_tags_json", "render_tags_header",
           "render_readme", "write_scaffold", "BACKEND_DIR", "FILES", "DEFAULT_LISTEN", "DEFAULT_SINK"]

_ = (json, os, re, tempfile)