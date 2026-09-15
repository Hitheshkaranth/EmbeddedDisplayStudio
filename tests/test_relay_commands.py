"""
tests/test_relay_commands.py
Layer: Test (Layer 3, Studio)

The SSH telemetry relay is bidirectional: the preview's TagEngine sends
CONTRACT 2.2 commands to 127.0.0.1:5000 exactly as it would on the panel,
the relay takes them off that port and writes them to the remote script's
stdin, the script sends them to the panel's daemon from its own socket, and
the ack comes back up stdout with the telemetry. The `list` the relay sends
on start is routed to catalogueReceived rather than to the engine.

The remote script is run here for real, as a subprocess, against a stand-in
daemon -- the one thing string-matching its source could never prove is
that stdin still ends the process when ssh goes away.
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer import telemetry  # noqa: E402
from tools.hmi_deployer.ssh import SshWorker  # noqa: E402


def _pump(seconds=0.2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


def _port_free(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


class RemoteRelayScriptTests(unittest.TestCase):
    """Run the panel-side script against a fake daemon on the real port."""

    @classmethod
    def setUpClass(cls):
        if not _port_free(5000):
            raise unittest.SkipTest("UDP 5000 is held by another process; the remote script targets it")

    def setUp(self):
        self.daemon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.daemon.bind(("127.0.0.1", 5000))
        self.daemon.settimeout(3.0)
        self.addCleanup(self.daemon.close)
        self.proc = subprocess.Popen(
            [sys.executable, "-c", telemetry.build_remote_relay_script()],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        self.addCleanup(self._kill)

    def _kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(5)

    def test_commands_go_down_stdin_and_acks_come_up_stdout(self):
        data, relay_addr = self.daemon.recvfrom(8192)
        self.assertEqual(json.loads(data)["cmd"], "subscribe")
        # A command written to stdin reaches the daemon from the relay's own
        # socket, so the reply can simply go back to the sender.
        self.proc.stdin.write(json.dumps({"id": "c-1", "cmd": "ping"}) + "\n")
        self.proc.stdin.flush()
        data, addr = self.daemon.recvfrom(8192)
        self.assertEqual(json.loads(data), {"id": "c-1", "cmd": "ping"})
        self.assertEqual(addr, relay_addr)
        self.daemon.sendto(json.dumps({"t": "ack", "id": "c-1", "ok": True}).encode(), addr)
        line = self.proc.stdout.readline()
        self.assertEqual(json.loads(line), {"t": "ack", "id": "c-1", "ok": True})
        # Telemetry still flows while stdin is open and idle.
        self.daemon.sendto(json.dumps({"t": "tags", "seq": 1, "tags": {"ai.pot": 1.0}}).encode(), addr)
        self.assertEqual(json.loads(self.proc.stdout.readline())["t"], "tags")

    def test_closing_stdin_still_ends_the_script(self):
        self.daemon.recvfrom(8192)
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.fail("the relay outlived its ssh transport")
        self.assertEqual(self.proc.returncode, 0)


class SshWorkerInjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_inject_writes_a_line_the_child_reads(self):
        worker = SshWorker([sys.executable, "-c",
                            "import sys; print(sys.stdin.readline().strip().upper(), flush=True)"],
                           timeout_s=10)
        lines, finished = [], []
        worker.outputLine.connect(lines.append)
        worker.finished.connect(finished.append)
        self.assertFalse(worker.inject("early"), "no child yet")
        worker.start()
        deadline = time.monotonic() + 5
        while worker._proc is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(worker.inject("hello"))
        while not finished and time.monotonic() < deadline:
            _pump(0.05)
        worker.wait(5000)
        self.assertEqual(lines, ["HELLO"])
        self.assertEqual(finished, [0])


class _StubWorker:
    """Just enough of SshWorker for the relay to start, inject and stop."""
    def __init__(self):
        self.injected = []

    def inject(self, line):
        self.injected.append(line)
        return True

    def cancel(self): pass
    def isRunning(self): return False
    def wait(self, _ms=0): return True


class TelemetryRelayCommandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        telemetry._RETIRED_WORKERS.clear()
        # An engine-side listener standing in for the preview's TagEngine.
        self.engine = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.engine.bind(("127.0.0.1", 0))
        self.engine.settimeout(1.0)
        self.addCleanup(self.engine.close)
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        command_port = probe.getsockname()[1]
        probe.close()
        self.relay = telemetry.TelemetryRelay("192.0.2.1", "root", 22, "", None,
                                              udp_port=self.engine.getsockname()[1],
                                              command_port=command_port)
        self.relay.worker.cancel()
        self.stub = _StubWorker()
        self.relay.worker = self.stub
        self.relay._open_command_port()
        self.addCleanup(self.relay.stop)
        self.command_port = command_port

    def test_preview_commands_are_forwarded_up_the_channel(self):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        command = {"id": "gui-1", "cmd": "set", "tag": "do.relay1", "value": True}
        sender.sendto(json.dumps(command).encode(), ("127.0.0.1", self.command_port))
        _pump()
        self.assertEqual([json.loads(line) for line in self.stub.injected], [command])

    def test_catalogue_ack_is_routed_to_the_studio_not_the_engine(self):
        received = []
        self.relay.catalogueReceived.connect(received.append)
        self.relay.request_catalogue()
        self.assertEqual(json.loads(self.stub.injected[-1]),
                         {"id": telemetry.CATALOGUE_REQUEST_ID, "cmd": "list"})
        self.relay._on_line(json.dumps({"t": "ack", "id": telemetry.CATALOGUE_REQUEST_ID,
                                        "ok": True, "tags": ["ai.pot", "do.relay1", 7]}))
        self.assertEqual(received, [["ai.pot", "do.relay1"]])
        with self.assertRaises(socket.timeout):
            self.engine.recv(8192)
        # Every other line -- frames and the engine's own acks -- still
        # reaches the engine's port.
        ack = {"t": "ack", "id": "gui-1", "ok": True}
        self.relay._on_line(json.dumps(ack))
        self.assertEqual(json.loads(self.engine.recv(8192)), ack)

    def test_stop_releases_the_command_port(self):
        self.relay.stop()
        self.assertTrue(_port_free(self.command_port))


if __name__ == "__main__":
    unittest.main()
