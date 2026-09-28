"""The offline TelemetrySimulator stands down while a local daemon answers.

It used to send every declared tag at a frozen value next to a real local
source (hmi-hwd --sim, daemon/tagsim.py); the tag engine took both streams in
turn and the preview's gauges flipped between 0 and the live value.
"""
import json
import os
import socket
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from tools.hmi_deployer.telemetry import TelemetrySimulator  # noqa: E402


def _udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.setblocking(False)
    return s


def _drain(sock):
    got = []
    while True:
        try:
            got.append(sock.recvfrom(65536))
        except (BlockingIOError, OSError):
            return got


class SimulatorYieldsToDaemon(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.engine = _udp()        # stands in for the TagEngine's rx port
        self.daemon = _udp()        # stands in for hmi-hwd / tagsim on :5000
        self.addCleanup(self.engine.close)
        self.addCleanup(self.daemon.close)
        self.sim = TelemetrySimulator(["ai.pot", "nav.tas"], udp_port=self.engine.getsockname()[1],
                                      daemon_addr=self.daemon.getsockname())
        self.addCleanup(self.sim.stop)

    def _answer_pings(self):
        for data, addr in _drain(self.daemon):
            msg = json.loads(data)
            if msg.get("cmd") == "ping":
                self.daemon.sendto(json.dumps({"t": "ack", "id": msg.get("id"), "ok": True}).encode(), addr)

    def _step(self, n, answer):
        for _ in range(n):
            self.sim._step()
            time.sleep(0.02)
            if answer:
                self._answer_pings()

    def test_sends_frames_when_no_daemon_answers(self):
        self._step(3, answer=False)
        self.assertGreaterEqual(len(_drain(self.engine)), 3)

    def test_quiet_while_a_daemon_answers(self):
        self._step(3, answer=True)       # first tick pings, the ack lands
        _drain(self.engine)
        self._step(5, answer=True)
        self.assertTrue(self.sim.daemon_present())
        self.assertEqual(_drain(self.engine), [])

    def test_resumes_after_the_daemon_goes(self):
        self._step(3, answer=True)
        _drain(self.engine)
        self.sim._daemon_seen -= self.sim.DAEMON_HOLD_S + 0.1   # the hold has lapsed
        self._step(2, answer=False)
        self.assertFalse(self.sim.daemon_present())
        self.assertGreaterEqual(len(_drain(self.engine)), 1)

    def test_no_probe_when_disabled(self):
        sim = TelemetrySimulator(["ai.pot"], udp_port=self.engine.getsockname()[1], daemon_addr=None)
        self.addCleanup(sim.stop)
        sim._step()
        time.sleep(0.02)
        self.assertEqual(_drain(self.daemon), [])
        self.assertEqual(len(_drain(self.engine)), 1)


if __name__ == "__main__":
    unittest.main()
