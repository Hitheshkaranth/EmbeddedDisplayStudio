"""
tests/test_qt_deploy.py
Layer: Test

The Qt-runtime stage of a deploy (tools/hmi_deployer/qt_deploy.py): which
bundles enter it, the commands the panel is asked to run, the launcher upload,
and the decisions taken on the panel's answers.

The panel side of these commands is POSIX sh on a Verdin; here they are
checked for content and, where a bash is available, for syntax.
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.hmi_deployer import qt_deploy  # noqa: E402
from tools.hmi_deployer.qt_deploy import (  # noqa: E402
    INSTALLER_FEATURE_MARKER,
    LAUNCHER_FILES,
    QtRuntimeDeployMixin,
    build_launcher_install_command,
    build_qt5_runtime_install_command,
    build_runtime_check_command,
    build_wheel_install_command,
    needs_qt_runtime,
    pack_launcher,
    panel_python_version,
    parse_runtime_line,
)

_BASH = shutil.which("bash")


def assert_sh_syntax(test: unittest.TestCase, command: str) -> None:
    """bash -n: the command at least parses (skipped without a bash)."""
    if not _BASH:
        return
    result = subprocess.run([_BASH, "-n", "-c", command], capture_output=True, text=True)
    test.assertEqual(result.returncode, 0, result.stderr)


class WhichBundlesNeedQt(unittest.TestCase):
    """Only a Python Qt application enters the stage."""

    def test_edsui_and_qml_bundles_do_not(self):
        self.assertIsNone(needs_qt_runtime({"runtime": "edsui"}))
        self.assertIsNone(needs_qt_runtime({"runtime": "qml"}))
        self.assertIsNone(needs_qt_runtime(None))

    def test_python_bundle_binding_defaults_to_pyside6(self):
        self.assertEqual(needs_qt_runtime({"runtime": "python"}), "pyside6")
        self.assertEqual(
            needs_qt_runtime({"runtime": "python", "qt_binding": "pyside2"}), "pyside2"
        )

    def test_wheels_are_fetched_for_the_runtime_interpreter(self):
        """Debian's PySide2 is cp311; /opt/hmi-python is 3.12."""
        self.assertEqual(panel_python_version("pyside2"), "3.11")
        self.assertEqual(panel_python_version("pyside6"), "3.12")


class RemoteCommands(unittest.TestCase):
    """What the panel is asked to run."""

    def test_check_reports_every_item(self):
        for binding in ("pyside2", "pyside6"):
            command = build_runtime_check_command(binding)
            for item in ("weston", "launcher", "installer", "python", "qt"):
                self.assertIn(f"r {item} ", command)
            assert_sh_syntax(self, command)

    @unittest.skipUnless(_BASH, "needs a bash")
    def test_check_runs_to_the_end_with_stdin_left_open(self):
        """Over ssh, stdin never closes: a probe that reads it hangs the check
        (the installer grep once lost its file to quoting and did just that)."""
        for binding in ("pyside2", "pyside6"):
            proc = subprocess.Popen(
                [_BASH, "-c", build_runtime_check_command(binding)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            )
            try:
                out, _ = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail(f"{binding} check blocked on stdin")
            items = [parse_runtime_line(line) for line in out.splitlines()]
            self.assertEqual(
                [item[0] for item in items if item],
                ["weston", "launcher", "installer", "python", "qt"],
            )

    def test_check_imports_qt_under_the_launchers_environment(self):
        command = build_runtime_check_command("pyside2")
        self.assertIn("/opt/hmi-python-qt5/bin/python3", command)
        self.assertIn("qt5/lib", command)
        self.assertIn("import PySide2.QtWidgets", command)
        self.assertIn("import PySide6.QtWidgets", build_runtime_check_command("pyside6"))

    def test_check_looks_for_the_runtime_aware_installer(self):
        self.assertIn(INSTALLER_FEATURE_MARKER, build_runtime_check_command("pyside6"))

    def test_the_installer_carries_the_marker_the_check_looks_for(self):
        """Otherwise every deploy would replace hmi-install, forever."""
        text = (REPO_ROOT / "target" / "bin" / "hmi-install").read_text(encoding="utf-8")
        self.assertIn(INSTALLER_FEATURE_MARKER, text)

    def test_parse_runtime_line(self):
        self.assertEqual(parse_runtime_line("RT qt ok"), ("qt", True))
        self.assertEqual(parse_runtime_line("RT weston missing"), ("weston", False))
        self.assertIsNone(parse_runtime_line("RT qt maybe"))
        self.assertIsNone(parse_runtime_line("DEP serial ok"))

    def test_launcher_install_does_not_enable_the_service(self):
        """hmi-install enables the service that matches the bundle."""
        command = build_launcher_install_command("/tmp/hmi_upload/l.tar.gz")
        self.assertNotIn("systemctl enable", command)
        self.assertIn("daemon-reload", command)
        self.assertIn("[ -e /etc/default/hmi-gui ] ||", command)
        self.assertIn("hmi-install.bak-", command)
        assert_sh_syntax(self, command)

    def test_qt5_runtime_is_swapped_in_and_proved(self):
        command = build_qt5_runtime_install_command("/tmp/hmi_upload/rt.tar.gz")
        # Unpacked beside, then moved: a failed unpack leaves the old runtime.
        self.assertLess(command.index("tar xzf"), command.index("mv /opt/.hmi-python-qt5.new/python"))
        self.assertIn("QApplication", command)
        self.assertIn("RT_INSTALLED qt", command)
        assert_sh_syntax(self, command)

    def test_wheels_install_offline_one_run_per_package(self):
        command = build_wheel_install_command(
            "/tmp/hmi_upload/w.tar.gz", ["pyserial", "networkscan"], "pyside2"
        )
        self.assertEqual(command.count("pip install --no-index"), 2)
        self.assertIn("/opt/hmi-python-qt5/bin/python3", command)
        self.assertIn("PIP_START pyserial", command)
        self.assertIn("PIP_FAIL", command)
        assert_sh_syntax(self, command)

    def test_package_names_are_quoted(self):
        """Scanned names come from someone else's source code."""
        command = build_wheel_install_command("/tmp/w.tar.gz", ["evil; rm -rf /"], "pyside6")
        self.assertNotIn("; rm -rf /", command.replace("'evil; rm -rf /'", ""))


class LauncherUpload(unittest.TestCase):
    """The files a Qt app needs besides the runtime."""

    def test_packs_every_launcher_file_verbatim(self):
        out = Path(tempfile.mkdtemp()) / "l.tar.gz"
        self.addCleanup(shutil.rmtree, out.parent)
        pack_launcher(str(out))
        with tarfile.open(out) as tar:
            names = tar.getnames()
            for rel, name in LAUNCHER_FILES:
                self.assertIn(name, names)
                data = tar.extractfile(name).read()
                self.assertEqual(data, (REPO_ROOT / rel).read_bytes())
                self.assertNotIn(b"\r\n", data, f"{rel} has CRLF line endings")

    def test_a_missing_file_is_reported_by_name(self):
        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty)
        with self.assertRaises(FileNotFoundError) as caught:
            pack_launcher(os.path.join(empty, "l.tar.gz"), repo_root=empty)
        self.assertIn("hmi-gui-launch", str(caught.exception))


