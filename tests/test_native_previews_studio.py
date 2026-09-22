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


# =========================================================================
# STAND-IN, removed at integration.
#
# W2 owns designer/preview/native_renderer.py; in this worktree its
# functions still raise NotImplementedError. The block below is a minimal
# working renderer written to that module's docstrings (one child process
# per render through a temporary one-page bundle, a QObject with ready /
# failed, image_for / page_image_for / render_page_sync / render_widget_sync
# / clear / shutdown, plus find_hmi_ui / kit_dir / page_key), installed by
# setUpModule over the `designer.preview` names only when the real ones
# raise. It is what the W3 tests run against until W2's file lands.
# =========================================================================
def _install_native_renderer_stand_in():
    import copy
    import subprocess
    from collections import OrderedDict

    import designer.preview as preview
    from designer.preview import native_renderer as contract
    from PySide6.QtCore import QObject, QProcess, Qt, Signal
    from designer.model.project import DesignerPage, DesignerProject, DesignerScreen

    try:
        contract.find_hmi_ui()
        return False                      # W2's implementation has landed
    except NotImplementedError:
        pass

    def find_hmi_ui():
        override = os.environ.get("HMI_UI_BIN")
        if override:
            return override if os.path.isfile(override) and os.access(override, os.X_OK) else None
        candidates = []
        frozen = getattr(sys, "_MEIPASS", None)
        if frozen:
            candidates.append(os.path.join(frozen, "hmi-ui", "hmi-ui.exe" if os.name == "nt" else "hmi-ui"))
        candidates.append(str(BIN.parent / "win64" / "hmi-ui.exe") if os.name == "nt" else str(BIN))
        for path in candidates:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path)
        return None

    _kit = {}

    def kit_dir():
        # The repository kit. Copied once to a temporary directory for the
        # stand-in only: a /mnt/c checkout under WSL reads the fonts through
        # 9P, which turns a 90 ms render into several seconds.
        if "path" not in _kit:
            source = REPO_ROOT / "ui" / "qml" / "Shadcn"
            root = tempfile.mkdtemp(prefix="eds-kit-")
            for sub in ("fonts", "icons"):
                shutil.copytree(source / sub, os.path.join(root, sub))
            _kit["path"] = root
        return _kit["path"]

    def page_key(project, page, theme, scale=1.0):
        screen = project.screen
        return json.dumps(["page", screen.width, screen.height, screen.background, theme,
                           round(scale, 2), [w.to_dict() for w in page.widgets]],
                          sort_keys=True, default=str)

    def _load(path, scale):
        image = QImage(path)
        if image.isNull():
            return None
        image = image.convertToFormat(QImage.Format_ARGB32)
        if scale != 1.0:
            image = image.scaled(max(1, int(image.width() * scale)), max(1, int(image.height() * scale)),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return image

    class NativeRenderer(QObject):
        ready = Signal(str)
        failed = Signal(str, str)

        def __init__(self, binary=None, parent=None):
            super().__init__(parent)
            self.binary = binary or find_hmi_ui()
            self.available = bool(self.binary)
            self.enabled = True
            self.background = "#101418"
            self.parallel = 2
            self._cache = OrderedDict()
            self._queue = OrderedDict()   # key -> (project, theme, scale)
            self._running = {}            # key -> (QProcess, tmpdir, out.png, scale)

        # -- projects to render ------------------------------------------
        def _widget_project(self, widget, width, height, theme):
            still = copy.deepcopy(widget)
            still.geometry.update({"x": 0, "y": 0})
            still.bindings = {}
            still.actions = {}
            return DesignerProject(name="preview", screen=DesignerScreen(
                width=int(width), height=int(height), background=self.background, theme=theme),
                pages=[DesignerPage(id="preview", name="preview", widgets=[still])])

        @staticmethod
        def _page_project(project, page, theme):
            screen = copy.copy(project.screen)
            screen.theme = theme
            return DesignerProject(name=project.name, screen=screen, pages=[page])

        def _command(self, project, theme, tmp):
            project.save(os.path.join(tmp, "project.edsui"))
            out = os.path.join(tmp, "out.png")
            return [self.binary, "--apps-dir", tmp, "--headless", out, "--kit", kit_dir(),
                    "--theme", theme], out

        # -- API ----------------------------------------------------------
        def image_for(self, widget, width, height, theme, scale=1.0):
            if not self.enabled or width < 2 or height < 2:
                return None
            from designer.canvas.qml_previews import preview_key
            key = preview_key(widget, width, height, theme, scale)
            return self._cached_or_schedule(key, lambda: self._widget_project(widget, width, height, theme),
                                            theme, scale)

        def page_image_for(self, project, page, theme, scale=1.0):
            if not self.enabled:
                return None
            key = page_key(project, page, theme, scale)
            return self._cached_or_schedule(key, lambda: self._page_project(project, page, theme), theme, scale)

        def render_page_sync(self, project, page, theme, timeout_ms=10000):
            return self._sync(self._page_project(project, page, theme), theme, timeout_ms)

        def render_widget_sync(self, widget, width, height, theme, timeout_ms=10000):
            return self._sync(self._widget_project(widget, width, height, theme), theme, timeout_ms)

        def clear(self):
            self._cache.clear()
            self._queue.clear()

        def shutdown(self):
            self._queue.clear()
            for key, (proc, tmp, _out, _scale) in list(self._running.items()):
                proc.blockSignals(True)
                proc.kill()
                proc.waitForFinished(1000)
                shutil.rmtree(tmp, True)
            self._running.clear()

        # -- pipeline -----------------------------------------------------
        def _cached_or_schedule(self, key, make_project, theme, scale):
            if key in self._cache:
                return self._cache[key]
            if key not in self._queue and key not in self._running:
                self._queue[key] = (make_project(), theme, scale)
                self._pump()
            return None

        def _pump(self):
            while self._queue and len(self._running) < self.parallel:
                key, (project, theme, scale) = self._queue.popitem(last=False)
                tmp = tempfile.mkdtemp(prefix="eds-render-")
                argv, out = self._command(project, theme, tmp)
                proc = QProcess(self)
                proc.finished.connect(lambda _code, _status, key=key: self._finished(key))
                proc.errorOccurred.connect(lambda _err, key=key: self._finished(key))
                self._running[key] = (proc, tmp, out, scale)
                proc.start(argv[0], argv[1:])

        def _finished(self, key):
            entry = self._running.pop(key, None)
            if entry is None:
                return
            proc, tmp, out, scale = entry
            image = _load(out, scale) if proc.exitCode() == 0 else None
            message = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            shutil.rmtree(tmp, True)
            proc.deleteLater()
            if image is None:
                self._cache[key] = QImage()
                self.failed.emit(key, message or "hmi-ui produced no image")
            else:
                self._cache[key] = image
            self.ready.emit(key)
            self._pump()

        def _sync(self, project, theme, timeout_ms):
            tmp = tempfile.mkdtemp(prefix="eds-render-")
            try:
                argv, out = self._command(project, theme, tmp)
                run = subprocess.run(argv, capture_output=True, timeout=timeout_ms / 1000.0)
                return _load(out, 1.0) if run.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                return None
            finally:
                shutil.rmtree(tmp, True)

    for module in (preview, contract):
        module.NativeRenderer = NativeRenderer
        module.find_hmi_ui = find_hmi_ui
        module.kit_dir = kit_dir
    contract.page_key = page_key
    return True


def setUpModule():
    _install_native_renderer_stand_in()
# ============================================ end of STAND-IN ============


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

    def test_combo_and_title_follow_the_format(self):
        from designer.ui import code_window
        for fmt in code_window.FORMATS:
            self.window.show_section("widget", fmt)
            self.assertEqual(self.window._fmt_box.currentText(), self.window.format_label(fmt))
            self.assertEqual(code_window.FORMAT_ORDER[self.window._fmt_box.currentIndex()], fmt)
        self.window.show_section("widget", "edsui")
        self.assertTrue(self.window._title.text().endswith("-- design (.edsui)"), self.window._title.text())
        self.window.show_section("page", "qml")
        self.assertTrue(self.window._title.text().endswith("-- QML (desktop preview)"), self.window._title.text())

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
