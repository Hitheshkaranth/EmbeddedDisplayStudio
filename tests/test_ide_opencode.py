"""designer/ide/opencode_client.py and agent_backend.OpencodeBackend -- W3's gate.

FROZEN: the tests below are the minimum W3 must pass; add more in a class
below them, never change these. Nothing here needs opencode or a model: the
normalizer runs on a recorded stream (tests/fixtures/opencode_events_edit.sse)
and the client/backend run against tests/fixtures/fake_opencode.py.
"""
import json
import os
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide import opencode_client as oc  # noqa: E402
from designer.ide.agent_backend import ERROR, READY, OpencodeBackend, SYSTEM_PROMPT  # noqa: E402

FIXTURE = str(REPO_ROOT / "tests" / "fixtures" / "opencode_events_edit.sse")
FAKE = [sys.executable, str(REPO_ROOT / "tests" / "fixtures" / "fake_opencode.py")]
SESSION = "ses_f328de678ffeFpsGDKP5pNthLH"


def spin_until(predicate, ms):
    """Runs the event loop until predicate() or ms pass. Not QTest.qWait:
    in PySide6 6.11 it holds the GIL, so the backend's reader and worker
    threads barely run (a probe: 1 time slice a second against ~65 for a
    QEventLoop, which is what the Studio's app.exec does)."""
    deadline = time.monotonic() + ms / 1000
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return predicate()


def _normalized(session=SESSION):
    norm = oc.EventNormalizer(session)
    out = []
    for raw in oc.read_sse_file(FIXTURE):
        out += norm.feed(raw)
    return out


def _joined(events, kind):
    parts = {}
    for e in events:
        if e["type"] == kind:
            parts[e["id"]] = parts.get(e["id"], "") + e["delta"]
    return parts


