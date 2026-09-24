"""Preview opens the design in a window of its own, live and operable.

The bezel in the Display Console is for judging a layout; the live preview
window is for using it: the generated app at the panel's real resolution,
on the Studio's tag engine, so a control's write leaves through the same
path it would on the glass.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.generators.qml_generator import QmlGenerator  # noqa: E402
from designer.model import DesignerAction, DesignerBinding, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402
from hmi_loader.tagengine import TagEngine, expose_to_qml  # noqa: E402
from tools.hmi_deployer.live_preview import LivePreviewWindow  # noqa: E402
from tools.hmi_deployer.mainwindow import MainWindow  # noqa: E402


def _bundle(widgets, width=640, height=400):
    project = DesignerProject(name="live")
    project.screen.width, project.screen.height = width, height
    project.pages[0].widgets = widgets
    bundle = tempfile.mkdtemp()
    paths = QmlGenerator(default_registry()).write(project, os.path.join(bundle, "generated"), bundle)
    manifest = {"schema": 1, "name": "live", "version": "1.0.0", "runtime": "qml",
                "entry": os.path.relpath(paths[0], bundle).replace(os.sep, "/"),
                "screen": {"width": width, "height": height},
                "tags_required": project.required_tags()}
    with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    project.save(os.path.join(bundle, "project.edsui"))
    return bundle, manifest


class LivePreviewWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_app_runs_at_target_size_and_zoom_scales_the_picture(self):
        bundle, manifest = _bundle([DesignerWidget(
            "ShClusterGauge", "tacho", {"x": 100, "y": 20, "width": 300, "height": 300},
            {}, {"value": DesignerBinding("mb.rpm")})])
        engine = TagEngine(manifest["tags_required"], rx_port=0, allow_any_port=True,
                           daemon_host="127.0.0.1", daemon_port=5000)
        window = LivePreviewWindow()
        self.addCleanup(window.close)
        window.load(bundle, manifest, engine, expose_to_qml)
        window.show()
        QTest.qWait(200)
        app = window.app_item()
        self.assertIsNotNone(app)
        self.assertEqual((app.property("width"), app.property("height")), (640, 400))
        self.assertEqual((window.quick.width(), window.quick.height()), (640, 400))
        window.zoom.setCurrentIndex(0)   # 50 %
        QTest.qWait(50)
        self.assertEqual((window.quick.width(), window.quick.height()), (320, 200))
        # The layout is still the panel's: zoom scales the picture only.
        self.assertEqual((app.property("width"), app.property("height")), (640, 400))

    def test_a_binding_on_a_property_the_widget_lacks_does_not_empty_the_window(self):
        """AI Design bound ShAnnunciator "value"; the generated file then
        failed to load and the window stayed dark. The threshold still lights
        the lamp; only the raw assignment is dropped."""
        bundle, manifest = _bundle([DesignerWidget(
            "ShAnnunciator", "lamp", {"x": 10, "y": 10, "width": 175, "height": 48},
            {"text": "CRITICAL"},
            {"value": DesignerBinding("di.fault", warning="> 2.5", critical="> 3.0")})])
        qml = open(os.path.join(bundle, manifest["entry"]), encoding="utf-8").read()
        self.assertNotIn("value: Bus.value", qml)
        self.assertIn("lit:", qml)
        engine = TagEngine(manifest["tags_required"], rx_port=0, allow_any_port=True,
                           daemon_host="127.0.0.1", daemon_port=5000)
        window = LivePreviewWindow()
        self.addCleanup(window.close)
        window.load(bundle, manifest, engine, expose_to_qml)
        window.show()
        QTest.qWait(200)
        self.assertIsNotNone(window.app_item(), window.errors())
        self.assertEqual(window.errors(), [])

    def test_a_file_that_does_not_load_says_why(self):
        """One bad line fails the whole file; the window used to show only
        its background, with nothing in the console."""
        bundle, manifest = _bundle([DesignerWidget(
            "ShButton", "b", {"x": 10, "y": 10, "width": 120, "height": 40}, {"text": "Go"})])
        with open(os.path.join(bundle, manifest["entry"]), "a", encoding="utf-8") as handle:
            handle.write("\nthis is not qml\n")
        window = LivePreviewWindow()
        self.addCleanup(window.close)
        reported = []
        window.problem.connect(reported.append)
        window.load(bundle, manifest, None, lambda *_: None)
        QTest.qWait(100)
        self.assertIsNone(window.app_item())
        self.assertTrue(reported)
        self.assertIn("did not load", window.feed.text())

    def test_a_control_in_the_window_writes_through_the_tag_engine(self):
        bundle, manifest = _bundle([DesignerWidget(
            "ShDriveMode", "mode", {"x": 10, "y": 10, "width": 180, "height": 56},
            {"modes": "ECO,SPORT", "currentIndex": 0},
            {"currentIndex": DesignerBinding("mb.mode")},
            actions={"activated": DesignerAction("write", "mb.mode")})])
        engine = TagEngine(manifest["tags_required"], rx_port=0, allow_any_port=True,
                           daemon_host="127.0.0.1", daemon_port=5000)
        sent = []
        engine.write = lambda tag, value: sent.append((tag, value))
        window = LivePreviewWindow()
        self.addCleanup(window.close)
        window.load(bundle, manifest, engine, expose_to_qml)
        window.show()
        QTest.qWait(200)
        mode = next(c for c in window.app_item().childItems() if c.property("modes") == "ECO,SPORT")
        mode.step(1)
        self.assertEqual(sent, [("mb.mode", 1)])


class StudioOpensTheLivePreview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._stylesheet, cls._font = cls.app.styleSheet(), cls.app.font()
        cls._org, cls._name = cls.app.organizationName(), cls.app.applicationName()
        cls.app.setOrganizationName("MIL-HMI-tests")
        cls.app.setApplicationName("LivePreviewTests")
        # MainWindow keeps its settings under a fixed ("MIL-HMI", "Deployer")
        # key, so every bundle a test opens becomes the user's startup bundle.
        # Put back whatever was there when the class is done.
        from PySide6.QtCore import QSettings
        cls._last_bundle = QSettings("MIL-HMI", "Deployer").value("last_bundle", "")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)
        cls.app.setOrganizationName(cls._org)
        cls.app.setApplicationName(cls._name)
        from PySide6.QtCore import QSettings
        QSettings("MIL-HMI", "Deployer").setValue("last_bundle", cls._last_bundle)

    def test_designer_preview_opens_the_window_on_the_shared_engine(self):
        bundle, manifest = _bundle([DesignerWidget(
            "ShTelltale", "lamp", {"x": 10, "y": 10, "width": 48, "height": 48},
            {"icon": "bulb"}, {"lit": DesignerBinding("di.lamp")})])
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), window.deleteLater(), self.app.processEvents()))
        # The Designer tab is in front: the bezel stays suspended, the live
        # window must still come up.
        window._preview_designed_bundle(bundle)
        QTest.qWait(200)
        live = window._live_preview
        self.assertIsNotNone(live)
        self.assertTrue(live.isVisible())
        self.assertIs(live._tag_engine, window.device_panel.tag_engine)
        self.assertTrue(window.btn_live_preview.isEnabled())
        # Closing it drops the reference; the next Preview makes a fresh one.
        live.close()
        self.app.processEvents()
        self.assertIsNone(window._live_preview)


if __name__ == "__main__":
    unittest.main()
