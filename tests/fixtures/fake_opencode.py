"""A stand-in for `opencode serve`, for tests (standard library only).

    python fake_opencode.py serve --hostname 127.0.0.1 --port 0

Prints the same "opencode server listening on http://..." line, then serves
the endpoints designer/ide/opencode_client.py uses. The event stream replays
tests/fixtures/opencode_events_edit.sse once per prompt, with its session id
rewritten to the prompted session, then keeps the connection open (a
heartbeat comment every 0.5 s). A prompt whose body contains __fail__ gets
HTTP 500. GET /_requests returns every request seen as
[{"method", "path", "query", "body"}] so tests can check what was sent.

Environment knobs:
    FAKE_OPENCODE_FAIL=1       exit(3) before listening, printing an error
    FAKE_OPENCODE_SILENT=1     never print the listening line (start timeout)
    FAKE_OPENCODE_MODEL=p/m    GET /config names this model (opencode's configured one)
    FAKE_OPENCODE_DROP_AFTER=N close each event stream after N events
                               (server.connected counts as the first)
"""
import json
import os
import queue
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RECORDED_SESSION = "ses_f328de678ffeFpsGDKP5pNthLH"

REQUESTS = []
SUBSCRIBERS = []
LOCK = threading.Lock()
SESSIONS = []


def recorded_events(session_id):
    events = []
    with open(os.path.join(HERE, "opencode_events_edit.sse"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("data:"):
                events.append(line[5:].strip().replace(RECORDED_SESSION, session_id))
    return events


def broadcast(lines):
    with LOCK:
        for q in SUBSCRIBERS:
            for line in lines:
                q.put(line)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _record(self, body):
        parsed = urllib.parse.urlparse(self.path)
        REQUESTS.append({"method": self.command, "path": parsed.path,
                         "query": dict(urllib.parse.parse_qsl(parsed.query)), "body": body})
        return parsed.path

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _empty(self, code=204):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self._record(None)
        if path == "/_requests":
            return self._json(200, REQUESTS[:-1])
        if path == "/config/providers":
            return self._json(200, {
                "providers": [
                    {"id": "local", "name": "Local", "models": {"zeta": {"name": "Zeta"}, "alpha": {"name": "Alpha"}}},
                    {"id": "cloud", "name": "Cloud", "models": {"big/model": {"name": "Big"}}},
                ],
                "default": {"ghost": "none", "cloud": "big/model", "local": "alpha"},
            })
        if path == "/config":
            model = os.environ.get("FAKE_OPENCODE_MODEL")
            return self._json(200, {"model": model} if model else {})
        if path == "/event":
            return self._stream()
        return self._json(404, {"name": "NotFound", "message": f"no route {path}"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        path = self._record(body)
        parts = path.strip("/").split("/")
        if path == "/session":
            sid = f"ses_fake{len(SESSIONS) + 1:04d}"
            SESSIONS.append(sid)
            return self._json(200, {"id": sid, "title": (body or {}).get("title", "")})
        if len(parts) == 3 and parts[0] == "session" and parts[2] == "prompt_async":
            if parts[1] not in SESSIONS:
                return self._json(404, {"name": "NotFoundError", "data": {"message": "Session not found"}})
            if "__fail__" in json.dumps(body):
                return self._json(500, {"name": "UnknownError", "data": {"message": "fake failure"}})
            events = recorded_events(parts[1])
            threading.Thread(target=lambda: (time.sleep(0.05), broadcast(events)), daemon=True).start()
            return self._empty(204)
        if len(parts) == 3 and parts[0] == "session" and parts[2] == "abort":
            broadcast([json.dumps({"type": "session.idle", "properties": {"sessionID": parts[1]}})])
            return self._json(200, True)
        if len(parts) == 3 and parts[0] == "permission" and parts[2] == "reply":
            return self._json(200, True)
        return self._json(404, {"name": "NotFound", "message": f"no route {path}"})

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        q = queue.Queue()
        with LOCK:
            SUBSCRIBERS.append(q)
        drop_after = int(os.environ.get("FAKE_OPENCODE_DROP_AFTER", "0") or 0)
        try:
            self.wfile.write(b'data: {"id":"evt_0","type":"server.connected","properties":{}}\n\n')
            self.wfile.flush()
            sent = 1
            while not (drop_after and sent >= drop_after):
                try:
                    line = q.get(timeout=0.5)
                    self.wfile.write(b"data: " + line.encode() + b"\n\n")
                    sent += 1
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            with LOCK:
                SUBSCRIBERS.remove(q)


def main(argv):
    port = 0
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    if os.environ.get("FAKE_OPENCODE_FAIL"):
        print("Error: fake opencode was told to fail", flush=True)
        sys.exit(3)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    print("Warning: OPENCODE_SERVER_PASSWORD is not set; server is unsecured.", flush=True)
    if not os.environ.get("FAKE_OPENCODE_SILENT"):
        print(f"opencode server listening on http://127.0.0.1:{server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