class NormalizerTests(unittest.TestCase):
    def test_fixture_reads(self):
        raw = oc.read_sse_file(FIXTURE)
        self.assertGreater(len(raw), 200)
        self.assertEqual(raw[0]["type"], "server.connected")

    def test_busy_then_idle_once_each(self):
        events = _normalized()
        states = [e["type"] for e in events if e["type"] in ("busy", "idle")]
        self.assertEqual(states, ["busy", "idle"])
        self.assertEqual(events[-1], {"type": "idle"})

    def test_prompt_echo_dropped(self):
        text = "".join(_joined(_normalized(), "text").values())
        self.assertNotIn("Keep it short", text)

    def test_answer_text(self):
        texts = _joined(_normalized(), "text")
        self.assertEqual(len(texts), 1)
        answer = list(texts.values())[0]
        self.assertIn("Added `sub(a, b)` to `math.c`", answer)
        self.assertEqual(len(answer), 145)

    def test_reasoning(self):
        reasoning = _joined(_normalized(), "reasoning")
        self.assertEqual(len(reasoning), 4)
        self.assertEqual(list(reasoning.values())[0],
                         "The user wants me to add a subtraction function to math.c. Let me find the file first.\n")

    def test_tools_one_event_per_status(self):
        tools = [(e["tool"], e["status"]) for e in _normalized() if e["type"] == "tool"]
        self.assertEqual(tools, [("glob", "pending"), ("glob", "running"), ("glob", "completed"),
                                 ("read", "pending"), ("read", "running"), ("read", "completed"),
                                 ("edit", "pending"), ("edit", "running"), ("edit", "completed")])
        edit = [e for e in _normalized() if e["type"] == "tool" and e["tool"] == "edit"][-1]
        self.assertEqual(edit["input"]["filePath"], "C:\\proj\\math.c")
        self.assertEqual(edit["output"], "Edit applied successfully.")
        self.assertEqual(edit["error"], "")
        self.assertTrue(edit["title"])
        for key in ("id", "tool", "status", "title", "input", "output", "error"):
            self.assertIn(key, edit)

    def test_file_edited_and_usage(self):
        events = _normalized()
        self.assertEqual([e for e in events if e["type"] == "file_edited"],
                         [{"type": "file_edited", "path": "C:\\proj\\math.c"}])
        usage = [e for e in events if e["type"] == "usage"]
        self.assertEqual(len(usage), 4)
        self.assertEqual(usage[0], {"type": "usage", "input": 40400, "output": 52, "reasoning": 0})

    def test_other_session_filtered(self):
        events = _normalized("ses_someone_else")
        self.assertEqual([e["type"] for e in events], ["file_edited"])

    def test_part_updated_without_deltas_emits_text(self):
        norm = oc.EventNormalizer("ses_x")
        norm.feed({"type": "message.updated", "properties": {"info": {"id": "msg_a", "role": "assistant", "sessionID": "ses_x"}}})
        part = {"id": "prt_1", "messageID": "msg_a", "sessionID": "ses_x", "type": "text", "text": "Hello"}
        out = norm.feed({"type": "message.part.updated", "properties": {"part": part}})
        self.assertEqual(out, [{"type": "text", "id": "prt_1", "delta": "Hello"}])
        part = dict(part, text="Hello world")
        out = norm.feed({"type": "message.part.updated", "properties": {"part": part}})
        self.assertEqual(out, [{"type": "text", "id": "prt_1", "delta": " world"}])
        self.assertEqual(norm.feed({"type": "message.part.updated", "properties": {"part": part}}), [])

    def test_delta_before_part_type_is_held(self):
        norm = oc.EventNormalizer("ses_x")
        norm.feed({"type": "message.updated", "properties": {"info": {"id": "msg_a", "role": "assistant", "sessionID": "ses_x"}}})
        early = norm.feed({"type": "message.part.delta", "properties": {
            "sessionID": "ses_x", "messageID": "msg_a", "partID": "prt_r", "field": "text", "delta": "hmm"}})
        late = norm.feed({"type": "message.part.updated", "properties": {"part": {
            "id": "prt_r", "messageID": "msg_a", "sessionID": "ses_x", "type": "reasoning", "text": "hmm"}}})
        self.assertEqual(early + late, [{"type": "reasoning", "id": "prt_r", "delta": "hmm"}])

    def test_permission_and_error(self):
        norm = oc.EventNormalizer("ses_x")
        out = norm.feed({"type": "permission.asked", "properties": {
            "id": "per_1", "sessionID": "ses_x", "permission": "bash", "patterns": ["make", "make test"],
            "metadata": {}, "always": []}})
        self.assertEqual(out, [{"type": "permission", "id": "per_1", "permission": "bash",
                                "patterns": ["make", "make test"], "title": "bash: make, make test"}])
        out = norm.feed({"type": "session.error", "properties": {"sessionID": "ses_x", "error": {
            "name": "APIError", "data": {"message": "model not found"}}}})
        self.assertEqual(out, [{"type": "error", "message": "model not found"}])
        out = norm.feed({"type": "session.error", "properties": {"sessionID": "ses_x", "error": {
            "name": "MessageAbortedError", "data": {}}}})
        self.assertEqual(out, [])

    def test_set_session_resets(self):
        norm = oc.EventNormalizer("ses_x")
        norm.feed({"type": "session.status", "properties": {"sessionID": "ses_x", "status": {"type": "busy"}}})
        norm.set_session("ses_y")
        out = norm.feed({"type": "session.status", "properties": {"sessionID": "ses_y", "status": {"type": "busy"}}})
        self.assertEqual(out, [{"type": "busy"}])


class ModelRefTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(oc.ModelRef.parse("vllm/nvidia/Qwen3"), oc.ModelRef("vllm", "nvidia/Qwen3"))
        self.assertEqual(oc.ModelRef("a", "b").label, "a/b")
        for bad in ("", "x", "/m", "p/"):
            self.assertIsNone(oc.ModelRef.parse(bad))


