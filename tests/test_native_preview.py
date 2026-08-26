"""
tests/test_native_preview.py
Layer: Test (W11)

Pins the live bezel preview for runtime=python bundles (CONTRACT 4.1, 10).

A Qt Widgets application owns its own QApplication and top-level window, so it
cannot be composited into App Studio's QQuickWidget the way a QML entry can.
Until this existed the bezel showed an explanatory card, which meant the one
class of application the platform exists to adopt -- an existing Qt app never
written for this panel -- was the one you could not see before deploying it.

These tests run a real, unmodified Qt Widgets application through the real
shim and assert that a frame comes back at the target resolution with actual
content in it. The fixture app is deliberately written the way a customer's
would be: it constructs its own QApplication, calls show(), and ends with
sys.exit(app.exec()).
"""

import os
import sys
import textwrap
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from PySide6.QtGui import QGuiApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - environment without PySide6
    HAVE_QT = False

if HAVE_QT:
    from tools.hmi_deployer.native_preview import (
        PIP_FLAG,
        PREVIEW_SHIM_FLAG,
        NativePreview,
        find_interpreter,
        missing_module,
        pip_install_argv,
        preview_argv,
        preview_site_dir,
    )


# A customer application, written the ordinary way. Nothing here knows it is
# being previewed.
FIXTURE_APP = textwrap.dedent(
    '''
    import sys
    from PySide6.QtWidgets import (
        QApplication, QWidget, QLabel, QPushButton, QVBoxLayout
    )

    def main():
        app = QApplication(sys.argv)
        window = QWidget()
        window.setWindowTitle("Fixture")
        layout = QVBoxLayout(window)
        layout.addWidget(QLabel("Pressure"))
        layout.addWidget(QPushButton("PURGE"))
        window.resize(400, 300)
        window.show()
        sys.exit(app.exec())

    if __name__ == "__main__":
        main()
    '''
).strip()


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class NativePreviewRendersARealApp(unittest.TestCase):
    """The preview must produce real frames from an untouched application."""

    @classmethod
    def setUpClass(cls):
        """A QCoreApplication is needed for QTcpServer and the timers."""
        cls.app = QCoreApplication.instance() or QGuiApplication(sys.argv)

    def setUp(self):
        import tempfile
        self.bundle = Path(tempfile.mkdtemp())
        (self.bundle / "main.py").write_text(FIXTURE_APP, encoding="utf-8")
        (self.bundle / "manifest.json").write_text(
            '{"schema": 1, "name": "fixture", "version": "1.0.0",'
            ' "entry": "main.py", "runtime": "python"}',
            encoding="utf-8",
        )
        self.preview = NativePreview()

    def tearDown(self):
        self.preview.stop()
        import shutil
        shutil.rmtree(self.bundle, ignore_errors=True)

    def _await_frame(self, width, height, timeout_ms=45000):
        """Start the preview and spin the event loop until a frame arrives.

        Args:
            width:      target panel width in pixels.
            height:     target panel height in pixels.
            timeout_ms: how long to wait before giving up.

        Returns:
            (image, failure_message). Exactly one is truthy.
        """
        received = []
        failures = []
        loop = QEventLoop()

        self.preview.frameReady.connect(lambda img: (received.append(img), loop.quit()))
        self.preview.failed.connect(lambda msg: (failures.append(msg), loop.quit()))

        started = self.preview.start(
            str(self.bundle),
            {"entry": "main.py", "runtime": "python", "qt_binding": "pyside6"},
            width,
            height,
        )
        self.assertTrue(started or failures, "start() neither launched nor reported")

        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        guard.start(timeout_ms)
        loop.exec()

        return (received[0] if received else None,
                failures[0] if failures else "")

    def test_a_frame_arrives_at_the_target_resolution(self):
        """
        The panel framebuffer must come back at the requested size, while the
        application inside it keeps its own authored geometry.
        """
        image, failure = self._await_frame(1280, 800)
        self.assertIsNotNone(image, f"no frame arrived: {failure}")
        self.assertEqual((image.width(), image.height()), (1280, 800))

    def test_the_frame_has_real_content(self):
        """
        A uniformly blank frame would mean the window was grabbed before it
        rendered, which looks like success and is not.
        """
        image, failure = self._await_frame(800, 480)
        self.assertIsNotNone(image, f"no frame arrived: {failure}")
        colours = {
            image.pixel(x, y)
            for x in range(0, image.width(), 7)
            for y in range(0, image.height(), 7)
        }
        self.assertGreater(
            len(colours), 1,
            "The frame is a single flat colour: the app was grabbed before it "
            "painted anything.",
        )

    def test_a_missing_entry_fails_with_a_reason(self):
        """
        The caller falls back to the explanatory card on failure, so the
        message is the only thing the user gets. It must say what went wrong.
        """
        failures = []
        self.preview.failed.connect(failures.append)
        started = self.preview.start(
            str(self.bundle),
            {"entry": "not-here.py", "runtime": "python"},
            1280, 800,
        )
        self.assertFalse(started)
        self.assertTrue(failures)
        self.assertIn("not-here.py", failures[0])

    def test_stop_is_idempotent_and_kills_the_child(self):
        """Loading one bundle after another must not leave orphans rendering."""
        self._await_frame(800, 480)
        self.assertTrue(self.preview.is_running())
        self.preview.stop()
        self.assertFalse(self.preview.is_running())
        self.preview.stop()  # must not raise


