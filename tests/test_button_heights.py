"""No button in the Studio stands taller than the Deploy button.

Every view of every mode is shown with a design loaded, and the device chip's
popover opened; each visible push or tool button is measured against
btn_deploy. A button that grows past it (a QSS `height` the layout stretched,
padding stacked on a min-height) fails here with its path.
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QToolButton  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "ci-smoke")


def _path(widget):
    names = []
    while widget is not None and len(names) < 4:
        names.append(widget.objectName() or type(widget).__name__)
        widget = widget.parentWidget()
    return " < ".join(names)


class ButtonHeights(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tools.hmi_deployer.mainwindow import MainWindow
        self.window = MainWindow()
        self.window.resize(1600, 1000)
        self.window.show()
        self.addCleanup(self._dispose)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        bundle = os.path.join(tmp, "bundle")
        shutil.copytree(FIXTURE, bundle)
        self.window.load_bundle(bundle)
        self.app.processEvents()

    def _dispose(self):
        self.window._stop_all_senders()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _too_tall(self, where, root, limit, found):
        for kind in (QPushButton, QToolButton):
            for button in root.findChildren(kind):
                if button.isVisible() and button.window() is root.window() and button.height() > limit:
                    found.add(f"{where}: {button.height()}px '{button.text() or button.toolTip()[:30]}' "
                              f"({_path(button)})")

    def test_no_button_is_taller_than_deploy(self):
        window, app = self.window, self.app
        limit = window.btn_deploy.height()
        self.assertGreater(limit, 0)
        found = set()
        for mode in range(window.mode_nav.count()):
            window.mode_nav.setCurrentIndex(mode)
            app.processEvents()
            for view in range(max(1, window.view_nav.count())):
                if window.view_nav.count():
                    window.view_nav.setCurrentIndex(view)
                for _ in range(3):
                    app.processEvents()
                self._too_tall(window.mode_nav.tabText(mode), window, limit, found)
        window._toggle_device_popover()
        app.processEvents()
        self._too_tall("device popover", window, limit, found)
        for top in app.topLevelWidgets():
            if top is not window and top.isVisible():
                self._too_tall(top.objectName() or type(top).__name__, top, limit, found)
        self.assertEqual(sorted(found), [], f"taller than Deploy ({limit}px)")


if __name__ == "__main__":
    unittest.main()
