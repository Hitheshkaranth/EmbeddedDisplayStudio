"""
tests/native/test_conformance_alarms.py
Black-box conformance test — alarm evaluation through the probe.
"""
import os
import time
import unittest

from .loader_harness import LoaderHarness

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "probe-app")


class TestConformanceAlarms(unittest.TestCase):
    def setUp(self):
        self.h = LoaderHarness(apps_dir=FIXTURES, exit_after_ms=15000)
        self.h.start()
        self.h.wait_for(r"PROBE ready", timeout=20)
        self.addCleanup(self.h.stop)

    def test_alarm_activates_critical(self):
        """{ai.pot:3.2} -> alarms=1 top=critical:Pot 3.2V:false."""
        self.h.frame({"ai.pot": 3.2})
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("alarms=1 top=critical:Pot 3.2V:false", text)
        self.assertIn("alarmCount=1", text)

    def test_alarm_acknowledged(self):
        """{ai.pot:3.2, ctl.ack:1} -> top=critical:Pot 3.2V:true."""
        self.h.frame({"ai.pot": 3.2})
        self.h.wait_for(r"PROBE alarms=1 top=critical:Pot 3.2V:false$", timeout=3)
        # ai.pot stays in the frame: a frame without it would clear the alarm.
        self.h.frame({"ai.pot": 3.2, "ctl.ack": 1})
        self.h.wait_for(r"PROBE alarms=1 top=critical:Pot 3.2V:true$", timeout=3)

    def test_escalation_down_keeps_alarm(self):
        """An acknowledged critical that drops to warning keeps the ack."""
        self.h.frame({"ai.pot": 3.2})
        self.h.wait_for(r"PROBE alarmCount=1$", timeout=3)
        self.h.frame({"ai.pot": 3.2, "ctl.ack": 1})
        self.h.wait_for(r"PROBE alarms=1 top=critical:Pot 3.2V:true$", timeout=3)
        self.h.frame({"ai.pot": 2.7})
        self.h.wait_for(r"PROBE alarms=1 top=warning:Pot 2.7V:true$", timeout=3)
        counts = [l for l in self.h.probe_lines() if l.startswith("alarmCount=")]
        self.assertEqual(counts, ["alarmCount=1"])

    def test_alarm_clears(self):
        """{ai.pot:1.0} -> alarms=0 top=none and alarmCount=0."""
        self.h.frame({"ai.pot": 3.2})
        time.sleep(0.5)
        self.h.frame({"ai.pot": 1.0})
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("alarms=0 top=none", text)
        self.assertIn("alarmCount=0", text)

    def test_integer_value_in_message(self):
        """{ai.pot:3} -> message uses %g -> 'Pot 3V'."""
        self.h.frame({"ai.pot": 3})
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("Pot 3V", text)

    def test_history(self):
        """Frames 1.5, 3.2, 2.0 then ai.pot=2.0+ctl.hist=1 -> hist=1.5,3.2,2."""
        self.h.frame({"ai.pot": 1.5})
        time.sleep(0.2)
        self.h.frame({"ai.pot": 3.2})
        time.sleep(0.2)
        self.h.frame({"ai.pot": 2.0})
        time.sleep(0.2)
        self.h.frame({"ai.pot": 2.0, "ctl.hist": 1})
        self.h.commands(timeout=1.0)
        time.sleep(0.5)
        pl = self.h.probe_lines()
        hist_lines = [l for l in pl if l.startswith("hist=")]
        self.assertTrue(bool(hist_lines), "No hist= line found")
        self.assertEqual(hist_lines[0], "hist=1.5,3.2,2")


if __name__ == "__main__":
    unittest.main()