# A Qt5 application, written the only way PySide2 allows: exec_(), because
# PySide2 has no `exec` at all.
FIXTURE_APP_QT5 = textwrap.dedent(
    '''
    import sys
    from PySide2.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout

    def main():
        app = QApplication(sys.argv)
        window = QWidget()
        layout = QVBoxLayout(window)
        layout.addWidget(QLabel("Pressure"))
        layout.addWidget(QLabel("PURGE"))
        window.resize(640, 320)
        window.show()
        sys.exit(app.exec_())

    if __name__ == "__main__":
        main()
    '''
).strip()


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class Qt5BundlePreview(unittest.TestCase):
    """A PySide2 bundle is the class of application this platform adopts.

    The shim read QApplication.exec to wrap it, which exists only in PySide6.
    Under PySide2 that raised in the shim's own preamble, before the
    application was given a chance to start, so every Qt5 bundle reported
    "the application exited" and the bezel stayed empty.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QGuiApplication(sys.argv)
        cls.interpreter = find_interpreter("pyside2")
        if not cls.interpreter:
            raise unittest.SkipTest("no PySide2 interpreter on this machine")

    def setUp(self):
        import tempfile
        self.bundle = Path(tempfile.mkdtemp())
        (self.bundle / "main.py").write_text(FIXTURE_APP_QT5, encoding="utf-8")
        self.preview = NativePreview()

    def tearDown(self):
        self.preview.stop()
        import shutil
        shutil.rmtree(self.bundle, ignore_errors=True)

    def test_a_qt5_application_reaches_the_bezel(self):
        """A real PySide2 app must render, not report that it exited."""
        received, failures = [], []
        loop = QEventLoop()
        self.preview.frameReady.connect(lambda img: (received.append(img), loop.quit()))
        self.preview.failed.connect(lambda msg: (failures.append(msg), loop.quit()))

        started = self.preview.start(
            str(self.bundle),
            {"entry": "main.py", "runtime": "python", "qt_binding": "pyside2"},
            1280, 800,
        )
        self.assertTrue(started, failures[0] if failures else "start() refused")

        guard = QTimer()
        guard.setSingleShot(True)
        guard.timeout.connect(loop.quit)
        guard.start(60000)
        loop.exec()

        self.assertTrue(
            received,
            "no frame from a PySide2 bundle: "
            + (failures[0] if failures else "timed out"),
        )
        image = received[0]
        self.assertEqual((image.width(), image.height()), (1280, 800))
        colours = {
            image.pixel(x, y)
            for x in range(0, image.width(), 11)
            for y in range(0, image.height(), 11)
        }
        self.assertGreater(len(colours), 1, "the Qt5 frame is a single flat colour")


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class ShimBindingCompatibility(unittest.TestCase):
    """The shim runs under both bindings and may assume neither."""

    def test_the_event_loop_is_never_read_by_one_name_only(self):
        """A bare QApplication.exec read is an AttributeError under PySide2.

        Cheap to assert and worth asserting: the end-to-end Qt5 test skips on
        any machine without a PySide2 interpreter, which includes CI.
        """
        from tools.hmi_deployer.native_preview import _SHIM
        self.assertIn('getattr(QApplication, "exec", None)', _SHIM)
        self.assertNotIn("_real_exec = QApplication.exec\n", _SHIM)


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class InterpreterResolution(unittest.TestCase):
    """Which interpreter a bundle is previewed with is not a free choice."""

    def test_pyside6_uses_this_interpreter(self):
        """App Studio is PySide6, so it can host a PySide6 bundle itself."""
        self.assertEqual(find_interpreter("pyside6"), sys.executable)

    def test_frozen_studio_runs_the_shim_through_its_own_flag(self):
        """A packaged Studio hosts the preview in a child of itself.

        `EmbeddedDisplayStudio.exe -c <shim>` is not a command: the binary is
        not an interpreter and would simply open a second Studio window
        claiming to be a panel preview. It must re-execute itself with the
        sub-command flag instead, which is what lets the executable preview a
        PySide6 bundle on a machine with no Python installed.
        """
        with mock.patch.object(sys, "frozen", True, create=True):
            argv = preview_argv(sys.executable)
        self.assertEqual(argv, [sys.executable, PREVIEW_SHIM_FLAG])
        self.assertNotIn("-c", argv)

    def test_source_checkout_hands_the_shim_to_a_real_interpreter(self):
        """Unfrozen, the interpreter takes the shim as source on argv."""
        argv = preview_argv(sys.executable)
        self.assertEqual(argv[:2], [sys.executable, "-c"])

    def test_an_external_interpreter_is_never_given_the_flag(self):
        """A PySide2 preview runs under a real Python, which has no such flag."""
        with mock.patch.object(sys, "frozen", True, create=True):
            argv = preview_argv(r"C:\other\python.exe")
        self.assertEqual(argv[:2], [r"C:\other\python.exe", "-c"])

    def test_a_missing_module_is_read_out_of_the_traceback(self):
        """The child's own error names what to install; nothing else does.

        This is the exact shape reported from a packaged build, where the
        customer's application reached for a standard-library module the
        frozen runtime did not carry.
        """
        output = (
            'File "<preview-shim>", line 156, in <module>\n'
            '  File "<frozen runpy>", line 280, in run_path\n'
            "ModuleNotFoundError: No module named 'pkgutil'"
        )
        self.assertEqual(missing_module(output), "pkgutil")

    def test_a_dotted_module_reports_its_top_level_package(self):
        """`No module named 'foo.bar'` is a missing foo, and foo is installable."""
        self.assertEqual(
            missing_module("ModuleNotFoundError: No module named 'foo.bar'"),
            "foo",
        )

    def test_ordinary_output_names_nothing(self):
        """An application that merely printed must not trigger an install."""
        self.assertEqual(missing_module("Traceback: ValueError: bad"), "")
        self.assertEqual(missing_module(""), "")

    def test_packages_install_into_a_writable_directory(self):
        """Never into the bundle: a frozen app's own directory is not writable,
        and a onefile build unpacks a fresh one on every run."""
        target = preview_site_dir()
        self.assertTrue(os.path.isabs(target))
        argv = pip_install_argv(["requests"])
        self.assertIn("--target", argv)
        self.assertEqual(argv[argv.index("--target") + 1], target)
        self.assertEqual(argv[-1], "requests")

    def test_a_frozen_build_installs_through_its_own_pip(self):
        """There is no `python -m pip` to call when there is no python."""
        with mock.patch.object(sys, "frozen", True, create=True):
            argv = pip_install_argv(["requests"])
        self.assertEqual(argv[:2], [sys.executable, PIP_FLAG])
        self.assertNotIn("-m", argv)

    def test_pyside2_never_uses_this_interpreter(self):
        """
        PySide2 and PySide6 cannot coexist in one process -- that is why the
        panel carries two runtimes. Returning sys.executable here would import
        PySide2 into a PySide6 process and take App Studio down with it.
        """
        found = find_interpreter("pyside2")
        self.assertNotEqual(
            found, sys.executable,
            "A pyside2 bundle must never be previewed in App Studio's own "
            "interpreter.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
