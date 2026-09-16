"""The Automotive widget set keeps its contract: registry, QML, preview, AI.

Every automotive widget must (1) declare in QML exactly the properties the
registry exposes, (2) render in a real QML engine, (3) visibly react to its
bindable properties -- a gauge whose value changes nothing is decoration --
(4) have a canvas preview that reacts the same way, (5) be reachable from the
AI generator by a plain name. Filter with ``-k ShClusterGauge`` while working
on one widget.
"""
import copy
import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QRectF, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from designer.canvas import widget_previews
from designer.generators.qml_generator import QmlGenerator
from designer.model import DesignerWidget
from designer.palette import default_registry
from tools.hmi_deployer.ai_generator import _AI_TYPE_ALIASES

ROOT = Path(__file__).resolve().parent.parent
QML_DIR = ROOT / "ui" / "qml" / "Shadcn"
CATEGORY = "Automotive"

# A second value for each bindable property that must change the picture.
ALTERED = {
    "value": lambda v: (float(v) + 30.0) if float(v) < 50 else float(v) - 30.0,
    "readout": lambda v: "88" if v != "88" else "12",
    "caption": lambda v: "SPORT" if v != "SPORT" else "ECO",
    "gear": lambda v: "R" if v != "R" else "N",
    "modeNumber": lambda v: 7 if v != 7 else 2,
    "currentIndex": lambda v: 0 if v != 0 else 1,
    "lit": lambda v: not v,
    "blink": lambda v: not v,
    "color": lambda v: "red" if v != "red" else "green",
    "row1Value": lambda v: "999" if v != "999" else "1",
    "row2Value": lambda v: "999" if v != "999" else "1",
    "active": lambda v: not v,
    "frontLeft": lambda v: 0.4,
    "frontRight": lambda v: 0.4,
    "rearLeft": lambda v: 0.4,
    "rearRight": lambda v: 0.4,
}


def _qml_properties(widget_type):
    text = (QML_DIR / f"{widget_type}.qml").read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(?:readonly\s+)?property\s+\w+\s+(\w+)\s*:", text, re.M)) | \
        set(re.findall(r"^\s*(?:readonly\s+)?property\s+\w+\s+(\w+)\s*$", text, re.M))


def _qml_signals(widget_type):
    text = (QML_DIR / f"{widget_type}.qml").read_text(encoding="utf-8")
    return set(re.findall(r"^\s*signal\s+(\w+)", text, re.M))


class AutomotiveContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.generator = QmlGenerator(cls.registry)
        cls.definitions = [d for d in cls.registry.definitions() if d.category == CATEGORY]
        assert cls.definitions, "no Automotive widgets registered"

    # -- rendering helpers ---------------------------------------------------

    def _render_qml(self, definition, props, warnings=None):
        """Render one widget; QML warnings (a TypeError inside onPaint, an
        undefined id) land in ``warnings`` when a list is given."""
        sink = warnings if warnings is not None else []
        handler = qInstallMessageHandler(lambda _t, _c, msg: sink.append(msg))
        try:
            return self._render_qml_unguarded(definition, props)
        finally:
            qInstallMessageHandler(handler)

    def _render_qml_unguarded(self, definition, props):
        view = QQuickView()
        view.engine().addImportPath(str(ROOT / "ui" / "qml"))
        widget = DesignerWidget(definition.type, "sample",
                                {"x": 8, "y": 8, "width": definition.default_width,
                                 "height": definition.default_height}, props)
        body = "\n".join(self.generator._widget(widget, 1))
        source = ("import QtQuick 2.15\nimport QtQuick.Controls 2.15\nimport Shadcn 1.0\n"
                  f"Rectangle {{ width: {definition.default_width + 16}; "
                  f"height: {definition.default_height + 16}; color: Theme.background\n{body}\n}}")
        component = QQmlComponent(view.engine())
        component.setData(source.encode(), QUrl.fromLocalFile(str(ROOT / "tests" / "contract.qml")))
        errors = [e.toString() for e in component.errors()]
        self.assertFalse(errors, f"{definition.type} failed to compile: {errors}")
        obj = component.create()
        self.assertIsNotNone(obj, f"{definition.type} failed to instantiate")
        view.setContent(QUrl(), component, obj)
        view.show()
        QTest.qWait(120)
        image = view.grabWindow()
        view.close()
        view.deleteLater()
        self.app.processEvents()
        return image

    def _render_preview(self, definition, props):
        painter_fn = widget_previews.painter_for(definition.type)
        self.assertIsNotNone(painter_fn, f"no preview painter for {definition.type}")
        image = QImage(definition.default_width, definition.default_height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter_fn(painter, QRectF(0, 0, definition.default_width, definition.default_height), props, None)
        painter.end()
        return image

    @staticmethod
    def _differs(a, b):
        if a.size() != b.size():
            return True
        return any(a.pixel(x, y) != b.pixel(x, y)
                   for y in range(0, a.height(), 2) for x in range(0, a.width(), 2))

    @staticmethod
    def _ink_count(image):
        return sum(1 for y in range(0, image.height(), 2) for x in range(0, image.width(), 2)
                   if image.pixelColor(x, y).alpha() > 0)

    # -- contract ------------------------------------------------------------

    def test_qml_declares_exactly_the_registry_properties(self):
        for definition in self.definitions:
            with self.subTest(widget=definition.type):
                declared = _qml_properties(definition.type)
                expected = set(definition.properties) - {"opacity", "visible", "enabled"}
                missing = expected - declared
                self.assertFalse(missing, f"{definition.type}.qml lacks {sorted(missing)}")
                for name in definition.bindable_properties:
                    self.assertIn(name, expected, f"bindable {name} is not a registry property")
                for signal in definition.action_signals:
                    self.assertIn(signal, _qml_signals(definition.type),
                                  f"{definition.type}.qml does not declare signal {signal}")

    def test_every_bindable_property_changes_the_qml_picture(self):
        for definition in self.definitions:
            base = self._render_qml(definition, copy.deepcopy(definition.defaults))
            self.assertFalse(base.isNull())
            for name in definition.bindable_properties:
                with self.subTest(widget=definition.type, prop=name):
                    props = copy.deepcopy(definition.defaults)
                    props[name] = ALTERED[name](props[name])
                    self.assertTrue(self._differs(base, self._render_qml(definition, props)),
                                    f"{definition.type}.{name} = {props[name]!r} changed nothing")

    def test_every_bindable_property_changes_the_preview(self):
        for definition in self.definitions:
            base = self._render_preview(definition, copy.deepcopy(definition.defaults))
            self.assertGreater(self._ink_count(base), 40, f"{definition.type} preview is blank")
            for name in definition.bindable_properties:
                with self.subTest(widget=definition.type, prop=name):
                    props = copy.deepcopy(definition.defaults)
                    props[name] = ALTERED[name](props[name])
                    self.assertTrue(self._differs(base, self._render_preview(definition, props)),
                                    f"preview of {definition.type}.{name} changed nothing")

    def test_previews_are_not_the_placeholder(self):
        """The stub draws the display name in a panel; a real painter draws
        the instrument, which lays down more distinct colours."""
        for definition in self.definitions:
            with self.subTest(widget=definition.type):
                image = self._render_preview(definition, copy.deepcopy(definition.defaults))
                colours = {image.pixel(x, y) for y in range(0, image.height(), 2)
                           for x in range(0, image.width(), 2) if image.pixelColor(x, y).alpha() > 0}
                self.assertGreater(len(colours), 12, f"{definition.type} preview looks like the stub")

    IGNORED_WARNING_PARTS = ("Cannot find font directory", "Qt no longer ships fonts")

    def test_widgets_render_at_the_registered_size_without_warnings(self):
        """A Canvas whose onPaint throws paints nothing and says so only on
        the console; an undefined id likewise. Neither may ship."""
        for definition in self.definitions:
            with self.subTest(widget=definition.type):
                warnings = []
                image = self._render_qml(definition, copy.deepcopy(definition.defaults), warnings)
                self.assertGreater(self._ink_count(image), 40)
                relevant = [w for w in warnings
                            if not any(part in w for part in self.IGNORED_WARNING_PARTS)]
                self.assertEqual(relevant, [], f"{definition.type} logged QML warnings")

    def test_generated_qml_binds_and_acts(self):
        """A bound value reaches Bus.value(); an action signal reaches Bus.write()."""
        for definition in self.definitions:
            with self.subTest(widget=definition.type):
                widget = DesignerWidget(definition.type, "w", {"x": 0, "y": 0, "width": 100, "height": 100},
                                        copy.deepcopy(definition.defaults))
                from designer.model.project import DesignerAction, DesignerBinding
                first = definition.bindable_properties[0]
                widget.bindings[first] = DesignerBinding(tag="mb.speed")
                for signal in definition.action_signals:
                    widget.actions[signal] = DesignerAction(kind="write", tag="do.mode", value=1)
                qml = "\n".join(self.generator._widget(widget, 1))
                self.assertIn('Bus.value("mb.speed"', qml)
                for signal in definition.action_signals:
                    self.assertIn("on" + signal[0].upper() + signal[1:] + ":", qml)
                    self.assertIn('Bus.write("do.mode"', qml)

    def test_ai_can_name_every_widget(self):
        for definition in self.definitions:
            with self.subTest(widget=definition.type):
                self.assertIn(definition.type, _AI_TYPE_ALIASES.values())


if __name__ == "__main__":
    unittest.main()
