"""
tests/hmi_ui/test_conformance_ui.py
Black-box conformance of the Qt-free runtime (native/hmi-ui) against the
CONTRACT section 2 wire protocol, driven exactly like the loaders' suite:
LoaderHarness spawns the binary with the standard flags and plays daemon.

The bundle is tests/hmi_ui/fixtures/probe-app: HmiProbe widgets that log every
bound value ("App Log: PROBE value=...") and turn ctl.* tag changes into
write / pulse / navigate actions.

    native/hmi-ui/build.sh && python -m unittest tests.hmi_ui.test_conformance_ui -v

Passes once tags.c (tag intake) and bind.c (bindings) are in place.
"""
import os
import shlex
import time
import unittest

from tests.native.loader_harness import LoaderHarness

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "probe-app")


def _ui_runtime():
    """The hmi-ui command under test: HMI_GUI_CMD when it names hmi-ui, else
    HMI_UI_BIN, else build.sh's output. None when there is no binary."""
    cmd = os.environ.get("HMI_GUI_CMD", "")
    if "hmi-ui" in cmd:
        return cmd
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.environ.get("HMI_UI_BIN") or os.path.join(root, "native", "hmi-ui", "out", "hmi-ui")
    return shlex.quote(path) if os.path.isfile(path) else None


UI_CMD = _ui_runtime()


@unittest.skipUnless(UI_CMD, "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class TestUiConformance(unittest.TestCase):
    def setUp(self):
        self.h = LoaderHarness(apps_dir=FIXTURE, exit_after_ms=15000, cmd=UI_CMD)
        self.h.start()
        self.h.wait_for(r"Marked ready", timeout=20)
        self.addCleanup(self.h.stop)

    def test_subscribe_cadence(self):
        """subscribe at start and every ~2 s, ttl 5, no id."""
        cmds = [c for c in self.h.commands(timeout=4.5) if c.get("cmd") == "subscribe"]
        self.assertGreaterEqual(len(cmds), 2)
        for c in cmds:
            self.assertEqual(c.get("ttl"), 5)
            self.assertNotIn("id", c)

    def test_tag_reaches_probe(self):
        self.h.frame({"ai.pot": 2.1, "di.estop": False})
        line = self.h.wait_for(r"PROBE value=", timeout=5)
        self.assertIn("App Log: PROBE value=2.1", line)
        line = self.h.wait_for(r"PROBE value=false", timeout=5)
        self.assertIn("false", line)

    def test_unchanged_value_is_not_redelivered(self):
        self.h.frame({"ai.pot": 1.5})
        self.h.wait_for(r"PROBE value=1.5", timeout=5)
        self.h.frame({"ai.pot": 1.5})
        with self.assertRaises(AssertionError):
            self.h.wait_for(r"PROBE value=1.5", timeout=1.5)

    def test_link_goes_online_then_lost(self):
        self.h.frame({"ai.pot": 0.5})
        self.h.wait_for(r"daemon link online", timeout=5)
        # No frames for > 2.5 s: watchdog declares the link lost.
        self.h.wait_for(r"daemon link lost", timeout=6)

    def test_write_action_sends_set(self):
        self.h.frame({"ctl.write": 1})
        cmd = self.h.wait_command("set", timeout=3)
        self.assertEqual(cmd["tag"], "do.relay1")
        self.assertTrue(cmd["value"])
        self.assertRegex(cmd["id"], r"^gui-\d+$")

    def test_pulse_action_sends_pulse(self):
        self.h.frame({"ctl.pulse": 1})
        cmd = self.h.wait_command("pulse", timeout=3)
        self.assertEqual(cmd["tag"], "do.relay1")
        self.assertEqual(cmd["ms"], 250)
        self.assertRegex(cmd["id"], r"^gui-\d+$")

    def test_command_ids_count_up(self):
        self.h.frame({"ctl.write": 1})
        self.h.wait_command("set", timeout=3)
        self.h.frame({"ctl.write": 2})
        deadline = time.monotonic() + 3
        sets = []
        while time.monotonic() < deadline and len(sets) < 2:
            sets = [c for c in self.h.commands(timeout=0.3) + [] if c.get("cmd") == "set"]
            sets = [c for c in self.h._received if c.get("cmd") == "set"]
        self.assertGreaterEqual(len(sets), 2, sets)
        self.assertEqual(int(sets[-1]["id"].split("-")[1]), int(sets[-2]["id"].split("-")[1]) + 1)

    def test_navigate_action_switches_page_and_scaled_binding(self):
        self.h.frame({"ctl.nav": 1})
        self.h.wait_for(r"navigate to page second", timeout=3)
        # The second page's probe binds ai.pot with *2 + 1 and format "%1 V".
        self.h.frame({"ai.pot": 2.0})
        # (the new page first logs its fallback, value=0; then the frame lands)
        line = self.h.wait_for(r'PROBE value="5 V"', timeout=5)
        self.assertIn('App Log: PROBE value="5 V"', line)

    def test_oversize_datagram_is_ignored(self):
        """> 8192 bytes: dropped; the next good frame still arrives."""
        self.h._daemon.sendto(b"{" + b" " * 9000 + b"}", ("127.0.0.1", self.h._rx_port))
        time.sleep(0.1)
        self.h.frame({"ai.pot": 3.3})
        self.h.wait_for(r"PROBE value=3.3", timeout=5)

    def test_unsubscribe_on_exit(self):
        """A runtime that exits (here: --exit-after) unsubscribes first."""
        self.h.stop()
        short = LoaderHarness(apps_dir=FIXTURE, exit_after_ms=2500, cmd=UI_CMD)
        short.start()
        self.addCleanup(short.stop)
        short.wait_for(r"Marked ready", timeout=20)
        cmds = [c.get("cmd") for c in short.commands(timeout=4.5)]
        self.assertIn("unsubscribe", cmds)


if __name__ == "__main__":
    unittest.main()
