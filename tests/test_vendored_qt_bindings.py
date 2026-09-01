"""A bundle must not ship the Qt the panel already provides.

A real deployment failed exactly this way. The bundle carried a PySide2/
directory that was not the bindings at all, but a desktop compatibility shim
whose __init__ did `import PySide6`, so a PySide2-written application could run
on a laptop that only had PySide6.

On the panel that inverts. The manifest correctly declared qt_binding=pyside2,
so hmi-gui started the Qt5 interpreter -- which carries the genuine PySide2 and
no PySide6 at all -- and the bundle's own directory, first on sys.path,
shadowed it. The application died on its first import, the GUI never marked
itself ready, and after a 60 MB upload the install rolled itself back 31
seconds later. Nothing host-side had objected, and the only account of why was
a traceback in the panel's journal.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from schema.manifest import validate_bundle  # noqa: E402


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


class VendoredQtBindingsAreRefused(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bundle = os.path.join(self.tmp.name, "app")
        os.makedirs(self.bundle)
        write(os.path.join(self.bundle, "main.py"),
              "from PySide2 import QtWidgets" + os.linesep)
        with open(os.path.join(self.bundle, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({
                "schema": 1, "name": "app", "version": "1.0.0", "entry": "main.py",
                "runtime": "python", "screen": {"width": 1280, "height": 800},
                "tags_required": [], "qt": ">=5.15", "qt_binding": "pyside2",
            }, handle)

    def _vendor(self, name):
        """Put a package named like a Qt binding at the bundle root."""
        write(os.path.join(self.bundle, name, "__init__.py"), "import PySide6")
        return os.path.join(self.bundle, name)

    def test_a_vendored_binding_is_refused_before_the_upload(self):
        self._vendor("PySide2")

        ok, messages = validate_bundle(self.bundle)

        self.assertFalse(ok, messages)
        self.assertTrue(
            any("shadows" in m and "PySide2" in m for m in messages), messages
        )

    def test_the_message_names_the_remedy(self):
        """A refusal the author cannot act on is only half a validator."""
        self._vendor("PySide2")

        _ok, messages = validate_bundle(self.bundle)

        self.assertTrue(any(".hmiignore" in m for m in messages), messages)

    def test_hmiignore_settles_it(self):
        """Excluded from the archive, it cannot shadow anything on the panel."""
        self._vendor("PySide2")
        write(os.path.join(self.bundle, ".hmiignore"), "PySide2")

        ok, messages = validate_bundle(self.bundle)

        self.assertTrue(ok, messages)

    def test_a_bundle_that_ships_no_qt_is_untouched(self):
        ok, messages = validate_bundle(self.bundle)

        self.assertTrue(ok, messages)

    def test_every_binding_name_is_covered_not_only_the_one_that_bit_us(self):
        for name in ("PySide6", "PyQt5", "PyQt6", "shiboken2", "shiboken6"):
            with self.subTest(package=name):
                path = self._vendor(name)
                ok, messages = validate_bundle(self.bundle)
                shutil.rmtree(path)
                self.assertFalse(ok, f"{name} was allowed through: {messages}")

    def test_a_single_module_counts_too(self):
        """PySide2.py shadows just as effectively as PySide2/."""
        write(os.path.join(self.bundle, "PySide2.py"), "import PySide6")

        ok, messages = validate_bundle(self.bundle)

        self.assertFalse(ok, messages)


if __name__ == "__main__":
    unittest.main()
