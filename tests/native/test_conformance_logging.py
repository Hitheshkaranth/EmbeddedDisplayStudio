"""
tests/native/test_conformance_logging.py
Black-box conformance test — log format and log-level behavior.
"""
import os
import re
import unittest

from .loader_harness import LoaderHarness

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "probe-app")


class TestConformanceLogging(unittest.TestCase):
    def setUp(self):
        self.harness = LoaderHarness(
            apps_dir=FIXTURES,
        )
        self.addCleanup(self.harness.stop)

    def test_hmi_log_format(self):
        """Hmi.log lines match '^INFO - hmi-gui - App Log: PROBE '."""
        self.harness.start()
        self.harness.wait_for(r"PROBE ready", timeout=20)
        lines = self.harness.lines()
        # The ready line is an Hmi.log call
        ready_line = [l for l in lines if "PROBE ready" in l]
        self.assertTrue(bool(ready_line), "No PROBE ready line")
        pattern = re.compile(r"^INFO - hmi-gui - App Log: PROBE ")
        self.assertRegex(ready_line[0], pattern,
                         f"Line does not match expected log format: {ready_line[0]}")

    def test_log_level_error(self):
        """--log-level ERROR -> no line starts with 'INFO - hmi-gui'."""
        harness = LoaderHarness(apps_dir=FIXTURES, log_level="ERROR")
        harness.start()
        try:
            harness.wait_for(r"PROBE ready", timeout=20)
        except Exception:
            pass  # Might time out if ready line filtered
        lines = harness.lines()
        info_lines = [l for l in lines if l.startswith("INFO - hmi-gui")]
        self.assertEqual(len(info_lines), 0,
                         f"INFO lines found with --log-level ERROR: {info_lines}")

    def test_log_level_warning_still_ready(self):
        """--log-level WARNING -> ready file still appears (logging doesn't change behaviour)."""
        harness = LoaderHarness(apps_dir=FIXTURES, log_level="WARNING", exit_after_ms=5000)
        harness.start()
        # With WARNING level, Hmi.log(INFO) is filtered so we can't wait for PROBE ready.
        # Just wait for the process to be alive and check the ready file appears.
        import time
        time.sleep(5)  # enough time for the loader to start and mark ready
        self.assertTrue(os.path.exists(harness._ready_file),
                        "Ready file missing with --log-level WARNING")
        harness.stop()


if __name__ == "__main__":
    unittest.main()