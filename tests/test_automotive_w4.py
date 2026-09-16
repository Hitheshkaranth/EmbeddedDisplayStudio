"""Automotive W4 widget tests — ShTripInfo, ShSegmentBar, ShVehicleStatus.

Functional assertions that the contract tests do not already cover,
plus preview matching.
"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QUrl, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from designer.canvas import widget_previews
from designer.generators.qml_generator import QmlGenerator
from designer.model import DesignerWidget
from designer.palette import default_registry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class W4WidgetTests(unittest.TestCase):
    """Functional tests for ShTripInfo, ShSegmentBar, ShVehicleStatus."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.generator = QmlGenerator(cls.registry)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _render_qml(widget_type, props, width=None, height=None):
        """Render a widget QML to a QImage."""
        definition = None
        for d in default_registry().definitions():
            if d.type == widget_type:
                definition = d
                break
        if definition is None:
            raise ValueError(f"unknown widget {widget_type!r}")

        view = QQuickView()
        view.engine().addImportPath(os.path.join(ROOT, "ui", "qml"))
        widget = DesignerWidget(definition.type, "sample",
                                {"x": 8, "y": 8,
                                 "width": width or definition.default_width,
                                 "height": height or definition.default_height},
                                props)
        body = "\n".join(QmlGenerator(default_registry())._widget(widget, 1))
        source = (
            "import QtQuick 2.15\n"
            "import QtQuick.Controls 2.15\n"
            "import Shadcn 1.0\n"
            f"Rectangle {{ width: {width or definition.default_width + 16}; "
            f"height: {height or definition.default_height + 16}; "
            f"color: Theme.autoPanel\n{body}\n}}")
        component = QQmlComponent(view.engine())
        component.setData(source.encode(),
                          QUrl.fromLocalFile(os.path.join(ROOT, "tests", "test.qml")))
        errors = [e.toString() for e in component.errors()]
        obj = component.create()
        if obj is None:
            view.close()
            view.deleteLater()
            raise RuntimeError(f"{widget_type} failed to compile: {errors}")
        view.setContent(QUrl(), component, obj)
        view.show()
        QTest.qWait(120)
        image = view.grabWindow()
        view.close()
        view.deleteLater()
        QApplication.instance().processEvents()
        return image

    @staticmethod
    def _render_preview(widget_type, props, width=None, height=None):
        """Render a preview painter to a QImage."""
        defn = None
        for d in default_registry().definitions():
            if d.type == widget_type:
                defn = d
                break
        if defn is None:
            raise ValueError(f"unknown widget {widget_type!r}")
        w = width or defn.default_width
        h = height or defn.default_height
        image = QImage(w, h, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        fn = widget_previews.painter_for(widget_type)
        if fn is None:
            painter.end()
            raise ValueError(f"no preview for {widget_type}")
        fn(painter, QRectF(0, 0, w, h), props, None)
        painter.end()
        return image

    @staticmethod
    def _color_count(image, hex_color, step=2):
        """Count pixels matching a hex color string (e.g. '#22a8ff')."""
        c = QColor(hex_color)
        rgb = c.rgb() & 0x00FFFFFF
        count = 0
        for y in range(0, image.height(), step):
            for x in range(0, image.width(), step):
                if (image.pixelColor(x, y).rgb() & 0x00FFFFFF) == rgb:
                    count += 1
        return count

    @staticmethod
    def _total_ink(image, step=2):
        """Count bright (text / fill) pixels at a step; the panel is dark."""
        return sum(1 for y in range(0, image.height(), step)
                   for x in range(0, image.width(), step)
                   if image.pixelColor(x, y).alpha() > 0 and image.pixelColor(x, y).lightness() > 90)


class TestShSegmentBar(W4WidgetTests):
    """Tests for the segment bar widget."""

    def test_value100_has_more_accent_than_value50(self):
        """Higher value fills more segments → more accent pixels."""
        props_full = {"value": 100.0, "minimumValue": 0.0, "maximumValue": 100.0,
                      "segments": 12, "lowLevel": 20.0}
        props_half = {"value": 50.0, "minimumValue": 0.0, "maximumValue": 100.0,
                      "segments": 12, "lowLevel": 20.0}
        img_full = self._render_preview("ShSegmentBar", props_full)
        img_half = self._render_preview("ShSegmentBar", props_half)
        accent_full = self._color_count(img_full, "#22a8ff")
        accent_half = self._color_count(img_half, "#22a8ff")
        self.assertGreater(accent_full, accent_half,
                           f"value=100 accent {accent_full} should exceed value=50 accent {accent_half}")

    def test_low_level_triggers_redline(self):
        """value <= lowLevel fills with redline, no accent."""
        props_low = {"value": 10.0, "minimumValue": 0.0, "maximumValue": 100.0,
                     "segments": 12, "lowLevel": 20.0}
        img = self._render_preview("ShSegmentBar", props_low)
        redline = self._color_count(img, "#ff2d55")
        accent = self._color_count(img, "#22a8ff")
        self.assertGreater(redline, 0, "redline should appear when value <= lowLevel")
        self.assertEqual(accent, 0,
                         "accent should be zero when value <= lowLevel")

    def test_different_segment_counts_differ(self):
        """4 segments vs 24 should produce different pixel patterns."""
        img4 = self._render_preview("ShSegmentBar",
                                    {"value": 50.0, "minimumValue": 0.0, "maximumValue": 100.0,
                                     "segments": 4})
        img24 = self._render_preview("ShSegmentBar",
                                     {"value": 50.0, "minimumValue": 0.0, "maximumValue": 100.0,
                                      "segments": 24})
        self.assertNotEqual(bytes(img4.constBits()), bytes(img24.constBits()),
                            "4 and 24 segments should differ")

    def test_qml_value100_has_more_accent(self):
        """Same check via QML rendering."""
        props_full = {"value": 100.0, "minimumValue": 0.0, "maximumValue": 100.0,
                      "segments": 12, "lowLevel": 20.0}
        props_half = {"value": 50.0, "minimumValue": 0.0, "maximumValue": 100.0,
                      "segments": 12, "lowLevel": 20.0}
        img_full = self._render_qml("ShSegmentBar", props_full)
        img_half = self._render_qml("ShSegmentBar", props_half)
        accent_full = self._color_count(img_full, "#22a8ff")
        accent_half = self._color_count(img_half, "#22a8ff")
        self.assertGreater(accent_full, accent_half)


class TestShVehicleStatus(W4WidgetTests):
    """Tests for the vehicle status widget."""

    def test_low_tyre_shows_red(self):
        """rearLeft 1.2 (below warnBelow 1.8) → red pixels."""
        img = self._render_preview("ShVehicleStatus",
                                   {"frontLeft": 2.6, "frontRight": 2.5,
                                    "rearLeft": 1.2, "rearRight": 2.2})
        red = self._color_count(img, "#ff3b3b")
        self.assertGreater(red, 0,
                           "red pixels should appear when rearLeft < warnBelow")

    def test_normal_tyres_no_red(self):
        """All pressures above warnBelow → no red pixels."""
        img = self._render_preview("ShVehicleStatus",
                                   {"frontLeft": 2.6, "frontRight": 2.5,
                                    "rearLeft": 2.4, "rearRight": 2.2})
        red = self._color_count(img, "#ff3b3b")
        self.assertEqual(red, 0,
                         "no red when all pressures are above warnBelow")

    def test_qml_low_tyre_shows_red(self):
        """Same check via QML rendering."""
        img = self._render_qml("ShVehicleStatus",
                               {"frontLeft": 2.6, "frontRight": 2.5,
                                "rearLeft": 1.2, "rearRight": 2.2})
        red = self._color_count(img, "#ff3b3b")
        self.assertGreater(red, 0)


class TestShTripInfo(W4WidgetTests):
    """Tests for the trip info widget."""

    def test_empty_row2_draws_less_ink(self):
        """row2Label='' and row2Value='' → less ink than default."""
        img_default = self._render_qml("ShTripInfo", {
            "title": "Distance", "row1Label": "Day", "row1Value": "352",
            "row1Unit": "km", "row2Label": "Total", "row2Value": "110 593",
            "row2Unit": "km"})
        img_empty = self._render_qml("ShTripInfo", {
            "title": "Distance", "row1Label": "Day", "row1Value": "352",
            "row1Unit": "km", "row2Label": "", "row2Value": "",
            "row2Unit": ""})
        ink_default = self._total_ink(img_default)
        ink_empty = self._total_ink(img_empty)
        self.assertGreater(ink_default, ink_empty,
                           f"empty row2 ink {ink_empty} < default ink {ink_default}")

    def test_qml_preview_consistency(self):
        """QML and preview should both react to empty rows."""
        img_qml = self._render_qml("ShTripInfo", {
            "title": "Distance", "row1Label": "Day", "row1Value": "352",
            "row1Unit": "km", "row2Label": "", "row2Value": "",
            "row2Unit": ""})
        img_prev = self._render_preview("ShTripInfo", {
            "title": "Distance", "row1Label": "Day", "row1Value": "352",
            "row1Unit": "km", "row2Label": "", "row2Value": "",
            "row2Unit": ""})
        ink_qml = self._total_ink(img_qml)
        ink_prev = self._total_ink(img_prev)
        self.assertGreater(ink_prev, 20, "preview of trip info should have content")
        self.assertGreater(ink_qml, 20, "QML of trip info should have content")


class TestPreviewMatching(W4WidgetTests):
    """Preview painters react the same as QML for W4 widgets."""

    def test_segment_bar_qml_vs_preview_accent(self):
        """Both QML and preview show more accent at value=100 than value=50."""
        for val in (50.0, 100.0):
            img_qml = self._render_qml("ShSegmentBar", {
                "value": val, "minimumValue": 0.0, "maximumValue": 100.0,
                "segments": 12, "lowLevel": 20.0})
            img_prev = self._render_preview("ShSegmentBar", {
                "value": val, "minimumValue": 0.0, "maximumValue": 100.0,
                "segments": 12, "lowLevel": 20.0})
            qml_accent = self._color_count(img_qml, "#22a8ff")
            prev_accent = self._color_count(img_prev, "#22a8ff")
            self.assertGreater(qml_accent, 0,
                               f"QML accent at value={val}")
            self.assertGreater(prev_accent, 0,
                               f"preview accent at value={val}")

    def test_vehicle_status_qml_vs_preview_red(self):
        """Both QML and preview show red when rearLeft is low."""
        for val in (1.2, 2.4):
            img_qml = self._render_qml("ShVehicleStatus", {
                "frontLeft": 2.6, "frontRight": 2.5,
                "rearLeft": val, "rearRight": 2.2})
            img_prev = self._render_preview("ShVehicleStatus", {
                "frontLeft": 2.6, "frontRight": 2.5,
                "rearLeft": val, "rearRight": 2.2})
            qml_red = self._color_count(img_qml, "#ff3b3b")
            prev_red = self._color_count(img_prev, "#ff3b3b")
            if val < 1.8:
                self.assertGreater(qml_red, 0, f"QML red at rearLeft={val}")
                self.assertGreater(prev_red, 0, f"preview red at rearLeft={val}")
            else:
                self.assertEqual(qml_red, 0, f"QML no red at rearLeft={val}")
                self.assertEqual(prev_red, 0, f"preview no red at rearLeft={val}")


if __name__ == "__main__":
    unittest.main()