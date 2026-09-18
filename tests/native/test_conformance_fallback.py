"""
tests/native/test_conformance_fallback.py
Black-box conformance test — manifest validation and fallback behavior.
Each test uses a temporary bundle directory with its own manifest.
"""
import json
import os
import re
import tempfile
import time
import unittest

from .loader_harness import LoaderHarness


APP_QML = b"import QtQuick 2.15; Rectangle { color: 'white' }"


class TestConformanceFallback(unittest.TestCase):
    def _make_bundle(self, manifest_data):
        """Create a temporary bundle dir with the given manifest and a valid QML."""
        tmpdir = tempfile.mkdtemp(prefix="fallback_")
        manifest_path = os.path.join(tmpdir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f)
        qml_path = os.path.join(tmpdir, "main.qml")
        with open(qml_path, "wb") as f:
            f.write(APP_QML)
        return tmpdir

    def test_missing_directory(self):
        """Missing apps dir -> ERROR log, no ready file, exit 0."""
        harness = LoaderHarness(
            apps_dir="/nonexistent/fake-dir-" + str(os.getpid()),
            exit_after_ms=3000,
        )
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Manifest not found: ", text)
        self.assertFalse(os.path.exists(harness._ready_file))
        self.assertEqual(harness.exit_code, 0)

    def test_invalid_json(self):
        """manifest.json = 'not json' -> 'Manifest parse error:' prefix."""
        tmpdir = self._make_bundle({})
        manifest_path = os.path.join(tmpdir, "manifest.json")
        with open(manifest_path, "w") as f:
            f.write("not json")

        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Manifest parse error:", text)
        self.assertEqual(harness.exit_code, 0)

    def test_bad_schema(self):
        """schema=2 -> 'Expected schema: 1.'."""
        tmpdir = self._make_bundle({"schema": 2, "name": "ok-app"})
        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Unsupported or missing schema version. Expected schema: 1.", text)
        self.assertEqual(harness.exit_code, 0)

    def test_bad_name(self):
        """name='Bad Name' -> 'Invalid app name:' with regex."""
        tmpdir = self._make_bundle({"schema": 1, "name": "Bad Name"})
        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Invalid app name: 'Bad Name'. Must match", text)
        self.assertEqual(harness.exit_code, 0)

    def test_missing_entry(self):
        """No 'entry' key -> 'Missing 'entry' in manifest.'"""
        tmpdir = self._make_bundle({"schema": 1, "name": "no-entry"})
        manifest_path = os.path.join(tmpdir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({"schema": 1, "name": "no-entry"}, f)
        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Missing 'entry' in manifest.", text)
        self.assertEqual(harness.exit_code, 0)

    def test_entry_with_dotdot(self):
        """entry='../x.qml' -> 'Invalid entry path:' with exact message."""
        tmpdir = self._make_bundle({"schema": 1, "name": "dotdot-app", "entry": "../x.qml"})
        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Invalid entry path: '../x.qml'. Cannot be absolute or contain '..'.", text)
        self.assertEqual(harness.exit_code, 0)

    def test_entry_not_found(self):
        """entry='missing.qml' -> 'Entry point not found:' prefix."""
        tmpdir = self._make_bundle({"schema": 1, "name": "missing-entry", "entry": "missing.qml"})
        harness = LoaderHarness(apps_dir=tmpdir, exit_after_ms=3000)
        harness.start()
        time.sleep(5)
        harness.stop()
        text = "\n".join(harness.lines())
        self.assertIn("Entry point not found: ", text)
        self.assertEqual(harness.exit_code, 0)


if __name__ == "__main__":
    unittest.main()