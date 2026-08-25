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
    from tools.hmi_deployer.native_preview import NativePreview, find_interpreter


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
        The point of the bezel is judging a layout at the panel's geometry, so
        the frame must come back at the requested size -- not at whatever size
        the application happened to call resize() with.
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


@unittest.skipUnless(HAVE_QT, "PySide6 is not installed")
class InterpreterResolution(unittest.TestCase):
    """Which interpreter a bundle is previewed with is not a free choice."""

    def test_pyside6_uses_this_interpreter(self):
        """App Studio is PySide6, so it can host a PySide6 bundle itself."""
        self.assertEqual(find_interpreter("pyside6"), sys.executable)

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