class ServerAndClientTests(unittest.TestCase):
    """Against the fake server."""

    @classmethod
    def setUpClass(cls):
        cls.server = oc.OpencodeServer(command=FAKE, cwd=str(REPO_ROOT))
        cls.url = cls.server.start(timeout=15)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def _requests(self):
        with urllib.request.urlopen(self.url + "/_requests", timeout=5) as r:
            return json.loads(r.read())

    def test_started(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))
        self.assertTrue(self.server.running)
        self.assertEqual(self.server.url, self.url)
        self.assertIn("listening", self.server.output_tail())
        self.assertEqual(self.server.start(), self.url, "start on a running server returns its url")

    def test_providers(self):
        client = oc.OpencodeClient(self.url, "/tmp/proj dir")
        models, default = client.providers()
        self.assertEqual([m.label for m in models], ["local/alpha", "local/zeta", "cloud/big/model"])
        self.assertEqual(default, oc.ModelRef("cloud", "big/model"))
        last = self._requests()[-1]
        self.assertEqual((last["path"], last["query"]), ("/config/providers", {"directory": "/tmp/proj dir"}))

    def test_session_prompt_abort_permission(self):
        client = oc.OpencodeClient(self.url, "/p")
        sid = client.create_session("demo")
        self.assertTrue(sid.startswith("ses_"))
        client.prompt(sid, "hello", oc.ModelRef("local", "alpha"), system="be brief")
        client.abort(sid)
        client.reply_permission("per_9", "always")
        with self.assertRaises(ValueError):
            client.reply_permission("per_9", "sometimes")
        reqs = [r for r in self._requests() if r["method"] == "POST"][-4:]
        self.assertEqual(reqs[0]["body"], {"title": "demo"})
        self.assertEqual(reqs[1]["path"], f"/session/{sid}/prompt_async")
        self.assertEqual(reqs[1]["body"], {"parts": [{"type": "text", "text": "hello"}],
                                           "model": {"providerID": "local", "modelID": "alpha"},
                                           "system": "be brief"})
        self.assertEqual(reqs[2]["path"], f"/session/{sid}/abort")
        self.assertEqual((reqs[3]["path"], reqs[3]["body"]), ("/permission/per_9/reply", {"reply": "always"}))
        self.assertTrue(all(r["query"] == {"directory": "/p"} for r in reqs))

    def test_http_error_is_opencode_error(self):
        client = oc.OpencodeClient(self.url, "/p")
        with self.assertRaises(oc.OpencodeError) as caught:
            client.prompt("ses_missing", "x")
        self.assertIn("404", str(caught.exception))

    def test_events_stream_and_stop(self):
        client = oc.OpencodeClient(self.url, "/p")
        sid = client.create_session()
        stop = threading.Event()
        got = []

        def read():
            for e in client.events(stop):
                got.append(e)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        time.sleep(0.3)
        client.prompt(sid, "go")
        deadline = time.time() + 10
        while time.time() < deadline and not any(e.get("type") == "session.idle" for e in got):
            time.sleep(0.05)
        self.assertTrue(any(e.get("type") == "session.idle" for e in got))
        self.assertEqual(got[0]["type"], "server.connected")
        stop.set()
        reader.join(3)
        self.assertFalse(reader.is_alive(), "events() returns within ~1 s of stop being set")

    def test_connection_refused(self):
        client = oc.OpencodeClient("http://127.0.0.1:9", "/p", timeout=2)
        with self.assertRaises(oc.OpencodeError):
            client.providers()


class ServerFailureTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("FAKE_OPENCODE_FAIL", "FAKE_OPENCODE_SILENT")}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_child_exits(self):
        os.environ["FAKE_OPENCODE_FAIL"] = "1"
        server = oc.OpencodeServer(command=FAKE)
        with self.assertRaises(oc.OpencodeError) as caught:
            server.start(timeout=10)
        self.assertIn("told to fail", str(caught.exception))
        self.assertFalse(server.running)

    def test_never_listens(self):
        os.environ["FAKE_OPENCODE_SILENT"] = "1"
        server = oc.OpencodeServer(command=FAKE)
        started = time.time()
        with self.assertRaises(oc.OpencodeError):
            server.start(timeout=1.5)
        self.assertLess(time.time() - started, 6)
        self.assertFalse(server.running)
        server.stop()

    def test_missing_binary(self):
        saved = os.environ.get("OPENCODE_BIN"), os.environ.get("PATH")
        try:
            os.environ["OPENCODE_BIN"] = "/nonexistent/opencode"
            os.environ["PATH"] = "/nonexistent"
            if os.name != "nt":
                self.assertIsNone(oc.find_opencode())
                with self.assertRaises(oc.OpencodeError) as caught:
                    oc.OpencodeServer().start(timeout=2)
                self.assertEqual(str(caught.exception), oc.INSTALL_HINT)
        finally:
            for key, value in zip(("OPENCODE_BIN", "PATH"), saved):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class OpencodeBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.backend = OpencodeBackend(server_command=FAKE)
        self.addCleanup(self.backend.stop)
        self.events = []
        self.states = []
        self.models = []
        self.backend.event.connect(self.events.append)
        self.backend.stateChanged.connect(lambda s, d: self.states.append((s, d)))
        self.backend.modelsChanged.connect(self.models.append)

    def _wait(self, predicate, ms=10000):
        return spin_until(predicate, ms)

    def test_start_send_receive(self):
        self.backend.start(str(REPO_ROOT))
        self.assertTrue(self._wait(lambda: self.backend.state() == READY), self.states)
        self.assertTrue(self.backend.detail().startswith("http://127.0.0.1:"))
        self.assertEqual([m.label for m in self.models[-1]], ["local/alpha", "local/zeta", "cloud/big/model"])
        self.assertEqual(self.backend.default_model(), oc.ModelRef("cloud", "big/model"))
        self.backend.send("add sub", context={"path": "/x/math.c", "relative": "math.c", "cursor_line": 1,
                                              "start_line": 1, "end_line": 1, "text": "", "language": "c"})
        self.assertEqual(self.events[0], {"type": "busy"}, "busy is emitted at once, before any network reply")
        self.assertTrue(self._wait(lambda: any(e["type"] == "idle" for e in self.events)), self.events[-5:])
        kinds = {e["type"] for e in self.events}
        self.assertTrue({"busy", "reasoning", "tool", "text", "file_edited", "usage", "idle"} <= kinds, kinds)
        self.assertTrue(self.backend.session_id().startswith("ses_fake"))
        with urllib.request.urlopen(self.backend.detail() + "/_requests", timeout=5) as r:
            reqs = json.loads(r.read())
        prompt = [r for r in reqs if r["path"].endswith("/prompt_async")][-1]
        self.assertEqual(prompt["body"]["system"], SYSTEM_PROMPT)
        self.assertIn("add sub", prompt["body"]["parts"][0]["text"])
        self.assertIn("math.c", prompt["body"]["parts"][0]["text"])
        self.assertEqual(prompt["query"]["directory"], str(REPO_ROOT))
        self.assertEqual([e for e in self.events if e["type"] == "busy"], [{"type": "busy"}],
                         "the backend's own busy and the stream's busy collapse into one")

    def test_new_session(self):
        self.backend.start(str(REPO_ROOT))
        self.assertTrue(self._wait(lambda: self.backend.state() == READY))
        self.backend.send("one")
        self.assertTrue(self._wait(lambda: any(e["type"] == "idle" for e in self.events)))
        first = self.backend.session_id()
        self.backend.new_session()
        self.assertEqual(self.backend.session_id(), "")
        self.events.clear()
        self.backend.send("two")
        self.assertTrue(self._wait(lambda: any(e["type"] == "idle" for e in self.events)))
        self.assertNotEqual(self.backend.session_id(), first)

    def test_start_failure_is_error_state(self):
        os.environ["FAKE_OPENCODE_FAIL"] = "1"
        try:
            self.backend.start(str(REPO_ROOT))
            self.assertTrue(self._wait(lambda: self.backend.state() == ERROR), self.states)
        finally:
            os.environ.pop("FAKE_OPENCODE_FAIL", None)
        self.assertIn("told to fail", self.backend.detail())

    def test_send_error_becomes_error_then_idle(self):
        self.backend.start(str(REPO_ROOT))
        self.assertTrue(self._wait(lambda: self.backend.state() == READY))
        # The fake answers a prompt containing __fail__ with HTTP 500.
        self.backend.send("please __fail__", model=oc.ModelRef("local", "alpha"))
        self.assertTrue(self._wait(lambda: any(e["type"] == "idle" for e in self.events)))
        types = [e["type"] for e in self.events]
        self.assertEqual(types[0], "busy")
        self.assertIn("error", types)
        self.assertEqual(types[-1], "idle")
        error = [e for e in self.events if e["type"] == "error"][0]
        self.assertIn("500", error["message"])
        self.assertEqual(self.backend.state(), READY, "a failed prompt does not take the backend down")

    def test_stream_reconnects(self):
        os.environ["FAKE_OPENCODE_DROP_AFTER"] = "1"
        try:
            self.backend.start(str(REPO_ROOT))
            self.assertTrue(self._wait(lambda: self.backend.state() == READY))
            url = self.backend.detail()

            def subscriptions():
                with urllib.request.urlopen(url + "/_requests", timeout=5) as r:
                    return sum(1 for q in json.loads(r.read()) if q["path"] == "/event")

            # Each stream closes after its first event; the reader keeps
            # reconnecting (0.5 s, 1 s, 2 s ... back-off, capped at 5 s).
            self.backend.send("first")
            self.assertTrue(self._wait(lambda: subscriptions() >= 3, 12000))
        finally:
            os.environ.pop("FAKE_OPENCODE_DROP_AFTER", None)

    def test_stop_stops_the_server(self):
        self.backend.start(str(REPO_ROOT))
        self.assertTrue(self._wait(lambda: self.backend.state() == READY))
        url = self.backend.detail()
        self.backend.stop()
        self.assertEqual(self.backend.state(), "stopped")
        time.sleep(0.5)
        with self.assertRaises(Exception):
            urllib.request.urlopen(url + "/config/providers", timeout=2)


