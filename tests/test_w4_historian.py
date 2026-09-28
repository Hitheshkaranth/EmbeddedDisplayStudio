"""Wave 1 gate for W4 (FROZEN): CONTRACT 13.4 -- the historian, the daemon's
history command and quality map, and the Studio's CSV export command."""
import io
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "daemon"))

import historian  # noqa: E402
from historian import Historian, HistoryConfigError  # noqa: E402
from tools.hmi_deployer.history_export import remote_command  # noqa: E402


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Config(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "h.db")

    def test_bad_configs(self):
        for cfg in ({}, {"path": 5},
                    {"path": self.db, "retention_days": 0},
                    {"path": self.db, "retention_days": 366},
                    {"path": self.db, "tags": {"a.b": {"period_ms": 50}}},
                    {"path": self.db, "tags": {"a.b": {"period_ms": 4_000_000}}},
                    {"path": self.db, "tags": {"a.b": {"deadband": -1}}},
                    {"path": self.db, "tags": {"a.b": {"colour": 1}}},
                    {"path": self.db, "tags": []},
                    {"path": self.db, "bogus": 1}):
            with self.subTest(cfg=cfg), self.assertRaises(HistoryConfigError):
                Historian(cfg)

    def test_from_config(self):
        self.assertIsNone(historian.from_config(None))
        h = historian.from_config({"path": self.db, "tags": {"a.b": {}}})
        self.assertIsInstance(h, Historian)
        h.close()


