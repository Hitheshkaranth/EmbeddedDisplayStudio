"""A separate window that runs the generated app so it can be operated.

The Display Console shows a design inside the bezel, scaled to whatever room
the Studio has left for it. That is the right place to judge composition
and the wrong place to *use* the screen: buttons are small, the drive-mode
chevrons need a steady hand, and the window is shared with the console.

LivePreviewWindow is the same generated QML in its own top-level window at
the panel's real resolution, on the same TagEngine the Display Console
uses, so whatever feeds the Studio -- Tag Lab, the simulator, a connected
panel's relay -- feeds this window too, and a control's write goes out the
same way. Zoom is a plain scale on the loaded item; the app itself is always
laid out at the target size, as on the glass.
"""
import os

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtQml import QQmlComponent
from PySide6.QtWidgets import QComboBox, QLabel, QMainWindow, QScrollArea, QSizePolicy, QToolBar, QWidget

from schema.manifest import preview_entry

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ZOOMS = ((0.5, "50 %"), (0.75, "75 %"), (1.0, "100 %"), (1.5, "150 %"))

# Hosts the app at its real size and scales the picture, not the layout.
HOST_QML = """
import QtQuick 2.15
Item {
    id: host
    property real zoom: 1.0
    property int targetWidth: 1280
    property int targetHeight: 800
    property url entry
    width: Math.round(targetWidth * zoom)
    height: Math.round(targetHeight * zoom)
    Rectangle { anchors.fill: parent; color: "#101418" }
    Loader {
        id: app
        source: host.entry
        width: host.targetWidth
        height: host.targetHeight
        transformOrigin: Item.TopLeft
        scale: host.zoom
        onLoaded: {
            // The generated App.qml sizes itself; pin it to the glass anyway.
            if (item) { item.width = host.targetWidth; item.height = host.targetHeight }
        }
    }
}
"""


class LivePreviewWindow(QMainWindow):
    """The generated app, live, in a window of its own.

    Signals:
        closed(): the window went away; the Studio drops its reference so the
            next Preview opens a fresh one.
    """

    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live preview")
        self.setWindowFlag(Qt.Window, True)
        self._entry = ""
        self._tag_engine = None

        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.SizeViewToRootObject)
        self.quick.setClearColor(QColor("#101418"))
        self.quick.engine().addImportPath(os.path.join(REPO_ROOT, "ui", "qml"))

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.quick)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setStyleSheet("QScrollArea { background: #0b0d12; border: 0; }")
        self.setCentralWidget(self.scroll)

        bar = QToolBar("Preview")
        bar.setMovable(False)
        self.addToolBar(bar)
        self.title = QLabel("No app loaded")
        bar.addWidget(self.title)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        bar.addWidget(QLabel("Zoom "))
        self.zoom = QComboBox()
        for factor, label in ZOOMS:
            self.zoom.addItem(label, factor)
        self.zoom.setCurrentIndex(2)
        self.zoom.currentIndexChanged.connect(self._apply_zoom)
        bar.addWidget(self.zoom)
        self.feed = QLabel("")
        self.feed.setContentsMargins(12, 0, 4, 0)
        bar.addWidget(self.feed)

    # ---------------------------------------------------------------- API

    def load(self, bundle_dir, manifest, tag_engine, expose):
        """Show ``manifest['entry']`` from ``bundle_dir`` on ``tag_engine``.

        Args:
            bundle_dir: the bundle on disk.
            manifest: its parsed manifest (entry, screen, name).
            tag_engine: the Studio's live TagEngine, or None for a static view.
            expose: ``hmi_loader.tagengine.expose_to_qml`` (passed in so this
                module does not repeat the device panel's import dance).
        """
        screen = manifest.get("screen", {})
        width = int(screen.get("width", 1280))
        height = int(screen.get("height", 800))
        self._entry = os.path.join(bundle_dir, preview_entry(manifest))
        self._tag_engine = tag_engine
        name = manifest.get("name") or os.path.basename(bundle_dir)
        self.title.setText(f"<b>{name}</b> &nbsp; {width}×{height}")
        self.feed.setText("live tags" if tag_engine is not None else "no tag feed")

        engine = self.quick.engine()
        if tag_engine is not None:
            expose(engine, engine.rootContext(), tag_engine)
        # A regenerated design lands at the same path; the engine would hand
        # back the cached component otherwise.
        self.quick.setSource(QUrl())
        engine.clearComponentCache()
        self.quick.setContent(QUrl(), *self._host_object(width, height))
        self._apply_zoom()
        self.resize(min(width + 24, 1600), min(height + 80, 1000))

    def _host_object(self, width, height):
        """Build the host item; returns (component, item), both kept alive."""
        component = QQmlComponent(self.quick.engine())
        component.setData(HOST_QML.encode(), QUrl.fromLocalFile(os.path.join(REPO_ROOT, "live_preview_host.qml")))
        host = component.create()
        if host is None:
            raise RuntimeError("; ".join(e.toString() for e in component.errors()))
        host.setProperty("targetWidth", width)
        host.setProperty("targetHeight", height)
        host.setProperty("entry", QUrl.fromLocalFile(self._entry))
        self._component, self._host = component, host
        return component, host

    def zoom_factor(self):
        return float(self.zoom.currentData())

    def _apply_zoom(self, *_):
        host = getattr(self, "_host", None)
        if host is not None:
            host.setProperty("zoom", self.zoom_factor())
            self.quick.resize(int(host.property("width")), int(host.property("height")))

    def app_item(self):
        """The loaded app's root item, or None (tests operate its controls)."""
        host = getattr(self, "_host", None)
        if host is None:
            return None
        loader = next((c for c in host.childItems() if c.metaObject().className().startswith("QQuickLoader")), None)
        return loader.property("item") if loader is not None else None

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
