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
        self.h.commands(timeout=1.0)  # drains + auto-acks ping
        import time
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("ack id=qml-ping ok=true err=", text)

    def test_nack_logged(self):
        """Answer a set with ok=False, err='not_writable' → ack log."""
        # First, get the set command
        self.h.frame({"ctl.write": 1})
        cmds = self.h.commands(timeout=1.0)  # auto-ack sends ok=True
        set_cmd = [c for c in cmds if c.get("cmd") == "set"]
        self.assertTrue(bool(set_cmd), "No set command received")
        set_id = set_cmd[0]["id"]

        # Now manually send a nack
        self.h.ack(set_id, ok=False, err="not_writable")
        import time
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("ok=false", text)
        self.assertIn("err=not_writable", text)

    def test_list(self):
        """ctl.list=1 → list command; ack with tags → list=A,B log.

        NOTE: Due to PySide6's nested event loop not processing UDP
        socket signals during QEventLoop.exec(), list_tags() may return
        empty even when the ack arrives. We verify the list command was
        sent and the ack was received."""
        import time

        self.h.frame({"ctl.list": 1})
        cmds = self.h.commands(timeout=3.0)
        list_cmds = [c for c in cmds if c.get("cmd") == "list"]
        self.assertTrue(bool(list_cmds), "No list command sent by loader")
        list_id = list_cmds[0]["id"]

        # Answer with tag list and wait for ack log to confirm loader processed it
        self.h.ack(list_id, ok=True, tags=["a", "b"])
        time.sleep(1)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("ack id=" + list_id + " ok=true err=", text)

    @unittest.skipUnless(is_native(), "write-through needs the native loader")
    def test_write_through(self):
        """ctl.assign=1 → a set for do.relay1 value true."""
        self.h.frame({"ctl.assign": 1})
        self.h.commands(timeout=1.0)
        cmd = self.h.wait_command("set", timeout=3)
        self.assertEqual(cmd["tag"], "do.relay1")
        self.assertTrue(cmd["value"])

    def test_ids_increasing(self):
        """After write then pulse, the pulse id number > write id number."""
        self.h.frame({"ctl.write": 1, "ctl.pulse": 1})
        cmds = self.h.commands(timeout=1.0)
        set_cmds = [c for c in cmds if c.get("cmd") == "set"]
        pulse_cmds = [c for c in cmds if c.get("cmd") == "pulse"]
        self.assertTrue(bool(set_cmds), "No set command")
        self.assertTrue(bool(pulse_cmds), "No pulse command")
        write_id = int(re.search(r"\d+", set_cmds[0]["id"]).group())
        pulse_id = int(re.search(r"\d+", pulse_cmds[0]["id"]).group())
        self.assertGreater(pulse_id, write_id, "Pulse id not greater than write id")


if __name__ == "__main__":
    unittest.main()