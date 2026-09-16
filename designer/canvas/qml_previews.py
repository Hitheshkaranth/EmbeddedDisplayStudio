"""The Designer canvas showing the real QML, not a painted imitation.

widget_previews.py draws each component with QPainter so a layout can be
judged by eye. Those painters are approximations, and the gap shows: the
panel renders the kit's gradients, glows and glyph metrics, the canvas
renders a sketch of them. The Studio should not look worse than the glass.

QmlPreviewRenderer renders a widget's generated QML in a hidden QQuickView
and hands back the image, so the canvas item can paint exactly what the
panel will. Renders are asynchronous (a Canvas element paints a frame
after it is created) and cached by content, so a page settles within a
few frames and a widget is only re-rendered when its properties, size or
theme change. Anything that fails to render falls back to the painter.
"""
import copy
import json
import os
from collections import OrderedDict

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Property, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView

from designer.generators.qml_generator import _CAR_JS

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_LIMIT = 400
# A Canvas-based instrument needs one event-loop turn to paint after it is
# created; grabbing straight away yields the frame before its first paint.
SETTLE_MS = 60
MAX_ATTEMPTS = 8

# What a bound expression sees when no panel is connected: its own fallback.
# ``Bus.value("mb.rpm", 0)`` reads 0, ``Bus.history(...)`` is empty.
# The canvas is a still: the clock is frozen at a moment 26 s into the drive
# cycle (mid-cruise, fourth gear) so sim.car.* widgets show a car in motion.
_SIM_BLOCK = """
    property real _t: 26.3
    property real _ts: 0.7
    function osc(lo, hi, phase) { return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(_t + phase)) }
    function osc_slow(lo, hi, phase) { return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(_ts + phase)) }
""" + _CAR_JS


class _StillBus(QObject):
    """Bus with no feed: every read returns its fallback, writes go nowhere."""
    historyVersionChanged = Signal()
    activeAlarmsChanged = Signal()

    @Slot(str, "QVariant")
    def write(self, tag, value):
        pass

    @Slot(str, int)
    def pulse(self, tag, ms):
        pass

    @Slot(str)
    def acknowledge(self, tag):
        pass

    @Slot(str, result="QVariant")
    @Slot(str, "QVariant", result="QVariant")
    def value(self, name, fallback=None):
        return fallback

    @Slot(str, int, result="QVariantList")
    def history(self, tag, count):
        return []

    historyVersion = Property(int, lambda self: 0, notify=historyVersionChanged)
    activeAlarms = Property("QVariantList", lambda self: [], notify=activeAlarmsChanged)


def preview_key(widget, width, height, theme, scale=1.0):
    """The cache key: everything that changes the picture."""
    return json.dumps([widget.type, round(width), round(height), theme, round(scale, 2),
                       widget.properties,
                       {k: [b.tag, b.format, b.multiplier, b.offset, b.warning, b.critical]
                        for k, b in widget.bindings.items()},
                       [c.id for c in widget.children]], sort_keys=True, default=str)