class OpencodeQcTests(unittest.TestCase):
    """Coordinator QC: what the frozen gate did not pin."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _sse_server(self, body: bytes):
        """A one-route server answering GET /event with `body`, then closing."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_sse_framing(self):
        body = (b": comment\n\n"
                b'data: {"type": "a",\ndata:  "n": 1}\n\n'      # one event over two data lines
                b"data: not json\n\n"
                b'data: {"type": "b"}\r\n\r\n')
        url = self._sse_server(body)
        events = list(oc.OpencodeClient(url, "/p").events())
        self.assertEqual(events, [{"type": "a", "n": 1}, {"type": "b"}])

    def test_early_exit_reported_fast(self):
        os.environ["FAKE_OPENCODE_FAIL"] = "1"
        try:
            started = time.monotonic()
            with self.assertRaises(oc.OpencodeError):
                oc.OpencodeServer(command=FAKE).start(timeout=20)
            self.assertLess(time.monotonic() - started, 5, "a dead child does not wait out the timeout")
        finally:
            os.environ.pop("FAKE_OPENCODE_FAIL", None)

    def test_stop_during_start_never_turns_ready(self):
        backend = OpencodeBackend(server_command=FAKE)
        self.addCleanup(backend.stop)
        states = []
        backend.stateChanged.connect(lambda s, d: states.append(s))
        backend.start(str(REPO_ROOT))
        backend.stop()
        spin_until(lambda: False, 2500)
        self.assertEqual(backend.state(), "stopped")
        self.assertNotIn(READY, states)

    def test_abort_without_session_is_idle(self):
        backend = OpencodeBackend(server_command=FAKE)
        self.addCleanup(backend.stop)
        events = []
        backend.event.connect(events.append)
        backend.start(str(REPO_ROOT))
        self.assertTrue(spin_until(lambda: backend.state() == READY, 10000))
        backend.abort()
        self.assertEqual(events, [{"type": "idle"}])

    def test_server_death_is_an_error_state(self):
        backend = OpencodeBackend(server_command=FAKE)
        self.addCleanup(backend.stop)
        backend.start(str(REPO_ROOT))
        self.assertTrue(spin_until(lambda: backend.state() == READY, 10000))
        backend._server._proc.kill()
        self.assertTrue(spin_until(lambda: backend.state() == ERROR, 15000), backend.detail())
        self.assertIn("stopped unexpectedly", backend.detail())

    def test_default_is_the_configured_model(self):
        # opencode's per-provider default map put an OpenRouter image model
        # first on the bench; the configured model must win when listed.
        for configured, expected in (("local/zeta", oc.ModelRef("local", "zeta")),
                                     ("nowhere/else", oc.ModelRef("cloud", "big/model"))):
            os.environ["FAKE_OPENCODE_MODEL"] = configured
            server = oc.OpencodeServer(command=FAKE)
            try:
                _models, default = oc.OpencodeClient(server.start(15), "/p").providers()
            finally:
                server.stop()
                os.environ.pop("FAKE_OPENCODE_MODEL", None)
            self.assertEqual(default, expected, configured)

    def test_normalizer_releases_untyped_text_at_idle(self):
        norm = oc.EventNormalizer("ses_x")
        norm.feed({"type": "message.updated", "properties": {"info": {"id": "m", "role": "assistant", "sessionID": "ses_x"}}})
        held = norm.feed({"type": "message.part.delta", "properties": {
            "sessionID": "ses_x", "messageID": "m", "partID": "p", "field": "text", "delta": "late"}})
        self.assertEqual(held, [])
        out = norm.feed({"type": "session.idle", "properties": {"sessionID": "ses_x"}})
        self.assertEqual(out, [{"type": "text", "id": "p", "delta": "late"}, {"type": "idle"}])


if __name__ == "__main__":
    unittest.main()
