"""
tests/test_readiness_ui.py

Source-level audit of the readiness UI in mainwindow.py.

Reads the actual source file and asserts:
  1. import audit_readiness exists
  2. _refresh_readiness exists as a method
  3. _refresh_readiness calls audit_readiness
  4. _refresh_readiness body contains no setEnabled
  5. setup_ui creates the summary then calls _refresh_readiness
"""
import os
import re
import unittest

# Resolve the path to mainwindow.py relative to this test file.
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_MAINWINDOW_PATH = os.path.join(
    _PROJECT_ROOT, "tools", "hmi_deployer", "mainwindow.py"
)


class TestReadinessUI(unittest.TestCase):
    """Source-level checks on mainwindow.py for the readiness UI."""

    @classmethod
    def setUpClass(cls):
        with open(_MAINWINDOW_PATH, "r", encoding="utf-8") as fh:
            cls.source = fh.read()

    # -- 1. import audit_readiness exists --

    def test_import_audit_readiness_exists(self):
        self.assertIn("from .readiness_core import audit_readiness", self.source)

    # -- 2. _refresh_readiness exists --

    def test_refresh_readiness_method_exists(self):
        """_refresh_readiness must be defined as a method on MainWindow."""
        self.assertRegex(
            self.source,
            r"def _refresh_readiness\s*\(",
        )

    # -- 3. _refresh_readiness calls audit_readiness --

    def test_refresh_readiness_calls_audit_readiness(self):
        """The body of _refresh_readiness must call audit_readiness."""
        # Extract the body of _refresh_readiness: from its def line to the
        # next def at the same indentation (or end of class).
        pattern = r"(    def _refresh_readiness.*?)(?=\n    def |\nclass |\Z)"
        match = re.search(pattern, self.source, re.DOTALL)
        self.assertIsNotNone(match, "_refresh_readiness not found in source")
        body = match.group(1)
        self.assertIn("audit_readiness(", body)

    # -- 4. _refresh_readiness body contains no setEnabled --

    def test_refresh_readiness_no_setEnabled(self):
        """_refresh_readiness must not call setEnabled on any widget."""
        pattern = r"(    def _refresh_readiness.*?)(?=\n    def |\nclass |\Z)"
        match = re.search(pattern, self.source, re.DOTALL)
        self.assertIsNotNone(match, "_refresh_readiness not found in source")
        body = match.group(1)
        self.assertNotIn(
            "setEnabled",
            body,
            "_refresh_readiness must not call setEnabled",
        )

    # -- 5. setup_ui creates the summary then calls _refresh_readiness --

    def test_setup_ui_creates_summary_then_calls_refresh(self):
        """setup_ui must add _readiness_summary to the layout, then call _refresh_readiness."""
        # Extract the setup_ui method body.
        pattern = r"(    def setup_ui\s*\(self\).*?)(?=\n    def |\nclass |\Z)"
        match = re.search(pattern, self.source, re.DOTALL)
        self.assertIsNotNone(match, "setup_ui not found in source")
        body = match.group(1)

        # Find the position of _readiness_summary being added to the layout.
        summary_add_match = re.search(
            r"readiness_body_layout\.addWidget\(self\._readiness_summary\)",
            body,
        )
        self.assertIsNotNone(
            summary_add_match,
            "_readiness_summary not added to readiness_body_layout in setup_ui",
        )

        # Find the position of _refresh_readiness call in setup_ui.
        refresh_call_match = re.search(
            r"self\._refresh_readiness\(\)",
            body,
        )
        self.assertIsNotNone(
            refresh_call_match,
            "_refresh_readiness() not called in setup_ui",
        )

        # The _refresh_readiness call must come AFTER the summary add.
        self.assertGreater(
            refresh_call_match.start(),
            summary_add_match.start(),
            "_refresh_readiness() must be called after _readiness_summary is added to the layout",
        )


if __name__ == "__main__":
    unittest.main()