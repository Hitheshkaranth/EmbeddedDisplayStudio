"""
tests/test_qt_binding.py
Layer: Test
Purpose: Cover which Qt binding a bundle is deployed against.

A panel hosts two application runtimes -- CPython 3.12 + PySide6 for Qt6 apps,
CPython 3.11 + PySide2 for Qt5 apps -- because PySide2 is Qt5-only and was
never built past Python 3.11. Which one starts is decided by the manifest's
"qt_binding", and getting it wrong is not a degraded experience: the app dies on
its first import line and systemd restart-loops it forever.

That failure is exactly what shipped before this field existed. A PySide2
application was imported, declared runtime=python, installed cleanly, was
reported "Running on the panel, and set as the boot default", and never drew a
pixel -- 38 crashes in 90 seconds. These tests pin the detection that stops it.
"""
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tools.hmi_deployer.deployer import (  # noqa: E402
    detect_bundle,
    detect_qt_binding,
    validate_bundle,
)


def write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class DetectQtBinding(unittest.TestCase):
    """detect_qt_binding reads the sources rather than trusting a convention."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = os.path.join(self.tmp.name, "app")
        os.makedirs(self.bundle)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_entry_importing_pyside2(self) -> None:
        write(os.path.join(self.bundle, "main.py"),
              "import sys\nfrom PySide2 import QtWidgets\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside2")

    def test_entry_importing_pyside6(self) -> None:
        write(os.path.join(self.bundle, "main.py"),
              "import sys\nfrom PySide6.QtWidgets import QApplication\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside6")

    def test_plain_import_form(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "import PySide2\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside2")

    def test_falls_back_to_the_rest_of_the_bundle(self) -> None:
        """
        The entry point often imports nothing itself.

        A launcher module that only pulls in the real application is common, and
        deciding from the entry point alone would call it Qt6 by default and
        start the wrong interpreter.
        """
        write(os.path.join(self.bundle, "main.py"), "from ui import start\nstart()\n")
        write(os.path.join(self.bundle, "ui.py"), "from PySide2 import QtWidgets\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside2")

    def test_majority_wins_when_both_appear(self) -> None:
        """
        Vendored subpackages muddy the signal.

        The application that prompted this carries a node_editor/ directory
        written against PySide6 while the application itself is PySide2. What
        must run is the application.
        """
        write(os.path.join(self.bundle, "main.py"), "import helpers\n")
        for i in range(3):
            write(os.path.join(self.bundle, "mod%d.py" % i), "from PySide2 import QtCore\n")
        write(os.path.join(self.bundle, "vendor", "widget.py"), "from PySide6 import QtCore\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside2")

    def test_no_qt_import_defaults_to_pyside6(self) -> None:
        """The platform's own binding is the safe default for an unknown app."""
        write(os.path.join(self.bundle, "main.py"), "print('hello')\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside6")

    def test_commented_import_is_not_a_signal(self) -> None:
        write(os.path.join(self.bundle, "main.py"),
              "# from PySide2 import QtWidgets\nfrom PySide6 import QtWidgets\n")
        self.assertEqual(detect_qt_binding(self.bundle, "main.py"), "pyside6")


class DetectBundleRecordsBinding(unittest.TestCase):
    """An imported app carries its binding into the manifest that is deployed."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = os.path.join(self.tmp.name, "adv-pdb")
        os.makedirs(self.bundle)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_python_bundle_gets_qt_binding(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        manifest = detect_bundle(self.bundle)
        self.assertEqual(manifest["runtime"], "python")
        self.assertEqual(manifest["qt_binding"], "pyside2")

    def test_pyside2_bundle_does_not_advertise_qt6(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        self.assertEqual(detect_bundle(self.bundle)["qt"], ">=5.15")

    def test_qml_bundle_has_no_binding(self) -> None:
        """A QML bundle runs inside the platform loader, which is PySide6 regardless."""
        write(os.path.join(self.bundle, "main.qml"), "import QtQuick\nItem {}\n")
        self.assertNotIn("qt_binding", detect_bundle(self.bundle))


class ValidateQtBinding(unittest.TestCase):
    """Validation catches a manifest that would start the wrong interpreter."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bundle = os.path.join(self.tmp.name, "app")
        os.makedirs(self.bundle)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def manifest(self, **overrides) -> None:
        base = {
            "schema": 1,
            "name": "app",
            "version": "1.0.0",
            "entry": "main.py",
            "runtime": "python",
            "screen": {"width": 1280, "height": 800},
            "tags_required": [],
            "qt": ">=5.15",
        }
        base.update(overrides)
        with open(os.path.join(self.bundle, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(base, f)

    def test_matching_binding_passes(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        self.manifest(qt_binding="pyside2")
        ok, msgs = validate_bundle(self.bundle)
        self.assertTrue(ok, msgs)
        self.assertIn("PySide2", msgs[0])

    def test_wrong_binding_is_rejected(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        self.manifest(qt_binding="pyside6")
        ok, msgs = validate_bundle(self.bundle)
        self.assertFalse(ok)
        self.assertTrue(any("qt_binding" in m for m in msgs), msgs)

    def test_unknown_binding_is_rejected(self) -> None:
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        self.manifest(qt_binding="pyqt5")
        ok, msgs = validate_bundle(self.bundle)
        self.assertFalse(ok)

    def test_absent_binding_still_validates(self) -> None:
        """
        Manifests written before the field existed must not start failing.

        The caller fills the value in, and the panel sniffs the entry point as a
        last resort, so absence is incomplete rather than wrong.
        """
        write(os.path.join(self.bundle, "main.py"), "from PySide2 import QtWidgets\n")
        self.manifest()
        ok, msgs = validate_bundle(self.bundle)
        self.assertTrue(ok, msgs)
        self.assertIn("PySide2", msgs[0])

    def test_qml_bundle_ignores_binding(self) -> None:
        write(os.path.join(self.bundle, "main.qml"), "import QtQuick\nItem {}\n")
        self.manifest(entry="main.qml", runtime="qml", qt_binding="nonsense")
        ok, msgs = validate_bundle(self.bundle)
        self.assertTrue(ok, msgs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
