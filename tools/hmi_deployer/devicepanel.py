"""
tools/hmi_deployer/devicepanel.py
Layer: 3 (Host Deployer)
Purpose: The centred hardware mock-up of the panel with a live QML preview.
(CONTRACT section 10).
"""
import os
import sys
import logging
from PySide6.QtCore import (
    Qt, QUrl, QRectF, QPropertyAnimation, Property, QRect, Signal, QTimer, QEvent
)
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
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

# Below this the bezel stops being a preview at all, at any scaling. The
# adaptive floor never goes under it.
ABSOLUTE_MIN_PANEL_WIDTH = 380
ABSOLUTE_MIN_PANEL_HEIGHT = 280



def panel_floor(available=None):
    """Return the (width, height) floor for the preview on this screen.

    Args:
        available: the usable screen rectangle, or None to ask the application.

    Returns:
        The preferred floor, reduced to a share of the screen when the screen
        is too small to grant it. Never returns less than a size the bezel can
        still be read at.
    """
    if available is None:
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
    if available is None:
        return MIN_PANEL_WIDTH, MIN_PANEL_HEIGHT
    return (
        min(MIN_PANEL_WIDTH, max(ABSOLUTE_MIN_PANEL_WIDTH, int(available.width() * 0.45))),
        min(MIN_PANEL_HEIGHT, max(ABSOLUTE_MIN_PANEL_HEIGHT, int(available.height() * 0.55))),
    )


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
        # Floor on the preview. The bezel is aspect-locked, so the widget can
        # still be given more room than this, but never less - the splitter is
        # prevented from squeezing the panel down to an unreadable sliver.
        #
        # Taken against the screen, not fixed. Display scaling shrinks the
        # desktop in the units Qt lays out in: a 1920x1080 screen is 1280x720
        # at 150%, and a floor of 720x520 there is most of the desktop, so the
        # window could not fit and the pane was clipped instead. The floor
        # exists to keep the preview judgeable; one that stops the window
        # fitting the screen defeats itself. Everything is drawn larger at that
        # scale anyway, so a smaller floor is the same physical size.
        self.setMinimumSize(*panel_floor())
        self.setObjectName("devicePanel")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

        self.manifest = None
        self.bundle_dir = None
        self.target_width = 1280
        self.target_height = 800
        # Physical diagonal of the selected panel, in inches. Decides how large
        # the bezel draws relative to the other presets; see _physical_scale.
        self.target_inches = 10.1
        # The same FlyVi wordmark used on the reference hardware bezel. It is
        # painted on the lower-right bezel margin, never over the active LCD.
        logo_path = os.path.join(
            os.path.dirname(__file__), "resources", "flyvi_logo_full.png"
        )
        self._bezel_logo = QPixmap(logo_path)
        
        # LED state: 0 = idle/disconnected, 1 = link up, 2 = deploying, 3 = fault
        self._led_state = 0
        
        # Setup QQuickWidget for the screen
        self.quick_widget = QQuickWidget(self)
        self.quick_widget.setResizeMode(QQuickWidget.SizeRootObjectToView)
        # The device framebuffer itself is a dark grey; the area *around* the
        # bezel stays transparent so it inherits the Studio canvas.
        self.quick_widget.setClearColor(QColor("#343434"))
        
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
        self.native_view.setStyleSheet("background: #343434;")
        self.native_view.setScaledContents(False)
        # A preview you can operate needs the events a widget only gets when
        # it can be focused and is told to track the mouse between presses.
        self.native_view.setMouseTracking(True)
        self.native_view.setFocusPolicy(Qt.StrongFocus)
        self.native_view.setCursor(Qt.PointingHandCursor)
        self.native_view.hide()

        # QML is composed at the real panel dimensions offscreen, then its
        # framebuffer is fitted into the physical screen opening below. This
        # prevents the desktop preview from reflowing the root object to the
        # bezel's on-screen size and preserves device clipping exactly.
        self.qml_view = QLabel(self)
        self.qml_view.setAlignment(Qt.AlignCenter)
        self.qml_view.setStyleSheet("background: #343434;")
        self.qml_view.setScaledContents(False)
        self.qml_view.hide()
        self._qml_frame = None
        self._qml_capture_timer = QTimer(self)
        self._qml_capture_timer.setInterval(33)
        self._qml_capture_timer.timeout.connect(self._capture_qml_frame)

        self.native_preview = NativePreview(self)
        self.native_preview.frameReady.connect(self._on_preview_frame)
        self.native_preview.failed.connect(self._on_preview_failed)
        self.native_preview.stopped.connect(self._on_preview_stopped)
        # Fetching a package can take tens of seconds. Forwarded to the
        # console so the pause reads as work rather than as a hang.
        self.native_preview.installing.connect(self.previewMessage.emit)
        # Installed only now: the filter reads native_preview, and widget
        # calls as ordinary as setCursor() deliver events into it, so an
        # earlier install fires before there is anything to read.
        self.native_view.installEventFilter(self)

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

    def set_target_resolution(self, width: int, height: int,
                              inches: float = 0.0) -> None:
        """
        Changes the emulated panel resolution and re-lays out the preview.

        The QQuickWidget is resized to this resolution and scaled to fit the
        bezel, so the app is composed against the geometry it will actually meet
        on the device: a screen authored for 1280x800 shown in a 800x480 frame
        must look wrong here, because it will look wrong there.

        Args:
            width: horizontal resolution in pixels, > 0.
            height: vertical resolution in pixels, > 0.
            inches: physical diagonal of the panel. 0 keeps the current value,
                which is what a manifest-driven size wants: a bundle declares
                its resolution but says nothing about the glass it runs on.
        """
        if width <= 0 or height <= 0:
            logging.warning("Ignoring invalid resolution %sx%s", width, height)
            return
        self.target_width = int(width)
        self.target_height = int(height)
        if inches > 0:
            self.target_inches = float(inches)
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
        """Returns the caption under the bezel: diagonal and resolution.

        The diagonal is included because three of the presets are 1280x800 and
        differ only in physical size, so a resolution-only caption could not
        say which one you were looking at.
        """
        return (f'{self.target_inches:g}" - {self.target_width} x '
                f'{self.target_height}')

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
                # The Studio owns the senders too, so it can be told where to
                # send. A stale process holding 5001 used to leave every
                # preview showing dead tags, silently, for the whole session.
                allow_any_port=True,
                daemon_host="127.0.0.1",
                daemon_port=5000,
                parent=self,
            )
            # A live tag feed is what separates this preview from a
            # screenshot, so losing it is worth a line in the console rather
            # than only in stderr.
            port = getattr(self.tag_engine, "rx_port", 0)
            if not port:
                self.previewMessage.emit(
                    "Tags: the telemetry port is held by another process, and "
                    "the preview will show no live values."
                )
            elif port != 5001:
                self.previewMessage.emit(
                    f"Tags: port 5001 was taken; listening on {port} instead."
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
        self.qml_view.show()
        self.quick_widget.show()
        if not self._qml_capture_timer.isActive():
            self._qml_capture_timer.start()

    def _capture_qml_frame(self) -> None:
        """Capture the target-resolution QML framebuffer for the bezel."""
        if self.quick_widget.isHidden() or self.manifest is None:
            return
        image = self.quick_widget.grabFramebuffer()
        if image.isNull():
            return
        self._qml_frame = image
        self._rescale_qml_frame()

    def _rescale_qml_frame(self) -> None:
        """Fit the real panel framebuffer inside the bezel screen opening."""
        if self._qml_frame is None:
            return
        rect = self.qml_view.size()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.qml_view.setPixmap(
            QPixmap.fromImage(self._qml_frame).scaled(
                rect, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )

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
            self.qml_view.hide()
            self.native_view.show()
        self._rescale_native_frame()

    # ------------------------------------------------------------------
    # Touching the preview
    # ------------------------------------------------------------------

    def _panel_pos(self, pos):
        """Map a point on the preview widget to a pixel on the panel.

        Args:
            pos: a QPoint in native_view coordinates.

        Returns:
            (x, y) in the panel's own pixels, or None for a click outside the
            displayed image -- the grey around a letterboxed frame is not part
            of the panel and must not be reported as a touch on its edge.

        The frame is drawn KeepAspectRatio and centred, so undoing the fit is
        the scale and the centring offset taken back off.
        """
        pixmap = self.native_view.pixmap()
        if pixmap is None or pixmap.isNull() or self._native_frame is None:
            return None
        pw, ph = pixmap.width(), pixmap.height()
        if pw <= 0 or ph <= 0:
            return None

        ox = (self.native_view.width() - pw) / 2.0
        oy = (self.native_view.height() - ph) / 2.0
        x = pos.x() - ox
        y = pos.y() - oy
        if x < 0 or y < 0 or x >= pw or y >= ph:
            return None

        return (
            int(x * self._native_frame.width() / pw),
            int(y * self._native_frame.height() / ph),
        )

    def eventFilter(self, watched, event):
        """Forward interaction with the preview to the application behind it.

        The bezel shows a running application, and until now it was a
        photograph of one: the only way to press a button was to deploy first.
        Events are translated to panel coordinates here and sent on; the child
        turns them into Qt events for the widget under the point.
        """
        preview = getattr(self, "native_preview", None)
        if watched is not self.native_view or preview is None or not preview.is_running():
            return super().eventFilter(watched, event)

        kind = event.type()

        if kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                    QEvent.MouseButtonDblClick, QEvent.MouseMove):
            point = self._panel_pos(event.position().toPoint())
            if point is None:
                return False
            if kind == QEvent.MouseButtonPress:
                # Keystrokes should follow the panel once it has been touched.
                self.native_view.setFocus(Qt.MouseFocusReason)
            preview.send_input(
                t={
                    QEvent.MouseButtonPress: "press",
                    QEvent.MouseButtonRelease: "release",
                    QEvent.MouseButtonDblClick: "dblclick",
                    QEvent.MouseMove: "move",
                }[kind],
                x=point[0], y=point[1],
                b=int(event.button().value),
                buttons=int(event.buttons().value),
                mods=int(event.modifiers().value),
            )
            return True

        if kind == QEvent.Wheel:
            point = self._panel_pos(event.position().toPoint())
            if point is None:
                return False
            delta = event.angleDelta()
            preview.send_input(
                t="wheel", x=point[0], y=point[1],
                dx=delta.x(), dy=delta.y(),
                mods=int(event.modifiers().value),
            )
            return True

        if kind in (QEvent.KeyPress, QEvent.KeyRelease):
            preview.send_input(
                t="keypress" if kind == QEvent.KeyPress else "keyrelease",
                key=int(event.key()),
                mods=int(event.modifiers().value),
                text=event.text(),
            )
            return True

        return super().eventFilter(watched, event)

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
        self._qml_capture_timer.stop()

    def _on_preview_stopped(self) -> None:
        """The application exited; keep the last frame rather than blanking.

        A closed app is not the same as a broken one, and a bezel that goes
        empty the moment the process ends tells the user less than the final
        frame does.
        """
        logging.info("Native preview stopped")

    # Bezel margin as a fraction of bezel width (CONTRACT section 10:
    # "uniform bezel margin ~9.5% of bezel width").
    BEZEL_MARGIN_PCT = 0.095

    # The largest panel the tool offers. The preview scales every other panel
    # against this one, so relative physical size is visible at a glance.
    MAX_DIAGONAL_IN = max(inches for _label, inches, _w, _h in PANEL_PRESETS)

    # How small the smallest panel is allowed to render, as a fraction of the
    # pane. Pure physical scaling would draw a 5.0" panel at 5.0/15.6 = 32% of
    # a 15.6" one, which is too small to judge a layout in -- and judging the
    # layout is the entire point. The scale is therefore compressed into
    # [MIN_PHYSICAL_SCALE, 1.0]: a 5" panel still reads as clearly smaller than
    # a 12" one without becoming unusable.
    MIN_PHYSICAL_SCALE = 0.62

    # How much of the pane the bezel fills, before physical scaling. Raised 20%
    # from the original 0.90: the preview is the thing being judged, and it was
    # leaving more of the pane empty than the panel occupied.
    BEZEL_FILL_PCT = 0.9 * 1.2

    # The bezel is centred in the pane, so a fill of 1.0 would put its edge
    # exactly on the pane's. This keeps a sliver of margin at the largest
    # diagonal, where the raised fill would otherwise overrun.
    MAX_BEZEL_FILL_PCT = 0.98

    def _physical_scale(self) -> float:
        """Return how large this panel draws relative to the biggest one.

        Returns:
            A factor in [MIN_PHYSICAL_SCALE, 1.0].

        Without this the diagonal in each preset was decorative: every panel
        rendered at exactly the same on-screen width, so the three 1280x800
        presets (7.0", 10.1", 12.1") were pixel-identical and choosing between
        them changed nothing. Physical size is precisely what separates them,
        and it is what decides whether 14px text is comfortable or unreadable
        on the finished machine.
        """
        if self.target_inches <= 0:
            return 1.0
        raw = min(1.0, self.target_inches / self.MAX_DIAGONAL_IN)
        return self.MIN_PHYSICAL_SCALE + (1.0 - self.MIN_PHYSICAL_SCALE) * raw

    def _bezel_rect(self):
        """Return (bx, by, bw, bh) for the bezel in widget coordinates.

        Returns:
            A tuple of floats, or None when the widget has no area yet.

        Single source of truth for the bezel box. The layout pass and the paint
        pass each carried their own copy of this arithmetic; any change had to
        be made twice and identically or the painted bezel would drift away
        from the screen widget positioned inside it.
        """
        w = self.width()
        h = self.height()
        if w == 0 or h == 0:
            return None

        # Bezel outer aspect: the screen plus a uniform margin on all sides.
        bezel_width_px = self.target_width / (1 - 2 * self.BEZEL_MARGIN_PCT)
        bezel_aspect = bezel_width_px / (
            self.target_height + 2 * (bezel_width_px * self.BEZEL_MARGIN_PCT)
        )

        fill = min(
            self.MAX_BEZEL_FILL_PCT, self.BEZEL_FILL_PCT * self._physical_scale()
        )
        if w / h > bezel_aspect:
            bh = h * fill
            bw = bh * bezel_aspect
        else:
            bw = w * fill
            bh = bw / bezel_aspect

        return (w - bw) / 2, (h - bh) / 2, bw, bh

    def update_geometry(self):
        """Place the screen widgets inside the bezel.

        Side effects: moves quick_widget and native_view, and rescales any held
        native frame to the new screen rect.
        """
        rect = self._bezel_rect()
        if rect is None:
            return
        bx, by, bw, bh = rect
        margin = bw * self.BEZEL_MARGIN_PCT

        sx = bx + margin
        sy = by + margin
        sw = bw - 2 * margin
        sh = bh - 2 * margin

        # Compose QML at the actual device resolution. It remains outside the
        # visible widget bounds; grabFramebuffer() yields the unclipped target
        # framebuffer, which qml_view displays inside the screen opening.
        self.quick_widget.setGeometry(
            -self.target_width - 8, -self.target_height - 8,
            self.target_width, self.target_height,
        )
        # The two visible frame views occupy the physical screen opening; only
        # one is shown at a time.
        self.native_view.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self.qml_view.setGeometry(int(sx), int(sy), int(sw), int(sh))
        self._rescale_native_frame()
        self._rescale_qml_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_geometry()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self._bezel_rect()
        if rect is None:
            return
        bx, by, bw, bh = rect
        
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

        # The same inset defines both the active LCD opening and the hardware
        # logo location in the lower bezel margin.
        margin = bw * self.BEZEL_MARGIN_PCT

        # Brand mark on the lower-right bezel, positioned within the physical
        # margin below the display just as it is on the deployed hardware.
        if not self._bezel_logo.isNull():
            # Keep the whole mark inside the lower bezel margin, including on
            # the smallest selectable panel. This is deliberately tied to the
            # available margin rather than an absolute preview size.
            logo_height = int(max(14, min(46, margin * 0.52)))
            logo = self._bezel_logo.scaledToHeight(
                logo_height, Qt.SmoothTransformation
            )
            logo_x = int(bx + bw - margin * 0.56 - logo.width())
            screen_bottom = by + bh - margin
            logo_y = int(screen_bottom + (margin - logo.height()) / 2)
            painter.drawPixmap(logo_x, logo_y, logo)

        # LED: top-left corner
        # ~10px diameter, position it inside the bezel margin
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
