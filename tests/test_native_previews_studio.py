"""The Studio draws its previews with hmi-ui when the binary is at hand (W3 gate).

FROZEN: the tests below are the minimum W3 must pass; add more below them,
never change these. They need the Linux hmi-ui binary
(native/hmi-ui/out/hmi-ui) -- run in WSL.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

BIN = REPO_ROOT / "native" / "hmi-ui" / "out" / "hmi-ui"
FIXTURE = REPO_ROOT / "tests" / "ui" / "fixtures" / "engine-dashboard"


def _wait(condition, timeout_ms=15000):
    waited = 0
    while not condition() and waited < timeout_ms:
        QTest.qWait(100)
        waited += 100
    return condition()


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class DesignerUsesNativeRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_workspace_picks_hmi_ui_when_available(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        self.assertEqual(type(workspace.scene.qml_previews).__name__, "NativeRenderer")
        self.assertEqual(workspace.preview_renderer_name, "hmi-ui")
        # The Designer's own live toggle drives the same renderer.
        workspace.toggle_live_previews(False)
        self.assertFalse(workspace.scene.qml_previews.enabled)
        workspace.toggle_live_previews(True)

    def test_workspace_falls_back_to_qml_without_binary(self):
        os.environ["HMI_UI_BIN"] = "/nonexistent/hmi-ui"
        try:
            from designer.ui.designer_workspace import DesignerWorkspace
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            self.assertEqual(type(workspace.scene.qml_previews).__name__, "QmlPreviewRenderer")
            self.assertEqual(workspace.preview_renderer_name, "qml")
        finally:
            del os.environ["HMI_UI_BIN"]

    def test_canvas_renders_a_widget_with_hmi_ui(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.resize(1200, 800); workspace.show()
        workspace.add_widget("ShGauge")
        widget = workspace.current_page.widgets[0]
        renderer = workspace.scene.qml_previews
        theme = workspace.project.screen.theme
        renderer.image_for(widget, int(widget.geometry["width"]), int(widget.geometry["height"]), theme)
        self.assertTrue(_wait(lambda: renderer.image_for(
            widget, int(widget.geometry["width"]), int(widget.geometry["height"]), theme) is not None))


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class CodeSectionUsesNativeRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_default_format_is_the_design_and_page_preview_is_hmi_ui(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.add_widget("ShGauge")
        window = workspace.open_code_window()
        self.addCleanup(window.close)
        # What the panel runs comes first; QML is the desktop's preview code.
        self.assertEqual(window.fmt, "edsui")
        labels = [window.format_label(f) for f in ("edsui", "qml")]
        self.assertTrue(labels[0].lower().startswith("design"), labels)
        self.assertIn("desktop", labels[1].lower(), labels)
        window.show_section("page", "edsui")
        window.set_preview_visible(True)
        window.show()
        self.assertTrue(_wait(lambda: isinstance(window.preview_image(), QImage)))
        image = window.preview_image()
        self.assertEqual((image.width(), image.height()),
                         (workspace.project.screen.width, workspace.project.screen.height))
        self.assertEqual(window.preview_renderer_name(), "hmi-ui")


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class BezelUsesNativeRenderer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        from PySide6.QtCore import QSettings
        cls._last_bundle = QSettings("MIL-HMI", "Deployer").value("last_bundle", "")
        cls._stylesheet, cls._font = cls.app.styleSheet(), cls.app.font()

    @classmethod
    def tearDownClass(cls):
        from PySide6.QtCore import QSettings
        QSettings("MIL-HMI", "Deployer").setValue("last_bundle", cls._last_bundle)
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)

    def test_edsui_bundle_shows_the_hmi_ui_render_in_the_bezel(self):
        from tools.hmi_deployer.mainwindow import MainWindow
        root = tempfile.mkdtemp(prefix="eds-native-bezel-")
        self.addCleanup(shutil.rmtree, root, True)
        bundle = os.path.join(root, "engine-dashboard")
        shutil.copytree(FIXTURE, bundle)
        with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "name": "engine-dashboard", "version": "1.0.0",
                       "entry": "project.edsui", "runtime": "edsui",
                       "screen": {"width": 1024, "height": 768}}, handle)
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), window.deleteLater(), self.app.processEvents()))
        window.show_preview_tab()
        window.load_bundle(bundle)
        self.assertTrue(_wait(lambda: window.device_panel.preview_mode() == "hmi-ui"))
        image = window.device_panel.preview_image()
        self.assertIsInstance(image, QImage)
        self.assertEqual((image.width(), image.height()), (1024, 768))


if __name__ == "__main__":
    unittest.main()
