"""
tests/test_capture_preview_tab.py
Layer: Test (W11)

Pins the one thing a bezel capture depends on that nothing else does: that the
Studio is showing a workspace where the runtime preview is loaded.

The bug these were written for: the Studio opens on the Designer, which hides
the runtime preview and unloads its renderers -- deliberately, so Qt Quick's
RHI renderer is not running behind a hidden panel. `--bundle` therefore loaded
a bundle straight into a suspended preview, and `--capture-bezel` grabbed an
empty panel. CI reported "the bundle's colour appears 0 times ... the window
opened but the application was not rendered inside the bezel", which reads like
a frozen-runtime failure -- the exact failure the smoke check exists to catch --
when the executable was fine and simply on the wrong tab.

The capture run is the only caller that needs the preview live while nobody is
looking at it, so it is the only one that has to ask.

Requires PySide6; skipped elsewhere.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - environment without PySide6
    HAVE_QT = False

if HAVE_QT:
    from tools.hmi_deployer.mainwindow import MainWindow


@unittest.skipUnless(HAVE_QT, "PySide6 is required for the Studio window")
class CapturePreviewTab(unittest.TestCase):
    """Drives the real MainWindow offscreen."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # MainWindow.apply_theme pushes the Studio stylesheet onto the
        # QApplication, and QSettings writes the opened bundle to the real
        # user store. Both outlive this file: leaving the stylesheet in place
        # changes widget metrics for every test that runs afterwards, which is
        # how a first draft of this file broke the toolbar layout assertions
        # in a module it never imports.
        cls._stylesheet = cls.app.styleSheet()
        cls._font = cls.app.font()
        cls._org = cls.app.organizationName()
        cls._name = cls.app.applicationName()
        cls.app.setOrganizationName("MIL-HMI-tests")
        cls.app.setApplicationName("CapturePreviewTab")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)
        cls.app.setOrganizationName(cls._org)
        cls.app.setApplicationName(cls._name)

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self._dispose)

    def _dispose(self):
        """Close and drop the window inside the test that made it.

        deleteLater alone defers to an event loop this suite does not run, so
        the windows pile up until interpreter shutdown and are reported as
        uncollectable.
        """
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    # -- tests -----------------------------------------------------------

    def test_the_studio_opens_on_the_designer(self):
        """The premise of everything below, and the reason the bug existed.

        If this ever changes the capture path stops depending on the switch --
        but so does the reasoning in show_preview_tab, which should then be
        revisited rather than left as a no-op nobody reads.
        """
        self.assertIs(
            self.window._right_tabs.currentWidget(),
            self.window.designer_workspace,
        )

    def test_show_preview_tab_leaves_the_designer(self):
        """A capture taken on the Designer is a capture of a hidden panel."""
        self.window.show_preview_tab()

        self.assertIsNot(
            self.window._right_tabs.currentWidget(),
            self.window.designer_workspace,
            "show_preview_tab left the Studio on the tab that hides the preview",
        )

    def test_the_preview_panel_is_visible_after_the_switch(self):
        """Visibility is what the suspension keys off, so assert it directly."""
        self.window.show_preview_tab()

        self.assertTrue(
            self.window._preview_panel_wrap.isVisibleTo(self.window),
            "the preview panel is still hidden, so the bezel grab would be empty",
        )

    def test_switching_away_from_the_designer_reloads_a_pending_bundle(self):
        """load_bundle on the Designer records the bundle without starting it.

        The tab change is what turns that record back into a running preview.
        Without this the capture switches to a visible but empty panel, which
        fails in exactly the same way and is harder to see.
        """
        bundle = REPO_ROOT / "tests" / "fixtures" / "ci-smoke"
        self.window.load_bundle(str(bundle))

        self.assertIsNone(
            self.window.device_panel.manifest,
            "the fixture no longer exercises the suspended-load path",
        )

        self.window.show_preview_tab()

        self.assertIsNotNone(
            self.window.device_panel.manifest,
            "the bundle was never handed to the panel, so nothing renders",
        )


if __name__ == "__main__":
    unittest.main()