class QmlPreviewRenderer(QObject):
    """Renders widgets one at a time in a hidden QQuickView, cached by content.

    Signals:
        ready(str): a render for this key has landed; repaint what uses it.
    """

    ready = Signal(str)

    def __init__(self, generator, parent=None):
        super().__init__(parent)
        self.generator = generator
        self._cache = OrderedDict()
        self._queue = OrderedDict()      # key -> (widget, width, height, theme, scale)
        self._current = None
        self._keep = None
        self.enabled = True
        self._view = None
        self._bus = _StillBus(self)

    # ----------------------------------------------------------------- API

    def image_for(self, widget, width, height, theme, scale=1.0):
        """The cached render, or None -- in which case one is scheduled and
        ``ready`` fires with the key when it lands."""
        if not self.enabled or width < 2 or height < 2:
            return None
        key = preview_key(widget, width, height, theme, scale)
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            return image
        if key not in self._queue and key != self._current:
            self._queue[key] = (widget, width, height, theme, scale)
            if self._current is None:
                QTimer.singleShot(0, self._pump)
        return None

    def clear(self):
        self._cache.clear()
        self._queue.clear()

    # ------------------------------------------------------------ pipeline

    def _ensure_view(self):
        if self._view is None:
            view = QQuickView()
            view.setFlags(Qt.Tool | Qt.FramelessWindowHint)
            view.setColor(Qt.transparent)
            view.engine().addImportPath(os.path.join(REPO_ROOT, "ui", "qml"))
            view.engine().rootContext().setContextProperty("Bus", self._bus)
            view.engine().rootContext().setContextProperty("Tags", QObject(self))
            self._view = view
        return self._view

    def _source(self, widget, width, height, theme, scale):
        """The widget at its size inside a root scaled for the canvas zoom.

        ``root`` keeps the name the generated expressions use (sim clocks,
        navigateRequested); the inner stage carries the zoom so a canvas at
        200 % gets a render with real pixels rather than a blown-up one.
        """
        # A still of the design, not of the feed: a bound property shows the
        # sample value the inspector holds (as the sketch painters did)
        # rather than the Bus fallback, so a gauge on the canvas reads 137,
        # not 0, until a panel is connected.
        still = copy.copy(widget)
        still.bindings = {}
        still.actions = {}
        body = "\n".join(self.generator._widget(still, 2))
        w, h = int(width), int(height)
        return "\n".join([
            "import QtQuick 2.15", "import QtQuick.Controls 2.15", "import QtQuick.Layouts 1.15",
            "import Shadcn 1.0",
            "Item {", "    id: root",
            f"    width: {max(1, int(w * scale))}", f"    height: {max(1, int(h * scale))}",
            "    signal navigateRequested(string page)",
            f'    Component.onCompleted: Theme.mode = "{theme}"',
            _SIM_BLOCK,
            "    Item {", "        id: stage", f"        width: {w}", f"        height: {h}",
            f"        scale: {scale}", "        transformOrigin: Item.TopLeft",
            body, "    }", "}", ""])


    def _pump(self):
        if self._current is not None or not self._queue:
            return
        key, (widget, width, height, theme, scale) = self._queue.popitem(last=False)
        self._current = key
        try:
            view = self._ensure_view()
            engine = view.engine()
            component = QQmlComponent(engine)
            component.setData(self._source(widget, width, height, theme, scale).encode(),
                              QUrl.fromLocalFile(os.path.join(REPO_ROOT, "designer", "canvas", "preview.qml")))
            item = component.create() if not component.isError() else None
            if item is None:
                self._finish(key, None)
                return
            # The widget is generated at its canvas geometry; render it at 0,0.
            stage = item.childItems()[-1] if item.childItems() else None
            for child in (stage.childItems() if stage is not None else []):
                child.setX(0)
                child.setY(0)
            view.setContent(QUrl(), component, item)
            view.resize(max(1, int(width * scale)), max(1, int(height * scale)))
            self._keep = (component, item)
            QTimer.singleShot(SETTLE_MS, lambda: self._grab(key, scale, 0))
        except Exception:      # noqa: BLE001 -- a preview must never take the canvas down
            self._finish(key, None)

    def _grab(self, key, scale, attempt):
        """Grab once every Image in the tree has loaded (an ShIcon decodes
        its SVG asynchronously; the first render in a fresh engine also
        loads the icon registry), or after MAX_ATTEMPTS regardless."""
        image = None
        try:
            item = self._keep[1] if self._keep else None
            if attempt < MAX_ATTEMPTS and item is not None and self._images_loading(item):
                QTimer.singleShot(SETTLE_MS, lambda: self._grab(key, scale, attempt + 1))
                return
            image = self._view.grabWindow()
            if image.isNull():
                image = None
        except Exception:      # noqa: BLE001
            image = None
        self._finish(key, image)

    @staticmethod
    def _images_loading(item):
        for child in item.findChildren(QObject):
            if child.metaObject().className().startswith("QQuickImage"):
                progress = child.property("progress")
                source = child.property("source")
                if source and source.toString() and progress is not None and progress < 1.0:
                    return True
        return False

    def _finish(self, key, image):
        if image is not None:
            self._cache[key] = image
            while len(self._cache) > CACHE_LIMIT:
                self._cache.popitem(last=False)
        else:
            # Remember the failure so the painter fallback is used without
            # re-queueing on every repaint.
            self._cache[key] = QImage()
        self._current = None
        self._keep = None
        self.ready.emit(key)
        if self._queue:
            QTimer.singleShot(0, self._pump)
