"""
tests/native/test_conformance_commands.py
Black-box conformance test — commands sent by the loader through the probe.
"""
import os
import re
import unittest

from .loader_harness import LoaderHarness, is_native

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "probe-app")


class TestConformanceCommands(unittest.TestCase):
    def setUp(self):
        self.h = LoaderHarness(apps_dir=FIXTURES, exit_after_ms=15000)
        self.h.start()
        self.h.wait_for(r"PROBE ready", timeout=20)
        self.addCleanup(self.h.stop)

    def test_write_sends_set(self):
        """ctl.write=1 → daemon receives {cmd:set, tag:do.relay1, value:true}."""
        self.h.frame({"ctl.write": 1})
        self.h.commands(timeout=1.0)
        cmd = self.h.wait_command("set", timeout=3)
        self.assertEqual(cmd["cmd"], "set")
        self.assertEqual(cmd["tag"], "do.relay1")
        self.assertTrue(cmd["value"])
        self.assertRegex(cmd["id"], r"^gui-\d+$")

    def test_pulse_sends_pulse(self):
        """ctl.pulse=1 → {cmd:pulse, tag:do.relay1, ms:250} with an id."""
        self.h.frame({"ctl.pulse": 1})
        self.h.commands(timeout=1.0)
        cmd = self.h.wait_command("pulse", timeout=3)
        self.assertEqual(cmd["cmd"], "pulse")
        self.assertEqual(cmd["tag"], "do.relay1")
        self.assertEqual(cmd["ms"], 250)
        self.assertIn("id", cmd)

    def test_uart_tx(self):
        """ctl.uart=1 → {cmd:uart_tx, data:'hello\n'} with an id."""
        self.h.frame({"ctl.uart": 1})
        self.h.commands(timeout=1.0)
        cmd = self.h.wait_command("uart_tx", timeout=3)
        self.assertEqual(cmd["cmd"], "uart_tx")
        self.assertEqual(cmd["data"], "hello\n")
        self.assertIn("id", cmd)

    def test_ping_acked(self):
        """ctl.ping=1 → ping command; ack(id=qml-ping, ok=True) → ack log."""
        self.h.frame({"ctl.ping": 1})
        cmd = self.h.wait_command("ping", timeout=3)
        self.assertEqual(cmd["id"], "qml-ping")
        self.h.ack("qml-ping", ok=True)
        self.h.wait_for(r"PROBE ack id=qml-ping ok=true err=$", timeout=3)

    def test_nack_logged(self):
        """Answer a set with ok=False, err='not_writable' → ack log."""
        # First, get the set command
        self.h.frame({"ctl.write": 1})
        set_id = self.h.wait_command("set", timeout=3)["id"]
        self.h.ack(set_id, ok=False, err="not_writable")
        self.h.wait_for(r"PROBE ack id=" + re.escape(set_id) + r" ok=false err=not_writable$", timeout=3)

    def test_list(self):
        """ctl.list=1 -> list command; ack with tags -> the app sees them.

        list_tags() blocks in a nested event loop for up to 2 s, so the ack
        must be answered promptly; the result appears as `list=a,b`."""
        self.h.frame({"ctl.list": 1})
        list_id = self.h.wait_command("list", timeout=3)["id"]
        self.h.ack(list_id, ok=True, tags=["a", "b"])
        self.h.wait_for(r"PROBE list=a,b$", timeout=4)

    def test_write_through(self):
        """ctl.assign=1 (the app assigns Tags.do_relay1 = true).

        The native loader turns the assignment into a set command
        (QQmlPropertyMap::updateValue). The Python loader cannot -- the
        PLATFORM NOTE in gui/hmi_loader/tagengine.py explains why -- and the
        assignment is silently dropped. Both behaviours are pinned here so a
        change in either shows up, rather than skipping on one of them and
        tripping the no-skips rule the Linux suite runs under.
        """
        self.h.frame({"ctl.assign": 1})
        if is_native():
            cmd = self.h.wait_command("set", timeout=3)
            self.assertEqual(cmd["tag"], "do.relay1")
            self.assertTrue(cmd["value"])
        else:
            sets = [c for c in self.h.commands(timeout=1.5) if c.get("cmd") == "set"]
            self.assertEqual(sets, [], "the Python loader has no write-through; a set here means it grew one")

    def test_ids_increasing(self):
        """After write then pulse, the pulse id number > write id number."""
        # Two frames: the order in which one frame's tags are applied is not
        # part of the contract (a JSON object is unordered; Qt sorts keys).
        self.h.frame({"ctl.write": 1})
        set_cmd = self.h.wait_command("set", timeout=3)
        self.h.frame({"ctl.pulse": 1})
        pulse_cmd = self.h.wait_command("pulse", timeout=3)
        write_id = int(re.search(r"\d+", set_cmd["id"]).group())
        pulse_id = int(re.search(r"\d+", pulse_cmd["id"]).group())
        self.assertGreater(pulse_id, write_id, "Pulse id not greater than write id")


if __name__ == "__main__":
    unittest.main()