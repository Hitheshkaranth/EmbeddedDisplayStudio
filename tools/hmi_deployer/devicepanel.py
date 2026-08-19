"""
tools/hmi_deployer/devicepanel.py
Layer: 3 (Host Deployer)
Purpose: The centred hardware mock-up of the panel with a live QML preview.
(CONTRACT section 10).
"""
import os
import sys
import logging
from PySide6.QtCore import Qt, QUrl, QRectF, QPropertyAnimation, Property, QRect
from PySide6.QtGui import QPainter, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQml import QQmlComponent, QQmlContext

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

class DevicePanel(QWidget):
    """
    Renders the hardware mock-up of the panel.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        
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
        self.tag_engine = TagEngine(expected_tags, rx_port=5001, daemon_host="127.0.0.1", daemon_port=5000, parent=self)
        
        ctx = self.quick_widget.rootContext()
        ctx.setContextProperty("Tags", self.tag_engine.tagMap())
        ctx.setContextProperty("Bus", self.tag_engine)
        
        entry = manifest.get("entry", "main.qml")
        entry_path = os.path.join(bundle_dir, entry)
        self.quick_widget.setSource(QUrl.fromLocalFile(entry_path))
        
        self.update_geometry()

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
