"""Tests for working out what a bundle needs installed on the panel."""

import os
import shutil
import tempfile
import unittest

from schema.deps import (
    Dependency,
    dependencies,
    imported_names,
    local_modules,
)
from tools.hmi_deployer.ssh import (
    build_dep_check_command,
    build_dep_install_command,
)


def write(path, text=""):
    """Create a file and every directory above it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class TestDependencyScan(unittest.TestCase):
    """A bundle's requirement is read off the application's own imports."""

    def setUp(self):
        self.bundle = tempfile.mkdtemp(prefix="hmi-deps-")
        self.addCleanup(shutil.rmtree, self.bundle, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.bundle, *parts)

    def test_third_party_import_is_reported_with_its_distribution(self):
        """`import serial` means the panel needs pyserial, not 'serial'."""
        write(self.path("main.py"), "import serial\nimport reportlab\n")

        self.assertEqual(
            dependencies(self.bundle),
            [Dependency("reportlab", "reportlab"), Dependency("serial", "pyserial")],
        )

    def test_stdlib_platform_and_local_modules_are_not_dependencies(self):
        """Only what pip must supply is left after the three exclusions."""
        write(self.path("main.py"),
              "import os, json, socket\n"
              "from PySide6.QtWidgets import QApplication\n"
              "import helper\n"
              "from widgets.dial import Dial\n")
        write(self.path("helper.py"), "VALUE = 1\n")
        write(self.path("widgets", "dial.py"), "class Dial: pass\n")

        self.assertEqual(dependencies(self.bundle), [])

    def test_guarded_import_is_not_required(self):
        """An import the author already handles failing is not a requirement."""
        write(self.path("main.py"),
              "try:\n"
              "    import Queue\n"
              "except ImportError:\n"
              "    import queue\n"
              "try:\n"
              "    import optional_extra\n"
              "except ModuleNotFoundError:\n"
              "    optional_extra = None\n")

        self.assertEqual(dependencies(self.bundle), [])

    def test_unguarded_import_survives_being_guarded_elsewhere(self):
        """One file's fallback must not excuse another file's hard import."""
        write(self.path("main.py"),
              "try:\n    import reportlab\nexcept ImportError:\n    reportlab = None\n")
        write(self.path("report.py"), "import reportlab\n")

        self.assertEqual(
            dependencies(self.bundle), [Dependency("reportlab", "reportlab")]
        )

    def test_files_that_are_not_packaged_are_not_scanned(self):
        """A build directory never reaches the panel, so its imports do not."""
        write(self.path("main.py"), "import serial\n")
        write(self.path("build", "generated.py"), "import tensorflow\n")
        write(self.path(".hmiignore"), "vendor_snapshot.py\n")
        write(self.path("vendor_snapshot.py"), "import torch\n")

        self.assertEqual(dependencies(self.bundle), [Dependency("serial", "pyserial")])

    def test_requirements_file_pins_the_version(self):
        """A scan can name a package; only the author can pin it."""
        write(self.path("main.py"), "import reportlab\n")
        write(self.path("requirements.txt"),
              "# needed for the PDF export\n"
              "reportlab>=4.0\n"
              "\n"
              "-r other.txt\n")

        self.assertEqual(
            dependencies(self.bundle), [Dependency("reportlab", "reportlab>=4.0")]
        )

    def test_syntax_error_does_not_stop_the_scan(self):
        """One unparseable file must not hide the rest of the application."""
        write(self.path("main.py"), "import serial\n")
        write(self.path("broken.py"), "def (:\n")

        self.assertEqual(dependencies(self.bundle), [Dependency("serial", "pyserial")])

    def test_relative_imports_resolve_inside_the_bundle(self):
        """A relative import is by definition satisfied by the bundle."""
        write(self.path("pkg", "__init__.py"))
        write(self.path("pkg", "view.py"), "from .model import Model\nfrom . import util\n")

        self.assertEqual(dependencies(self.bundle), [])


class TestLocalModules(unittest.TestCase):
    """Names the bundle supplies itself, at any depth."""

    def test_nested_modules_and_directories_count(self):
        """Apps put subdirectories on sys.path and import them as top level."""
        names = local_modules(["main.py", "pkg/__init__.py", "simulator/udp_sim.py"])

        self.assertIn("main", names)
        self.assertIn("pkg", names)
        self.assertIn("simulator", names)
        self.assertIn("udp_sim", names)


class TestImportedNames(unittest.TestCase):
    """Reading one file's imports."""

    def test_dotted_imports_reduce_to_their_top_level(self):
        """pip installs the distribution behind the first component."""
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         encoding="utf-8") as handle:
            handle.write("import os.path\nfrom reportlab.pdfgen import canvas\n")
            name = handle.name
        self.addCleanup(os.unlink, name)

        self.assertEqual(imported_names(name), {"os", "reportlab"})


class TestRemoteCommands(unittest.TestCase):
    """The commands the panel is asked to run."""

    def test_check_command_tests_by_importing(self):
        """Presence on disk is not the question; importing is."""
        command = build_dep_check_command(["reportlab"])

        self.assertIn('"$P" -c "import $m"', command)
        self.assertIn("DEP_PYTHON=", command)

    def test_pyside2_bundles_are_checked_against_the_qt5_runtime(self):
        """A package in the wrong interpreter is the same as no package."""
        command = build_dep_check_command(["serial"], qt_binding="pyside2")

        self.assertIn("/opt/hmi-python-qt5/bin/python3", command)

    def test_install_runs_pip_once_per_distribution(self):
        """One bad name must not take the others down with it."""
        command = build_dep_install_command(["reportlab", "pyserial"])

        self.assertEqual(command.count("pip install"), 2)
        self.assertIn("PIP_OK", command)
        self.assertIn("PIP_FAIL", command)

    def test_names_are_quoted_for_the_remote_shell(self):
        """Scanned names come from someone else's source code."""
        command = build_dep_install_command(["evil; rm -rf /"])

        self.assertNotIn("; rm -rf /", command.replace("'evil; rm -rf /'", ""))

    def test_hid_import_installs_self_contained_hidapi_distribution(self):
        from schema.deps import IMPORT_TO_DISTRIBUTION

        self.assertEqual(IMPORT_TO_DISTRIBUTION["hid"], "hidapi")


if __name__ == "__main__":
    unittest.main()
