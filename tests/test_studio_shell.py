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


class CanvasRequestTests(ShellTests.__base__):
    """A change asked for over the canvas, answered by a design that lost most
    of the page: Ornith once returned 10 of 45 widgets for "add the logo"."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(lambda: (self.window._stop_all_senders(), self.window.close(),
                                 self.window.deleteLater(), self.app.processEvents()))

    @staticmethod
    def _page(tags):
        from designer.model import DesignerBinding, DesignerProject, DesignerWidget
        project = DesignerProject(name="line")
        for i, tag in enumerate(tags):
            widget = DesignerWidget(type="ShValueTile", id=f"tile{i}",
                                    geometry={"x": 0, "y": 40 * i, "width": 100, "height": 40})
            widget.bindings["value"] = DesignerBinding(tag=tag)
            project.pages[0].widgets.append(widget)
        return project

    def _answer(self, project):
        window, tab = self.window, self.window._ai_tab
        window._ai_before = object()
        window._canvas_tags_before = set(window.designer_workspace.project.required_tags())
        tab.last_project = project
        tab.auto_apply.setChecked(True)
        window.designer_workspace.load_project(project)
        window._watch_canvas_ai()

    def test_a_reply_that_drops_most_of_the_page_is_put_back(self):
        workspace = self.window.designer_workspace
        workspace.load_project(self._page([f"line.v{i}" for i in range(10)]))
        self._answer(self._page(["line.v0", "line.v1"]))
        self.assertEqual(len(workspace.project.required_tags()), 10)
        self.assertIn("put back", workspace.chat_reply.text())

    def test_an_imported_logo_named_without_its_extension_still_shows(self):
        # Ornith was handed "assets/datasol_logo.png" and wrote "assets/datasol_logo".
        import tempfile
        from designer.model import DesignerWidget
        workspace = self.window.designer_workspace
        with tempfile.TemporaryDirectory() as bundle:
            os.makedirs(os.path.join(bundle, "assets"))
            open(os.path.join(bundle, "assets", "datasol_logo.png"), "wb").close()
            workspace.bundle_dir = bundle
            workspace.load_project(self._page(["line.v0"]))
            reply = self._page(["line.v0"])
            reply.pages[0].widgets.append(DesignerWidget(
                type="Image", id="logo", geometry={"x": 0, "y": 0, "width": 120, "height": 40},
                properties={"source": "assets/datasol_logo"}))
            self.window._canvas_imported = ["assets/datasol_logo.png"]
            self._answer(reply)
            logo = next(w for w in workspace.project.all_widgets() if w.id == "logo")
            self.assertEqual(logo.properties["source"], "assets/datasol_logo.png")
            workspace.bundle_dir = ""

    def test_a_reply_that_keeps_the_page_is_applied(self):
        workspace = self.window.designer_workspace
        workspace.load_project(self._page([f"line.v{i}" for i in range(10)]))
        self._answer(self._page([f"line.v{i}" for i in range(11)]))
        self.assertEqual(len(workspace.project.required_tags()), 11)
        self.assertIn("applied", workspace.chat_reply.text())


if __name__ == "__main__":
    unittest.main()
