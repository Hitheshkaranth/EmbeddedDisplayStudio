"""Extra tests for designer/ide/backend_scaffold.py: the robustness the module
docstring and CONTRACT 2 ask for that the frozen gate does not reach."""
import importlib.util
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from designer.ide import backend_scaffold  # noqa: E402
from designer.ide.backend_scaffold import (  # noqa: E402
    BACKEND_DIR, FILES, render_backend_py, render_tags_header, write_scaffold,
)
from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.model.project import DesignerBinding, DesignerPage, DesignerProject  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project, widget  # noqa: E402

EVIL_TAGS = [
    "ai.x'); import os; os.system('echo pwned') #",
    'ai.q"""\nraise SystemExit(3)\n"""',
    "ai.@@TAGS@@",
    "ai.a_b",
    "ai.a.b",
]


def fixture_index():
    return DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS)


def evil_index():
    widgets = [widget("ShNumDisplay", f"w{i}", bindings={"value": DesignerBinding(tag)})
               for i, tag in enumerate(EVIL_TAGS)]
    project = DesignerProject(name="Evil */ name\n#define X")
    project.pages = [DesignerPage("main", "Main", widgets)]
    return DesignIndex.build(project)


def load_backend(text):
    """Imports a generated backend.py as a module (definitions only)."""
    d = tempfile.mkdtemp()
    path = os.path.join(d, "backend_under_test.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    spec = importlib.util.spec_from_file_location("backend_under_test_%d" % id(text), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shutil.rmtree(d, True)
    return module


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((json.loads(data), addr))

    def close(self):
        pass


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class GeneratedModuleTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_backend(render_backend_py(fixture_index()))
        self.sock = FakeSocket()
        self.server = self.mod.Server(self.sock)

    def send(self, obj, addr=("127.0.0.1", 40000)):
        self.sock.sent.clear()
        self.server.handle(json.dumps(obj).encode(), addr)
        return self.sock.sent[-1][0] if self.sock.sent else None

    def test_ttl_capped_and_expired_pruned(self):
        self.assertTrue(self.send({"id": "s", "cmd": "subscribe", "ttl": 1000})["ok"])
        expiry = self.server.subscribers[("127.0.0.1", 40000)]
        self.assertLessEqual(expiry - time.monotonic(), 60.0)
        self.assertGreater(expiry - time.monotonic(), 59.0)
        self.send({"id": "s2", "cmd": "subscribe"}, addr=("127.0.0.1", 40001))
        self.assertAlmostEqual(self.server.subscribers[("127.0.0.1", 40001)] - time.monotonic(), 5.0, delta=0.5)
        self.send({"id": "s3", "cmd": "subscribe", "ttl": 0}, addr=("127.0.0.1", 40002))
        self.assertNotIn(("127.0.0.1", 40002), self.server.live_subscribers())
        self.assertNotIn(("127.0.0.1", 40002), self.server.subscribers, "expired subscriber pruned")
        self.assertEqual(self.send({"id": "s4", "cmd": "subscribe", "ttl": "x"})["err"], "bad_value")
        self.assertEqual(self.send({"id": "s5", "cmd": "subscribe", "ttl": True})["err"], "bad_value")

    def test_raising_read_publishes_null(self):
        def broken():
            raise RuntimeError("sensor gone")
        self.mod.READERS["ai.rpm"] = broken
        self.mod.READERS["ai.fuel"] = lambda: object()  # not JSON: null too
        self.server.publish(("127.0.0.1", 5001))
        frame = self.sock.sent[0][0]
        self.assertIn("ai.rpm", frame["tags"])
        self.assertIsNone(frame["tags"]["ai.rpm"])
        self.assertIsNone(frame["tags"]["ai.fuel"])
        self.assertEqual(frame["tags"]["ai.oiltemp"], 0.0)

    def test_seq_starts_at_zero_and_wraps(self):
        self.server.publish(("127.0.0.1", 5001))
        self.assertEqual(self.sock.sent[-1][0]["seq"], 0)
        self.server.seq = 2 ** 31 - 1
        self.server.publish(("127.0.0.1", 5001))
        self.server.publish(("127.0.0.1", 5001))
        self.assertEqual([m["seq"] for m, _ in self.sock.sent[-2:]], [2 ** 31 - 1, 0])

    def test_oversize_dropped_without_reply(self):
        self.sock.sent.clear()
        big = json.dumps({"id": "big", "cmd": "ping", "pad": "x" * 9000}).encode()
        self.server.handle(big, ("127.0.0.1", 40000))
        self.assertEqual(self.sock.sent, [])
        self.assertEqual(self.server.dropped, 1)

    def test_value_and_ms_validation(self):
        self.assertEqual(self.send({"id": 1, "cmd": "set", "tag": ["do.pump"], "value": 1})["err"], "unknown_tag")
        self.assertEqual(self.send({"id": 1, "cmd": "pulse", "tag": "zz.q", "ms": 5})["err"], "unknown_tag")
        self.assertEqual(self.send({"id": 1, "cmd": "pulse", "tag": "ai.rpm", "ms": 5})["err"], "not_writable")
        for value in (None, "1", [1], {"a": 1}):
            self.assertEqual(self.send({"id": 1, "cmd": "set", "tag": "do.pump", "value": value})["err"],
                             "bad_value", value)
        for ms in ("300", 3.5, True, 10001, -1):
            self.assertEqual(self.send({"id": 1, "cmd": "pulse", "tag": "do.horn", "ms": ms})["err"],
                             "bad_value", ms)
        self.server.handle(b'{"id":1,"cmd":"set","tag":"do.pump","value":NaN}', ("127.0.0.1", 40000))
        self.assertEqual(self.sock.sent[-1][0]["err"], "bad_value")
        self.server.handle(b"[" * 5000, ("127.0.0.1", 40000))  # nesting too deep for json
        self.assertEqual(self.sock.sent[-1][0]["err"], "bad_json")
        self.assertEqual(self.send({"id": 1, "cmd": "set", "tag": "do.pump", "value": 1}), {"t": "ack", "id": 1,
                                                                                            "ok": True})
        self.assertEqual(self.mod.READERS["do.pump"](), 1)

    def test_failing_write_is_hw_error(self):
        self.mod.WRITERS["do.pump"] = lambda value: False
        self.assertEqual(self.send({"id": 1, "cmd": "set", "tag": "do.pump", "value": 1})["err"], "hw_error")

    def test_sys_uptime_counts_seconds(self):
        project = make_project()
        project.pages[0].widgets.append(widget("ShNumDisplay", "up", bindings={"value": DesignerBinding("sys.uptime")}))
        mod = load_backend(render_backend_py(DesignIndex.build(project)))
        self.assertIsInstance(mod.read_sys_uptime(), float)
        self.assertGreaterEqual(mod.read_sys_uptime(), 0.0)


class SafeEmbeddingTests(unittest.TestCase):
    def test_tag_names_are_data(self):
        index = evil_index()
        text = render_backend_py(index)
        mod = load_backend(text)  # would exit/print if a tag were pasted as code
        self.assertEqual(sorted(mod.TAGS), sorted(EVIL_TAGS))
        self.assertEqual(sorted(mod.read_all()), sorted(EVIL_TAGS))
        self.assertEqual(mod.PROJECT, "Evil */ name\n#define X")
        # "ai.a_b" and "ai.a.b" share an identifier; neither may shadow the other.
        self.assertIsNot(mod.READERS["ai.a_b"], mod.READERS["ai.a.b"])

    def test_header_is_valid(self):
        text = render_tags_header(evil_index())
        lines = text.splitlines()
        self.assertEqual(lines[0].count("*/"), 1)
        self.assertTrue(lines[0].endswith("*/"))
        self.assertFalse(any(line.startswith("#define X") for line in lines))
        defines = [line for line in lines if line.startswith("#define TAG_") and "COUNT" not in line]
        self.assertEqual(len(defines), len(EVIL_TAGS))
        self.assertEqual(len({line.split()[1] for line in defines}), len(EVIL_TAGS), "unique macro names")
        for line in defines:
            self.assertIn(json.loads(line.split(" ", 2)[2]), EVIL_TAGS)


class WriteScaffoldErrorTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="scaffold-extra-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.folder = os.path.join(self.root, BACKEND_DIR)

    def test_no_temp_file_when_replace_fails(self):
        with mock.patch.object(backend_scaffold.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                write_scaffold(self.root, fixture_index())
        self.assertEqual(os.listdir(self.folder), [])

    def test_no_temp_file_when_write_fails(self):
        write_scaffold(self.root, fixture_index())
        real_open = open

        def failing_open(file, *args, **kwargs):
            if isinstance(file, int):
                os.close(file)
                raise OSError("no space")
            return real_open(file, *args, **kwargs)

        with mock.patch("builtins.open", failing_open):
            with self.assertRaises(OSError):
                write_scaffold(self.root, fixture_index(), overwrite=True)
        self.assertEqual(sorted(os.listdir(self.folder)), sorted(FILES))

    def test_render_error_writes_nothing(self):
        with mock.patch.object(backend_scaffold, "render_readme", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                write_scaffold(self.root, fixture_index())
        self.assertFalse(os.path.exists(self.folder) and os.listdir(self.folder))


class ProcessExtraTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="backend-extra-")
        self.addCleanup(shutil.rmtree, self.root, True)
        write_scaffold(self.root, fixture_index())
        self.script = os.path.join(self.root, BACKEND_DIR, "backend.py")
        self.port = free_port()
        self.sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink.bind(("127.0.0.1", 0))
        self.sink.settimeout(5)
        self.addCleanup(self.sink.close)
        self.client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.client.bind(("127.0.0.1", 0))
        self.client.settimeout(3)
        self.addCleanup(self.client.close)

    def start(self):
        proc = subprocess.Popen([sys.executable, self.script, "--listen", f"127.0.0.1:{self.port}",
                                 "--sink", f"127.0.0.1:{self.sink.getsockname()[1]}", "--period", "0.05"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        json.loads(self.sink.recvfrom(65536)[0])  # a fresh sink: this frame is from this process
        return proc

    def test_oversize_datagram_dropped_process_lives(self):
        self.start()
        self.client.sendto(json.dumps({"id": "big", "cmd": "ping", "pad": "x" * 9000}).encode(),
                           ("127.0.0.1", self.port))
        self.client.settimeout(0.5)
        with self.assertRaises(socket.timeout):
            self.client.recvfrom(65536)
        self.client.settimeout(3)
        self.client.sendto(b'{"cmd":"ping"}', ("127.0.0.1", self.port))
        self.assertEqual(json.loads(self.client.recvfrom(65536)[0]), {"t": "ack", "ok": True})

    def test_expired_subscriber_gets_no_frames(self):
        self.start()
        self.client.sendto(b'{"id":"s","cmd":"subscribe","ttl":0.3}', ("127.0.0.1", self.port))
        time.sleep(0.6)
        self.client.setblocking(False)
        try:
            while True:
                self.client.recvfrom(65536)
        except BlockingIOError:
            pass
        self.client.settimeout(0.4)
        with self.assertRaises(socket.timeout):
            self.client.recvfrom(65536)

    @unittest.skipIf(os.name == "nt", "SIGTERM is TerminateProcess on Windows")
    def test_sigterm_exits_zero(self):
        proc = self.start()
        proc.send_signal(signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=10), 0)


if __name__ == "__main__":
    unittest.main()
