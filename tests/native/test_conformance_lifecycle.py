"""
tests/native/test_conformance_lifecycle.py
Black-box conformance test — lifecycle of the loader process.
"""
import os
import time
import unittest

from .loader_harness import LoaderHarness


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.harness = LoaderHarness(
            apps_dir=os.path.join(os.path.dirname(__file__), "fixtures", "probe-app"),
        )
        self.addCleanup(self.harness.stop)

    def test_ready_line(self):
        self.harness.start()
        line = self.harness.wait_for(r"PROBE ready", timeout=20)
        self.assertIn("App Log: PROBE ready ", line)
        self.assertIn("app=probe-app/1.0.0", line)
        self.assertIn("screen=640x480", line)
        self.assertIn("missing=fallback", line)
        self.assertIn("online=false", line)
        self.assertIn("rxErrors=0", line)

    def test_ready_file_appears(self):
        self.harness.start()
        self.harness.wait_for(r"PROBE ready", timeout=20)
        ready_path = self.harness._ready_file
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if os.path.exists(ready_path):
                break
            time.sleep(0.05)
        self.assertTrue(os.path.exists(ready_path), "Ready file did not appear within 2 s")

    def test_subscribe_cadence(self):
        self.harness.start()
        self.harness.wait_for(r"PROBE ready", timeout=20)

        # First command must be subscribe
        cmd = self.harness.wait_command("subscribe", timeout=5)
        self.assertEqual(cmd["cmd"], "subscribe")
        self.assertEqual(cmd["ttl"], 5)

        # A second subscribe should arrive within 3 s (cadence 2000 ms)
        cmds = self.harness.commands(timeout=3.0)
        has_subscribe = any(c.get("cmd") == "subscribe" for c in cmds)
        self.assertTrue(has_subscribe, "Second subscribe not received within 3 s")

    def test_theme_override(self):
        self.harness = LoaderHarness(
            apps_dir=os.path.join(os.path.dirname(__file__), "fixtures", "probe-app"),
            theme="dark",
        )
        self.addCleanup(self.harness.stop)
        self.harness.start()
        self.harness.wait_for(r"PROBE ready", timeout=20)
        line = self.harness.wait_for(r"PROBE theme=", timeout=5)
        self.assertIn("theme=dark", line)

    def test_exit_after(self):
        harness = LoaderHarness(
            apps_dir=os.path.join(os.path.dirname(__file__), "fixtures", "probe-app"),
            exit_after_ms=3000,
        )
        harness.start()
        harness.wait_for(r"PROBE ready", timeout=20)
        time.sleep(5)
        harness.stop()
        self.assertEqual(harness.exit_code, 0)


if __name__ == "__main__":
    unittest.main()