class FakeWindow(QtRuntimeDeployMixin):
    """Just enough MainWindow for the stage's decisions."""

    def __init__(self, manifest):
        self.current_manifest = manifest
        self.bundle_dir = "/bundle"
        self._deploy_generation = 1
        self.calls = []
        self.lines = []
        self.btn_deploy = mock.Mock()

    def log(self, text):
        self.lines.append(text)

    def run_ssh_worker(self, cmd, desc, callback=None, **kw):
        self.calls.append(("ssh", desc))

    def _progress_busy(self, stage):
        pass

    def _progress_fail(self, reason):
        self.calls.append(("fail", reason))

    def _progress_cancel(self, reason):
        self.calls.append(("cancel", reason))

    def _transport_failure(self, what, code):
        return f"{what} failed ({code})"

    def _start_dependency_scan(self):
        self.calls.append(("deps",))

    def ssh_port(self):
        return 22

    class _Field:
        def text(self):
            return "x"

    inp_host = inp_user = inp_key = _Field()


class StageDecisions(unittest.TestCase):
    """What the stage does with the panel's answer."""

    def answered(self, manifest, have, rechecked=False):
        window = FakeWindow(manifest)
        self.assertTrue(window._start_qt_runtime_stage())
        window._qt_have = dict(have)
        window._qt_rechecked = rechecked
        return window

    ALL = {"weston": True, "launcher": True, "installer": True, "python": True, "qt": True}

    def test_edsui_bundle_skips_the_stage(self):
        self.assertFalse(FakeWindow({"runtime": "edsui"})._start_qt_runtime_stage())

    def test_nothing_missing_goes_straight_to_dependencies(self):
        window = self.answered({"runtime": "python"}, self.ALL)
        window._on_qt_runtime_checked(0)
        self.assertIn(("deps",), window.calls)

    def test_no_weston_is_a_clear_failure(self):
        window = self.answered({"runtime": "python"}, {**self.ALL, "weston": False})
        window._on_qt_runtime_checked(0)
        self.assertEqual(window.calls[-1][0], "fail")
        self.assertIn("weston", window.calls[-1][1])

    def test_still_missing_after_install_fails_instead_of_looping(self):
        window = self.answered(
            {"runtime": "python", "qt_binding": "pyside2"},
            {**self.ALL, "qt": False}, rechecked=True,
        )
        window._on_qt_runtime_checked(0)
        self.assertEqual(window.calls[-1][0], "fail")
        self.assertIn("qt", window.calls[-1][1])

    def test_missing_pieces_are_installed_in_order_after_consent(self):
        window = self.answered(
            {"runtime": "python", "qt_binding": "pyside2"},
            {**self.ALL, "launcher": False, "qt": False},
        )
        with mock.patch.object(qt_deploy, "QMessageBox") as box_cls, \
                mock.patch.object(QtRuntimeDeployMixin, "_qt_next_step") as next_step:
            box = box_cls.return_value
            box.clickedButton.return_value = box.addButton.return_value
            window._on_qt_runtime_checked(0)
        self.assertEqual(window._qt_steps, ["launcher", "runtime"])
        next_step.assert_called_once()

    def test_declining_cancels(self):
        window = self.answered({"runtime": "python"}, {**self.ALL, "installer": False})
        with mock.patch.object(qt_deploy, "QMessageBox") as box_cls:
            box_cls.return_value.clickedButton.return_value = object()
            window._on_qt_runtime_checked(0)
        self.assertEqual(window.calls[-1][0], "cancel")

    def test_an_unreachable_panel_fails_the_stage(self):
        window = self.answered({"runtime": "python"}, {})
        window._on_qt_runtime_checked(255)
        self.assertEqual(window.calls[-1][0], "fail")


if __name__ == "__main__":
    unittest.main()
