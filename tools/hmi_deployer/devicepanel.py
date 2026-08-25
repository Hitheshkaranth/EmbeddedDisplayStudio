"""
tools/hmi_deployer/devicepanel.py
Layer: 3 (Host Deployer)
Purpose: The centred hardware mock-up of the panel with a live QML preview.
(CONTRACT section 10).
"""
import os
import sys
import logging
from PySide6.QtCore import Qt, QUrl, QRectF, QPropertyAnimation, Property, QRect, Signal
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQml import QQmlComponent, QQmlContext

from .native_preview import NativePreview

# Add repo's gui/ to sys.path to import tagengine
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GUI_DIR = os.path.join(REPO_ROOT, "gui")
if GUI_DIR not in sys.path:
    sys.path.insert(0, GUI_DIR)

try:
    from hmi_loader.tagengine import TagEngine
except ImportError as e:
    logging.warning(f"Failed to import TagEngine from gui/hmi_loader/tagengine.py: {e}")
    class TagEngine(QObject):
        # Fallback minimal local shim
        def __init__(self, expected_tags, rx_port=5001, daemon_host="127.0.0.1", daemon_port=5000, parent=None):
            super().__init__(parent)
            from PySide6.QtQml import QQmlPropertyMap
            self._map = QQmlPropertyMap(self)
            self._map.insert("online", False)
            for t in expected_tags:
                self._map.insert(t, None)
                self._map.insert(t.replace('.', '_'), None)
        def tagMap(self): return self._map
        @Slot(str, "QVariant")
        def write(self, tag, value): pass
        @Slot(str, int)
        def pulse(self, tag, ms): pass
        @Slot(str, "QVariant", result="QVariant")
        def value(self, name, fallback=None): return fallback

# Selectable panel geometries, ordered by diagonal. Each entry is
# (label, diagonal_inches, width_px, height_px). These are the display sizes
# commonly paired with a Verdin module; "Custom" is filled in from the loaded
# manifest so a bundle targeting anything else still previews correctly.
PANEL_PRESETS = [
    ('5.0" - 800 x 480',     5.0,   800,  480),
    ('7.0" - 1024 x 600',    7.0,  1024,  600),
    ('7.0" - 1280 x 800',    7.0,  1280,  800),
    ('10.1" - 1280 x 800',  10.1,  1280,  800),
    ('12.1" - 1280 x 800',  12.1,  1280,  800),
    ('15.6" - 1920 x 1080', 15.6,  1920, 1080),
]

# The preview never renders smaller than this, in device-independent pixels.
# Below roughly this size the bezel stops reading as a panel and the app inside
# it becomes unjudgeable, which defeats the point of a WYSIWYG preview. The
# splitter cannot collapse past it either.
MIN_PANEL_WIDTH = 720
MIN_PANEL_HEIGHT = 520