class Logging(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "h.db")
        self.clock = Clock()
        self.h = Historian({"path": self.db, "retention_days": 1,
                            "tags": {"a.b": {"period_ms": 1000, "deadband": 0.5}}}, clock=self.clock)
        self.addCleanup(self.h.close)

    def test_logs(self):
        self.assertTrue(self.h.logs("a.b"))
        self.assertFalse(self.h.logs("c.d"))

    def test_observe_rules(self):
        self.assertTrue(self.h.observe("a.b", 10.0, now=1000.0))     # first value
        self.assertFalse(self.h.observe("a.b", 20.0, now=1000.5))    # inside the period
        self.assertFalse(self.h.observe("a.b", 10.4, now=1001.5))    # inside the deadband
        self.assertTrue(self.h.observe("a.b", 10.6, now=1002.0))     # moved enough
        self.assertTrue(self.h.observe("a.b", 10.6, now=1062.5))     # 60 periods passed
        self.assertFalse(self.h.observe("a.b", True, now=1100.0))    # bools are not numbers
        self.assertFalse(self.h.observe("a.b", float("nan"), now=1200.0))
        self.assertFalse(self.h.observe("a.b", None, now=1300.0))
        self.assertFalse(self.h.observe("c.d", 5.0, now=1300.0))     # not logged

    def test_star(self):
        h = Historian({"path": os.path.join(self.dir.name, "s.db"), "tags": {"*": {"period_ms": 100}}},
                      clock=self.clock)
        self.addCleanup(h.close)
        self.assertTrue(h.logs("anything.at_all"))
        self.assertTrue(h.observe("x.y", 1, now=1000.0))

    def test_query_buckets_and_buffering(self):
        for i in range(10):
            self.assertTrue(self.h.observe("a.b", float(i), now=1000.5 + i))
        got = self.h.query("a.b", seconds=10, points=5, now=1010.0)   # before any commit
        self.assertEqual([v for _, v in got], [1.0, 3.0, 5.0, 7.0, 9.0])
        self.assertEqual(got[0][0], 1001500)                            # epoch ms, int
        self.assertIsInstance(got[0][0], int)
        all_ = self.h.query("a.b", seconds=10, points=200, now=1010.0)
        self.assertEqual(len(all_), 10)
        self.assertEqual([t for t, _ in all_], sorted(t for t, _ in all_))
        self.assertEqual(self.h.query("a.b", seconds=3, points=200, now=1010.0),
                         [[1007500, 7.0], [1008500, 8.0], [1009500, 9.0]])
        for bad in ((0, 5), (604801, 5), (10, 0), (10, 201)):
            with self.assertRaises(ValueError):
                self.h.query("a.b", seconds=bad[0], points=bad[1], now=1010.0)

    def test_commit_schedule_and_persistence(self):
        self.h.observe("a.b", 1.0, now=1000.0)
        self.assertEqual(self.h.maybe_commit(now=1003.0), 0)
        self.assertEqual(self.h.maybe_commit(now=1005.5), 1)
        self.h.observe("a.b", 5.0, now=1010.0)
        self.h.close()
        again = Historian({"path": self.db, "tags": {"a.b": {}}}, clock=self.clock)
        self.addCleanup(again.close)
        self.assertEqual(again.query("a.b", seconds=100, points=200, now=1020.0),
                         [[1000000, 1.0], [1010000, 5.0]])            # close() flushed

    def test_prune(self):
        self.h.observe("a.b", 1.0, now=1000.0)
        self.h.flush()
        later = 1000.0 + 2 * 86400
        self.h.observe("a.b", 2.0, now=later)
        self.h.flush()
        self.assertEqual(self.h.prune(now=later), 1)
        self.assertEqual(self.h.query("a.b", seconds=604800, points=200, now=later), [[int(later * 1000), 2.0]])

    def test_export_csv(self):
        self.h.observe("a.b", 1.25, now=1000.0)
        self.h.observe("a.b", 2.5, now=1002.0)
        self.h.flush()
        out = io.StringIO()
        rows = historian.export_csv(self.db, "a.b", None, out, now=1010.0)
        self.assertEqual(rows, 2)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(lines[0], "timestamp_iso,epoch_ms,tag,value")
        self.assertEqual(lines[1], "1970-01-01T00:16:40.000Z,1000000,a.b,1.25")
        self.assertEqual(lines[2], "1970-01-01T00:16:42.000Z,1002000,a.b,2.5")
        out = io.StringIO()
        self.assertEqual(historian.export_csv(self.db, "a.b", 9.0, out, now=1010.0), 1)

    def test_cli(self):
        self.h.observe("a.b", 7.0, now=time.time())
        self.h.flush()
        run = subprocess.run([sys.executable, str(REPO_ROOT / "daemon" / "historian.py"), "export",
                              "--db", self.db, "--tag", "a.b"], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn(",a.b,7", run.stdout)


class ExportCommand(unittest.TestCase):
    def test_remote_command(self):
        self.assertEqual(remote_command("eng.egt", 3600),
                         "/opt/hmi-python/bin/python3 /usr/lib/hmi/historian.py export "
                         "--db /var/lib/hmi/history.db --tag eng.egt --since 3600")
        self.assertEqual(remote_command("eng.egt", None, db="/tmp/x y.db"),
                         "/opt/hmi-python/bin/python3 /usr/lib/hmi/historian.py export "
                         "--db '/tmp/x y.db' --tag eng.egt")
        self.assertIn("'a;b'", remote_command("a;b", 1.5))


class DaemonHistory(unittest.TestCase):
    """hmi_hwd.py with a "history" block answers the history command and
    publishes the 13.4 "q" map for a failing read."""
    _port = 5150

    def start(self, history, fail_pot=False):
        DaemonHistory._port += 2
        self.cmd_port, self.tel_port = DaemonHistory._port, DaemonHistory._port + 1
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        cfg = {"daemon": {"cmd_port": self.cmd_port, "telemetry_sink": f"127.0.0.1:{self.tel_port}",
                          "poll_interval_ms": 50},
               "gpio": {"chip": "/dev/gpiochip3", "inputs": {"di.estop": {"offset": 4, "active_low": True}},
                        "outputs": {"do.relay1": {"offset": 5, "active_low": False, "initial": 0}}},
               "adc": {"device_name": "ads1015",
                       "channels": {"ai.pot": {"channel_file": "in_voltage0_raw", "scale_file": "in_voltage0_scale"}}}}
        if history is not None:
            history = dict(history, path=os.path.join(self.dir.name, "hist.db"))
            cfg["history"] = history
        path = os.path.join(self.dir.name, "hwd.json")
        Path(path).write_text(json.dumps(cfg), encoding="utf-8")
        runner = os.path.join(self.dir.name, "run.py")
        Path(runner).write_text(
            "import sys\nsys.path.insert(0, %r)\nimport daemon.hmi_hwd as hwd\n" % str(REPO_ROOT)
            + ("orig = hwd.IioSim.read\nhwd.IioSim.read = lambda s, t: None if t == 'ai.pot' else orig(s, t)\n"
               if fail_pot else "")
            + "hwd.main()\n", encoding="utf-8")
        self.proc = subprocess.Popen([sys.executable, runner, "--config", path, "--sim"], cwd=str(REPO_ROOT))
        self.addCleanup(self._stop)
        self.cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.cmd.settimeout(1.0)
        self.addCleanup(self.cmd.close)
        self.sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sink.bind(("127.0.0.1", self.tel_port))
        self.sink.settimeout(0.5)
        self.addCleanup(self.sink.close)
        for _ in range(30):
            try:
                if self.sink.recvfrom(8192)[0]:
                    return
            except socket.timeout:
                pass
        self.fail("daemon produced no telemetry")

    def _stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def ask(self, payload):
        self.cmd.sendto(json.dumps(payload).encode(), ("127.0.0.1", self.cmd_port))
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                data, _ = self.cmd.recvfrom(9000)
            except socket.timeout:
                continue
            msg = json.loads(data)
            if msg.get("t") == "ack" and msg.get("id") == payload.get("id"):
                return msg
        return None

    def test_history_command(self):
        self.start({"tags": {"ai.pot": {"period_ms": 100}}})
        time.sleep(1.5)
        ack = self.ask({"id": "h1", "cmd": "history", "tag": "ai.pot", "seconds": 60, "points": 5})
        self.assertIsNotNone(ack)
        self.assertTrue(ack["ok"], ack)
        self.assertEqual(ack["history"]["tag"], "ai.pot")
        samples = ack["history"]["samples"]
        self.assertTrue(1 <= len(samples) <= 5, samples)
        for ts, value in samples:
            self.assertIsInstance(ts, int)
            self.assertTrue(math.isfinite(value))
        self.assertEqual([s[0] for s in samples], sorted(s[0] for s in samples))
        self.assertEqual(self.ask({"id": "h2", "cmd": "history", "tag": "no.such"})["err"], "unknown_tag")
        self.assertEqual(self.ask({"id": "h3", "cmd": "history", "tag": "di.estop"})["err"], "no_history")
        self.assertEqual(self.ask({"id": "h4", "cmd": "history", "tag": "ai.pot", "seconds": 0})["err"], "bad_value")
        self.assertEqual(self.ask({"id": "h5", "cmd": "history", "tag": "ai.pot", "points": 500})["err"], "bad_value")

    def test_no_historian(self):
        self.start(None)
        ack = self.ask({"id": "n1", "cmd": "history", "tag": "ai.pot"})
        self.assertIsNotNone(ack)
        self.assertFalse(ack["ok"])
        self.assertEqual(ack["err"], "no_history")

    def test_quality_map(self):
        self.start(None, fail_pot=True)
        seen = None
        for _ in range(20):
            frame = json.loads(self.sink.recvfrom(8192)[0])
            if frame.get("t") == "tags":
                seen = frame
                if "q" in frame:
                    break
        self.assertIsNotNone(seen)
        self.assertIsNone(seen["tags"]["ai.pot"])          # still published as null
        self.assertEqual(seen.get("q"), {"ai.pot": "bad"})


if __name__ == "__main__":
    unittest.main()
