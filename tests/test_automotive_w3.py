"""The interactive Automotive widgets act on the panel bus.

A drive-mode selector that looks right but never writes the mode, or a tile
that fires on telemetry, is decoration. These tests load a generated page
against a stub Bus (the harness tests/test_designer_actions.py uses) and
operate the controls the way a finger would.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, Property, QPointF, Qt, Signal, Slot, QUrl  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.generators.qml_generator import QmlGenerator  # noqa: E402
from designer.model import DesignerAction, DesignerBinding, DesignerProject, DesignerWidget  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402


def by_id(item, qml_id):
    return QQmlEngine.contextForObject(item).contextProperty(qml_id)


class StubBus(QObject):
    historyVersionChanged = Signal()
    activeAlarmsChanged = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []
        self.values = {}

    @Slot(str, "QVariant")
    def write(self, tag, value):
        self.calls.append(("write", tag, value))

    @Slot(str, int)
    def pulse(self, tag, ms):
        self.calls.append(("pulse", tag, ms))

    @Slot(str)
    def acknowledge(self, tag):
        self.calls.append(("acknowledge", tag))

    @Slot(str, result="QVariant")
    @Slot(str, "QVariant", result="QVariant")
    def value(self, name, fallback=None):
        return self.values.get(name, fallback)

    @Slot(str, int, result="QVariantList")
    def history(self, tag, count):
        return []

    historyVersion = Property(int, lambda self: 0, notify=historyVersionChanged)
    activeAlarms = Property("QVariantList", lambda self: [], notify=activeAlarmsChanged)


class AutomotiveControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def load(self, widgets, values=None):
        project = DesignerProject(name="auto")
        project.pages[0].widgets = widgets
        root_dir = tempfile.mkdtemp()
        paths = QmlGenerator(default_registry()).write(project, os.path.join(root_dir, "generated"), root_dir)
        engine = QQmlEngine()
        engine.addImportPath(str(REPO_ROOT / "ui" / "qml"))
        bus = StubBus()
        bus.values.update(values or {})
        engine.rootContext().setContextProperty("Bus", bus)
        engine.rootContext().setContextProperty("Tags", QObject())
        component = QQmlComponent(engine, paths[0])
        item = component.create()
        self.assertEqual([e.toString() for e in component.errors()], [])
        self._keep = (engine, bus, component, item)
        return item, bus

    def test_drive_mode_taps_wrap_and_write_but_telemetry_does_not(self):
        item, bus = self.load([DesignerWidget(
            "ShDriveMode", "mode", {"x": 0, "y": 0, "width": 180, "height": 56},
            {"modes": "ECO,COMFORT,SPORT", "currentIndex": 2},
            bindings={"currentIndex": DesignerBinding("mb.mode")},
            actions={"activated": DesignerAction("write", "mb.mode")})], values={"mb.mode": 2})
        mode = by_id(item, "mode")
        self.assertEqual(mode.property("currentIndex"), 2)   # the tag, not the literal
        mode.step(1)                       # what the right chevron's tap calls
        self.assertEqual(mode.property("currentIndex"), 0)   # SPORT wraps to ECO
        self.assertEqual(bus.calls, [("write", "mb.mode", 0)])
        mode.step(-1)
        self.assertEqual(mode.property("currentIndex"), 2)
        self.assertEqual(bus.calls[-1], ("write", "mb.mode", 2))
        bus.calls.clear()
        # A value arriving from the tag is a read, never a write.
        mode.setProperty("currentIndex", 1)
        self.assertEqual(mode.property("_currentMode"), "COMFORT")
        self.assertEqual(bus.calls, [])

    def test_disabled_drive_mode_ignores_taps(self):
        item, bus = self.load([DesignerWidget(
            "ShDriveMode", "mode", {"x": 0, "y": 0, "width": 180, "height": 56},
            {"modes": "A,B", "currentIndex": 0, "enabled": False},
            actions={"activated": DesignerAction("write", "mb.mode")})])
        mode = by_id(item, "mode")
        # The MouseAreas are disabled; a synthetic click on one must not land.
        area = mode.findChildren(QObject)
        areas = [child for child in area if child.metaObject().className().startswith("QQuickMouseArea")]
        self.assertEqual(len(areas), 2)
        self.assertTrue(all(not a.property("enabled") for a in areas))

    def test_icon_tile_click_pulses_and_active_glows(self):
        item, bus = self.load([DesignerWidget(
            "ShIconTile", "bt", {"x": 0, "y": 0, "width": 100, "height": 110},
            {"icon": "phone", "label": "BT"},
            actions={"clicked": DesignerAction("pulse", "do.bt", ms=200)})])
        tile = by_id(item, "bt")
        tile.clicked.emit()
        self.assertEqual(bus.calls, [("pulse", "do.bt", 200)])

    def _render(self, props, size=(48, 48)):
        view = QQuickView()
        view.engine().addImportPath(str(REPO_ROOT / "ui" / "qml"))
        body = "\n".join(QmlGenerator(default_registry())._widget(
            DesignerWidget("ShTelltale", "t", {"x": 4, "y": 4, "width": size[0], "height": size[1]}, props), 1))
        component = QQmlComponent(view.engine())
        component.setData(("import QtQuick 2.15\nimport Shadcn 1.0\nRectangle { width: %d; height: %d; "
                           "color: \"#0b0f16\"\n%s\n}" % (size[0] + 8, size[1] + 8, body)).encode(),
                          QUrl.fromLocalFile(str(REPO_ROOT / "tests" / "w3.qml")))
        self.assertEqual([e.toString() for e in component.errors()], [])
        obj = component.create()
        view.setContent(QUrl(), component, obj)
        view.show(); QTest.qWait(80)
        image = view.grabWindow()
        lamp = obj.childItems()[0] if obj.childItems() else None
        view.close(); view.deleteLater(); self.app.processEvents()
        return image, lamp

    @staticmethod
    def _bright(image):
        return sum(1 for y in range(image.height()) for x in range(image.width())
                   if image.pixelColor(x, y).lightness() > 120)

    def test_unlit_telltale_is_a_dim_ghost(self):
        lit, _ = self._render({"icon": "bulb", "color": "amber", "lit": True})
        unlit, _ = self._render({"icon": "bulb", "color": "amber", "lit": False})
        self.assertGreater(self._bright(lit), self._bright(unlit) * 2)

    def test_blink_runs_its_timer_only_while_lit(self):
        _, lamp = self._render({"icon": "bulb", "color": "amber", "lit": True, "blink": True})
        self.assertTrue(lamp.property("blinking"))
        _, lamp = self._render({"icon": "bulb", "color": "amber", "lit": False, "blink": True})
        self.assertFalse(lamp.property("blinking"))


if __name__ == "__main__":
    unittest.main()