class DevicePanel(QWidget):
    """
    Renders the hardware mock-up of the panel.

    Signals:
        previewMessage(str): something the user should read about the preview,
            forwarded to the console panel. Used when a native preview cannot
            run, where the reason ("no PySide2 interpreter here", a traceback
            from the app) is the whole value of the message.
    """

    previewMessage = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Hard floor on the preview. The bezel is aspect-locked, so the widget
        # can still be given more room than this, but never less - the splitter
        # is prevented from squeezing the panel down to an unreadable sliver.
        self.setMinimumSize(MIN_PANEL_WIDTH, MIN_PANEL_HEIGHT)

        self.manifest = None
        self.bundle_dir = None
        self.target_width = 1280
        self.target_height = 800
        
        # LED state: 0 = idle/disconnected, 1 = link up, 2 = deploying, 3 = fault
        self._led_state = 0
        
        # Setup QQuickWidget for the screen
        self.quick_widget = QQuickWidget(self)
        self.quick_widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
        # We need to set the background transparent if we want the idle color to show, 
        # but the QQuickWidget fills its own rect. 
        self.quick_widget.setClearColor(QColor("#2b2b2b"))
        
        # We add Shadcn QML import path
        # ui/qml needs to be added
        UI_QML_DIR = os.path.join(REPO_ROOT, "ui", "qml")
        self.quick_widget.engine().addImportPath(UI_QML_DIR)

        # Where frames from a runtime=python bundle are painted.
        #
        # A Qt Widgets application cannot be composited into the QQuickWidget
        # above -- it owns its own QApplication and window -- so it is rendered
        # offscreen in a child process and the resulting frames are shown here.
        # The two views occupy the same rect and only one is ever visible.
        self.native_view = QLabel(self)
        self.native_view.setAlignment(Qt.AlignCenter)
        self.native_view.setStyleSheet("background: #2b2b2b;")
        self.native_view.setScaledContents(False)
        self.native_view.hide()

        self.native_preview = NativePreview(self)
        self.native_preview.frameReady.connect(self._on_preview_frame)
        self.native_preview.failed.connect(self._on_preview_failed)
        self.native_preview.stopped.connect(self._on_preview_stopped)

        # The most recent frame at full target resolution, kept so a resize can
        # rescale without waiting for the next one.
        self._native_frame = None

        self.tag_engine = None

        # Keeps the throwaway QML object that owns the Theme assignment alive;
        # if it were garbage collected the binding it created would go with it.
        self._theme_holder = None

        # The panel previews the DEVICE, and the device ships Theme.mode="dark"
        # (CONTRACT 11.1). The deployer's own chrome defaults to light, so the
        # two are deliberately out of step until the user hits the toggle.
        self.set_preview_theme("dark")

    def set_preview_theme(self, mode: str) -> None:
        """
        Sets Theme.mode inside the preview's QML engine.

        The Shadcn Theme is a QML singleton, so it has no Python-side handle:
        the only supported way to touch it is from QML that imports the module.
        A bare engine.evaluate("Theme.mode = ...") cannot work, because a raw
        JS evaluation has no imports in scope and fails silently.

        Args:
            mode: "light" or "dark". Anything else is ignored.

        Side effects: replaces the previous theme-holder object.
        """
        if mode not in ("light", "dark"):
            logging.warning("Ignoring unknown preview theme %r", mode)
            return
        engine = self.quick_widget.engine()
        engine.rootContext().setContextProperty("_previewThemeMode", mode)
        component = QQmlComponent(engine)
        component.setData(
            b"import QtQuick\n"
            b"import Shadcn 1.0\n"
            b"QtObject { Component.onCompleted: Theme.mode = _previewThemeMode }",
            QUrl(),
        )
        obj = component.create()
        if component.isError() or obj is None:
            for err in component.errors():
                logging.warning("Preview theme could not be applied: %s", err.toString())
            return
        self._theme_holder = obj

    def set_target_resolution(self, width: int, height: int) -> None:
        """
        Changes the emulated panel resolution and re-lays out the preview.

        The QQuickWidget is resized to this resolution and scaled to fit the
        bezel, so the app is composed against the geometry it will actually meet
        on the device: a screen authored for 1280x800 shown in a 800x480 frame
        must look wrong here, because it will look wrong there.

        Args:
            width: horizontal resolution in pixels, > 0.
            height: vertical resolution in pixels, > 0.
        """
        if width <= 0 or height <= 0:
            logging.warning("Ignoring invalid resolution %sx%s", width, height)
            return
        self.target_width = int(width)
        self.target_height = int(height)
        self.update_geometry()
        self.update()

        # A native preview renders at a fixed size in its own process, so a new
        # panel size means restarting it. The QML preview needs no equivalent:
        # its root object is resized in place by the QQuickWidget.
        if self.native_preview.is_running() and self.manifest is not None:
            self.native_preview.start(
                self.bundle_dir, self.manifest, self.target_width, self.target_height
            )

    def resolution_text(self) -> str:
        """Returns the current resolution formatted for the caption strip."""
        return f"{self.target_width} x {self.target_height}"

    def get_led_state(self) -> int:
        return self._led_state
        
    def set_led_state(self, state: int):
        self._led_state = state
        self.update()
        
    ledState = Property(int, get_led_state, set_led_state)

    def load_bundle(self, bundle_dir: str, manifest: dict):
        self.bundle_dir = bundle_dir
        self.manifest = manifest
        
        screen = manifest.get("screen", {})
        self.target_width = screen.get("width", 1280)
        self.target_height = screen.get("height", 800)
        
        expected_tags = manifest.get("tags_required", [])

        # The engine binds UDP 5001, and only one socket may hold it. Creating a
        # fresh engine per bundle meant the second load - which happens on any
        # normal run, because the window restores the last bundle at startup and
        # then the caller loads one - failed to bind and silently dropped the
        # preview to offline for the rest of the session. Build it once, then
        # reuse it and just re-seed the expected tags.
        if self.tag_engine is None:
            self.tag_engine = TagEngine(
                expected_tags,
                rx_port=5001,
                daemon_host="127.0.0.1",
                daemon_port=5000,
                parent=self,
            )
        else:
            for tag in expected_tags:
                # Seed any tag this bundle declares that the previous one did
                # not, so its bindings resolve before the first frame arrives.
                if self.tag_engine.tagMap().value(tag.replace(".", "_")) is None:
                    self.tag_engine.tagMap().insert(tag.replace(".", "_"), None)
                    self.tag_engine.tagMap().insert(tag, None)

        ctx = self.quick_widget.rootContext()
        ctx.setContextProperty("Tags", self.tag_engine.tagMap())
        ctx.setContextProperty("Bus", self.tag_engine)
        
        entry = manifest.get("entry", "main.qml")
        runtime = manifest.get("runtime", "qml")

        if runtime == "python":
            # A Qt Widgets app owns its own QApplication and window, so it
            # cannot be composited into the QQuickWidget. It is rendered
            # offscreen in a child process at the target resolution instead,
            # and its frames are painted into the bezel -- see
            # native_preview.py. If that cannot run here (a PySide2 bundle with
            # no PySide2 interpreter on this machine, an app that never opens a
            # window), _on_preview_failed puts the explanatory card back.
            self._show_native_placeholder(manifest, entry)
            self.native_preview.start(
                bundle_dir, manifest, self.target_width, self.target_height
            )
        else:
            self.native_preview.stop()
            self._show_qml_view()
            entry_path = os.path.join(bundle_dir, entry)
            self.quick_widget.setSource(QUrl.fromLocalFile(entry_path))

        self.update_geometry()

    # ------------------------------------------------------- native preview

    def _show_qml_view(self) -> None:
        """Make the QML view the visible one and drop any held frame."""
        self._native_frame = None
        self.native_view.hide()
        self.native_view.clear()
        self.quick_widget.show()

    def _show_native_placeholder(self, manifest: dict, entry: str) -> None:
        """Show the explanatory card in the bezel.

        Args:
            manifest: the loaded manifest, for the app name and version.
            entry:    the manifest entry path, shown so the user can see which
                      file the preview is trying to run.

        Used while the child process starts, and left in place if it cannot.
        """
        ctx = self.quick_widget.rootContext()
        ctx.setContextProperty("appName", manifest.get("name", "application"))
        ctx.setContextProperty("appEntry", entry)
        ctx.setContextProperty("appVersion", manifest.get("version", ""))
        placeholder = os.path.join(
            os.path.dirname(__file__), "resources", "native_preview.qml"
        )
        self.quick_widget.setSource(QUrl.fromLocalFile(placeholder))
        self._show_qml_view()

    def _on_preview_frame(self, image) -> None:
        """Paint one rendered frame from the running application.

        Args:
            image: a QImage at the target panel resolution.

        Side effects: hides the QML view the first time a frame arrives, so the
        explanatory card is replaced the moment there is something real to show.
        """
        self._native_frame = image
        if self.native_view.isHidden():
            self.quick_widget.hide()
            self.native_view.show()
        self._rescale_native_frame()

    def _rescale_native_frame(self) -> None:
        """Fit the held frame to the screen rect, preserving aspect ratio.

        The frame is rendered at the target resolution and the bezel's screen
        area is whatever fits on this monitor, so it is scaled on display for
        the same reason the QML preview is: what is being judged is the layout
        at the panel's geometry, not its pixel size on a laptop.
        """
        if self._native_frame is None:
            return
        rect = self.native_view.size()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.native_view.setPixmap(
            QPixmap.fromImage(self._native_frame).scaled(
                rect, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

    def _on_preview_failed(self, message: str) -> None:
        """Fall back to the explanatory card and surface the reason.

        Args:
            message: why the preview could not run, already written for a user.
        """
        logging.warning("%s", message)
        self.previewMessage.emit(message)
        self._show_qml_view()

    def stop_preview(self) -> None:
        """Terminate any running native preview.

        Called when the window closes and before a deploy, so a child process
        rendering frames never outlives the thing that was showing them.
        """
        self.native_preview.stop()

    def _on_preview_stopped(self) -> None:
        """The application exited; keep the last frame rather than blanking.

        A closed app is not the same as a broken one, and a bezel that goes
        empty the moment the process ends tells the user less than the final
        frame does.
        """
        logging.info("Native preview stopped")

    def update_geometry(self):
        """Update QQuickWidget geometry inside the bezel"""
        # Calculate aspect ratio
        bezel_margin_pct = 0.095
        
        # the screen area is target_width x target_height
        # bezel adds margins on all sides.
        # Let W_s = screen width, H_s = screen height
        # Bezel width W_b = W_s / (1 - 2*0.095) = W_s / 0.81
        bezel_aspect = (self.target_width / 0.81) / (self.target_height + 2 * (self.target_width / 0.81 * 0.095))
        
        # Fit into available space
        w = self.width()
        h = self.height()
        
        if w == 0 or h == 0:
            return
            
        if w / h > bezel_aspect:
            # constrained by height
            bh = h * 0.9  # 90% of available height
            bw = bh * bezel_aspect
        else:
            # constrained by width
            bw = w * 0.9
            bh = bw / bezel_aspect
            
        bx = (w - bw) / 2
        by = (h - bh) / 2
        
        margin = bw * bezel_margin_pct
        
        sx = bx + margin
        sy = by + margin
        sw = bw - 2 * margin
        sh = bh - 2 * margin
        
        self.quick_widget.setGeometry(int(sx), int(sy), int(sw), int(sh))
        # The native frame view occupies the same screen rect; only one of the
        # two is ever visible.
        self.native_view.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self._rescale_native_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_geometry()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Calculate bezel bounds
        w = self.width()
        h = self.height()
        
        if w == 0 or h == 0:
            return
            
        bezel_margin_pct = 0.095
        bezel_aspect = (self.target_width / 0.81) / (self.target_height + 2 * (self.target_width / 0.81 * 0.095))
        
        if w / h > bezel_aspect:
            bh = h * 0.9
            bw = bh * bezel_aspect
        else:
            bw = w * 0.9
            bh = bw / bezel_aspect
            
        bx = (w - bw) / 2
        by = (h - bh) / 2
        
        # Soft drop shadow (simplified)
        shadow_rect = QRectF(bx + 4, by + 4, bw, bh)
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(shadow_rect, 28, 28)
        painter.fillPath(shadow_path, QColor(0, 0, 0, 40))
        
        # Bezel: near-black (#050505), radius ~28
        bezel_rect = QRectF(bx, by, bw, bh)
        bezel_path = QPainterPath()
        bezel_path.addRoundedRect(bezel_rect, 28, 28)
        painter.fillPath(bezel_path, QColor("#050505"))
        
        # LED: top-left corner
        # ~10px diameter, position it inside the bezel margin
        margin = bw * bezel_margin_pct
        led_radius = 5.0
        # Place roughly in the center of the top margin area (x: left margin / 2, y: top margin / 2)
        led_cx = bx + margin / 2
        led_cy = by + margin / 2
        
        led_colors = [
            QColor("#1a3d7c"), # idle
            QColor("#3b82f6"), # link up (brighter blue)
            QColor("#f59e0b"), # deploying (amber)
            QColor("#ef4444")  # fault (red)
        ]
        
        painter.setBrush(led_colors[self._led_state])
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(led_cx, led_cy), led_radius, led_radius)

from PySide6.QtCore import QPointF
