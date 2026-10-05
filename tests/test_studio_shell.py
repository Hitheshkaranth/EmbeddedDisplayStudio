"""tests/test_studio_shell.py -- the Studio 2 shell.

Four modes over the workspace views, the device chip that holds the
connection controls, the status bar, and the Simulate view (Tag Lab and the
panel journal in one).
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer.mainwindow import MainWindow  # noqa: E402


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.window._stop_all_senders()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def view(self):
        tabs = self.window._right_tabs
        return tabs.tabText(tabs.currentIndex())

    def test_every_view_belongs_to_one_mode(self):
        window = self.window
        views = [window._right_tabs.tabText(i) for i in range(window._right_tabs.count())]
        claimed = [view for _mode, members in window.MODES for view in members]
        self.assertEqual(sorted(views), sorted(claimed))
        self.assertEqual([window.mode_nav.tabText(i) for i in range(window.mode_nav.count())],
                         ["Design", "Simulate", "Code", "Deploy"])

    def test_modes_show_their_views_and_remember_the_last_one(self):
        window = self.window
        window.mode_nav.setCurrentIndex(0)
        self.assertEqual([window.view_nav.tabText(i) for i in range(window.view_nav.count())],
                         ["Designer", "AI Design"])
        window.view_nav.setCurrentIndex(1)
        self.assertEqual(self.view(), "AI Design")
        window.mode_nav.setCurrentIndex(1)
        self.assertEqual(self.view(), "Simulate")
        self.assertTrue(window.view_nav.isHidden())          # one view: no sub-switch
        window.mode_nav.setCurrentIndex(0)
        self.assertEqual(self.view(), "AI Design")           # remembered

    def test_the_mode_follows_a_view_opened_by_code(self):
        window = self.window
        window.mode_nav.setCurrentIndex(3)
        window._right_tabs.setCurrentWidget(window.designer_workspace)
        self.assertEqual(window.mode_nav.tabText(window.mode_nav.currentIndex()), "Design")

    def test_device_chip_and_status_follow_the_link(self):
        window = self.window
        window.inp_host.setText("10.0.0.7")
        self.assertIn("10.0.0.7", window.btn_device.text())
        self.assertIn("Not connected", window.lbl_status_link.text())
        window._set_link_state("connected")
        self.app.processEvents()
        self.assertEqual(window.btn_device.property("linkState"), "connected")
        self.assertIn("Connected", window.lbl_status_link.text())

    def test_the_connection_controls_live_in_the_chip_popover(self):
        window = self.window
        popover = window._device_popover
        for widget in (window.inp_host, window.inp_port, window.btn_test,
                       window.btn_disconnect, window.lbl_connection):
            self.assertTrue(popover.isAncestorOf(widget), widget.objectName())

    def test_simulate_holds_the_tags_and_the_journal(self):
        window = self.window
        drawer = window.simulate_drawer
        self.assertEqual([drawer.tabText(i) for i in range(drawer.count())], ["Commands", "Panel log"])
        self.assertTrue(drawer.isAncestorOf(window.logs_view))
        self.assertTrue(drawer.isAncestorOf(window.taglab_panel._cmd_log))


class DeployViewTests(ShellTests.__base__):
    """Display Console and System Profile as one Deploy view."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.window._stop_all_senders()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def steps(self):
        return [self.window.deploy_steps.state(i) for i in range(4)]

    def test_the_steps_follow_the_progress_calls(self):
        import tools.hmi_deployer.mainwindow as module
        window = self.window
        window._progress_begin()
        self.assertEqual(self.steps(), ["running", "waiting", "waiting", "waiting"])
        window._progress_busy("Packaging bundle...")
        self.assertEqual(self.steps(), ["done", "running", "waiting", "waiting"])
        window._progress_set(module.PROGRESS_UPLOAD_START + 10, "Uploading bundle...")
        self.assertEqual(self.steps(), ["done", "done", "running", "waiting"])
        window._progress_fail("Could not reach the panel over SSH")
        self.assertEqual(self.steps(), ["done", "done", "failed", "waiting"])
        window._progress_begin()
        window._progress_set(module.PROGRESS_INSTALL_START, "Installing...")
        window._progress_succeed()
        self.assertEqual(self.steps(), ["done"] * 4)
        window._progress_cancel("Cancelled")
        self.assertEqual(self.steps(), ["waiting"] * 4)

    def test_readiness_is_a_checklist(self):
        window = self.window
        window._refresh_readiness()
        for name, mark in window._readiness_marks.items():
            with self.subTest(row=name):
                self.assertIn(mark.text(), ("✓", "!", "×", "•"))
                self.assertTrue(window._readiness_labels[name].text().startswith(name))

    def test_health_lives_in_deploy_and_waits_for_a_panel(self):
        window = self.window
        calls = []
        window.refresh_memory_profile = lambda: calls.append(True)
        window.mode_nav.setCurrentIndex(3)
        self.assertIs(window._right_tabs.currentWidget(), window._profile_page)
        self.assertEqual(calls, [])                      # nothing connected: no SSH
        self.assertTrue(window._profile_page.isAncestorOf(window.btn_refresh_profile))


if __name__ == "__main__":
    unittest.main()
