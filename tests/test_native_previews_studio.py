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
        self.assertTrue(window.format_label("edsui").lower().startswith("design"))
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


# =========================================================================


# ------------------------------------------------------------ W3 additions
def _edsui_bundle(root):
    bundle = os.path.join(root, "engine-dashboard")
    shutil.copytree(FIXTURE, bundle)
    with open(os.path.join(bundle, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "name": "engine-dashboard", "version": "1.0.0",
                   "entry": "project.edsui", "runtime": "edsui",
                   "screen": {"width": 1024, "height": 768}}, handle)
    return bundle


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class DesignerRendererDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_live_toggle_is_named_for_the_renderer(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        self.assertEqual(workspace.live_action.text(), "Live preview")
        self.assertIn("hmi-ui", workspace.live_action.toolTip())
        os.environ["HMI_UI_BIN"] = "/nonexistent/hmi-ui"
        try:
            fallback = DesignerWorkspace()
            self.addCleanup(fallback.close)
            self.assertIn("Qt/QML", fallback.live_action.toolTip())
        finally:
            del os.environ["HMI_UI_BIN"]

    def test_renderer_background_follows_the_design(self):
        from designer.model.project import DesignerProject
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        self.assertEqual(workspace.scene.qml_previews.background, workspace.project.screen.background)
        project = DesignerProject.load(str(FIXTURE / "project.edsui"))
        project.screen.background = "#223344"
        workspace.load_project(project)
        self.assertEqual(workspace.scene.qml_previews.background, "#223344")

    def test_widget_render_is_at_the_widget_size(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.add_widget("ShButton")
        widget = workspace.current_page.widgets[0]
        renderer = workspace.scene.qml_previews
        width, height = int(widget.geometry["width"]), int(widget.geometry["height"])
        theme = workspace.project.screen.theme
        self.assertTrue(_wait(lambda: renderer.image_for(widget, width, height, theme) is not None))
        image = renderer.image_for(widget, width, height, theme)
        self.assertFalse(image.isNull())
        self.assertEqual((image.width(), image.height()), (width, height))


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class CodeSectionDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        self.workspace = DesignerWorkspace()
        self.addCleanup(self.workspace.close)
        self.workspace.add_widget("ShGauge")
        self.window = self.workspace.open_code_window()
        self.addCleanup(self.window.close)

    def test_design_and_runtime_c_are_offered_never_qml(self):
        from designer.ui import code_window
        self.assertEqual(code_window.FORMATS, ("edsui", "c"))
        self.assertEqual(self.window._fmt_box.count(), 2)
        self.assertTrue(self.window._fmt_box.itemText(0).startswith("Design"))
        self.assertIn("C", self.window._fmt_box.itemText(1))
        self.window.show_section("widget", "edsui")
        self.assertTrue(self.window._title.text().endswith("-- design (.edsui)"), self.window._title.text())
        with self.assertRaises(ValueError):
            self.window.show_section("page", "qml")

    def test_runtime_c_follows_the_selected_widget(self):
        ws = self.workspace
        ws.add_widget("ShButton")
        gauge, button = ws.current_page.widgets[-2], ws.current_page.widgets[-1]
        ws.scene.clearSelection(); ws.scene.item_for_id(gauge.id).setSelected(True); self.app.processEvents()
        self.window.show_section("widget", "c")
        self.assertTrue(self.window.editor.isReadOnly())
        self.assertIn("hmi_widget_shgauge", self.window.editor.code())
        self.assertIn("w_shgauge.c", self.window._title.text())
        ws.scene.clearSelection(); ws.scene.item_for_id(button.id).setSelected(True); self.app.processEvents()
        self.assertIn("hmi_widget_shbutton", self.window.editor.code())
        self.window.show_section("page", "c")
        code = self.window.editor.code()
        self.assertIn("// w_shgauge.c", code)
        self.assertIn("// w_shbutton.c", code)
        self.assertFalse(self.window.is_edited())

    def test_widget_scope_preview_is_hmi_ui_at_the_widget_size(self):
        widget = self.workspace.current_page.widgets[0]
        self.window.show_section("widget", "edsui")
        self.window.set_preview_visible(True)
        self.window.show()
        self.assertTrue(_wait(lambda: isinstance(self.window.preview_image(), QImage)))
        image = self.window.preview_image()
        self.assertEqual((image.width(), image.height()),
                         (int(widget.geometry["width"]), int(widget.geometry["height"])))
        self.assertEqual(self.window.preview_renderer_name(), "hmi-ui")

    def test_page_preview_follows_a_design_change(self):
        self.window.show_section("page", "edsui")
        self.window.set_preview_visible(True)
        self.window.show()
        self.assertTrue(_wait(lambda: isinstance(self.window.preview_image(), QImage)))
        first = self.window.preview_image()
        self.workspace.add_widget("ShButton", 600, 500)
        self.app.processEvents()
        self.assertTrue(_wait(lambda: self.window.preview_image() is not None
                              and self.window.preview_image() is not first))

    def test_preview_falls_back_to_qml_without_binary(self):
        os.environ["HMI_UI_BIN"] = "/nonexistent/hmi-ui"
        try:
            from designer.ui.designer_workspace import DesignerWorkspace
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            window = workspace.open_code_window()
            self.addCleanup(window.close)
            self.assertEqual(window.preview_renderer_name(), "qml")
            self.assertEqual(window.fmt, "edsui")
        finally:
            del os.environ["HMI_UI_BIN"]


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class BezelDetails(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _panel(self):
        from tools.hmi_deployer.devicepanel import DevicePanel
        panel = DevicePanel()
        self.addCleanup(lambda: (panel.stop_preview(), panel.deleteLater(), self.app.processEvents()))
        panel.resize(900, 700)
        return panel

    def _manifest(self, bundle):
        with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_nothing_loaded_is_the_empty_mode(self):
        panel = self._panel()
        self.assertEqual(panel.preview_mode(), "")
        self.assertIsNone(panel.preview_image())

    def test_edsui_bundle_renders_off_the_ui_thread_and_lands(self):
        root = tempfile.mkdtemp(prefix="eds-native-bezel-")
        self.addCleanup(shutil.rmtree, root, True)
        bundle = _edsui_bundle(root)
        panel = self._panel()
        panel.load_bundle(bundle, self._manifest(bundle))
        # The call returns before the render lands: nothing of the QML was loaded.
        self.assertTrue(panel.quick_widget.source().isEmpty())
        self.assertNotEqual(panel.preview_mode(), "qml")
        self.assertTrue(_wait(lambda: panel.preview_mode() == "hmi-ui"))
        image = panel.preview_image()
        self.assertEqual((image.width(), image.height()), (1024, 768))
        self.assertFalse(panel.native_view.isHidden())
        self.assertTrue(panel.qml_view.isHidden())

    def test_a_second_load_of_the_same_page_lands_at_once(self):
        root = tempfile.mkdtemp(prefix="eds-native-bezel-")
        self.addCleanup(shutil.rmtree, root, True)
        bundle = _edsui_bundle(root)
        panel = self._panel()
        panel.load_bundle(bundle, self._manifest(bundle))
        self.assertTrue(_wait(lambda: panel.preview_mode() == "hmi-ui"))
        # The renderer's cache answers a reload synchronously; the mode must
        # not be reset behind it.
        panel.load_bundle(bundle, self._manifest(bundle))
        self.assertEqual(panel.preview_mode(), "hmi-ui")
        self.assertIsInstance(panel.preview_image(), QImage)

    def test_edsui_bundle_falls_back_to_qml_without_binary(self):
        root = tempfile.mkdtemp(prefix="eds-native-bezel-")
        self.addCleanup(shutil.rmtree, root, True)
        bundle = _edsui_bundle(root)
        os.makedirs(os.path.join(bundle, "generated"), exist_ok=True)
        with open(os.path.join(bundle, "generated", "App.qml"), "w", encoding="utf-8") as handle:
            handle.write("import QtQuick\nRectangle { width: 1024; height: 768; color: 'black' }\n")
        os.environ["HMI_UI_BIN"] = "/nonexistent/hmi-ui"
        try:
            panel = self._panel()
            panel.load_bundle(bundle, self._manifest(bundle))
        finally:
            del os.environ["HMI_UI_BIN"]
        self.assertEqual(panel.preview_mode(), "qml")
        self.assertIsNone(panel.preview_image())
        self.assertFalse(panel.quick_widget.source().isEmpty())

    def test_qml_bundle_is_unchanged(self):
        root = tempfile.mkdtemp(prefix="eds-qml-bezel-")
        self.addCleanup(shutil.rmtree, root, True)
        with open(os.path.join(root, "main.qml"), "w", encoding="utf-8") as handle:
            handle.write("import QtQuick\nRectangle { width: 800; height: 480; color: 'black' }\n")
        manifest = {"schema": 1, "name": "plain", "version": "1.0.0", "entry": "main.qml",
                    "runtime": "qml", "screen": {"width": 800, "height": 480}}
        panel = self._panel()
        panel.load_bundle(root, manifest)
        self.assertEqual(panel.preview_mode(), "qml")
        self.assertIsNone(panel.preview_image())


class PackagingSpec(unittest.TestCase):
    def test_spec_ships_the_windows_binary_beside_the_studio(self):
        spec = (REPO_ROOT / "packaging" / "EmbeddedDisplayStudio.spec").read_text(encoding="utf-8")
        self.assertIn('"out", "win64", "hmi-ui.exe"', spec)
        self.assertIn('(_hmi_ui, "hmi-ui")', spec)
        self.assertIn("binaries=binaries", spec)
        self.assertIn("file=sys.stderr", spec)


if __name__ == "__main__":
    unittest.main()
