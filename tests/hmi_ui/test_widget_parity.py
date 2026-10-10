"""
tests/hmi_ui/test_widget_parity.py
The Qt-free kit against the QML kit, widget by widget.

For every implemented kit type (wave 1, WAVE below) the widget is rendered
twice at its registered default size with its registry defaults, dark theme:
  * by the QML kit through PySide6 (offscreen, software scene graph, Inter),
    exactly as the Studio previews and the Qt loader draw it;
  * by native/hmi-ui --render-widget, headless.
The two images are compared (mean absolute channel difference and the share
of pixels differing by > 64). A render passes when it is at least twice as
close to the QML picture as an empty background is -- a self-calibrating
"most of the ink is in the right place" gate; the side-by-side PNGs written
to swarm/qc/ui-parity/<Type>.png (QML | hmi-ui | diff) are what a human
signs off on. Placeholder renders (the runtime logs "not implemented") are
reported as skips, so the gate is honest about stubs.

    QT_QPA_PLATFORM=offscreen HMI_UI_BIN=native/hmi-ui/out/hmi-ui \\
        python -m unittest tests.hmi_ui.test_widget_parity -v
    HMI_UI_TYPES=ShClusterGauge,ShButton restricts the run.
"""
import copy
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
# swarm/qc/ui-parity next to the main checkout (a worktree lives one level
# deeper, under swarm/, so walk up until a sibling "swarm" directory exists).
def _qc_dir():
    here = ROOT
    for _ in range(4):
        parent = os.path.dirname(here)
        if os.path.isdir(os.path.join(parent, "swarm")):
            return os.path.join(parent, "swarm", "qc", "ui-parity")
        here = parent
    return os.path.join(ROOT, "..", "swarm", "qc", "ui-parity")


OUT_DIR = os.environ.get("HMI_UI_QC_DIR") or _qc_dir()
# The native panel binary, built by native/hmi-ui. Only searched for here, when
# HMI_UI_BIN is unset: Windows emits win64/hmi-ui.exe, Linux a flat out/hmi-ui,
# both directly under native/hmi-ui/out.
if "HMI_UI_BIN" in os.environ:
    BIN = os.environ["HMI_UI_BIN"]
elif os.name == "nt":
    BIN = os.path.join(ROOT, "native", "hmi-ui", "out", "win64", "hmi-ui.exe")
else:
    BIN = os.path.join(ROOT, "native", "hmi-ui", "out", "hmi-ui")
BACKGROUND = "#101318"

# Every Designer type (kit_schema.json); stubs report as skips.
WAVE = ["Column", "Grid", "Image", "Item", "Rectangle", "Row", "ShAlarmTable", "ShAlert", "ShAnalogDisplay", "ShAnnunciator", "ShAttitude", "ShAutoLevel", "ShAutoReadout", "ShButton", "ShCard", "ShCheckbox", "ShClusterGauge", "ShCompass", "ShDataField", "ShDriveMode", "ShEngineBar", "ShEngineGauge", "ShFlightDirector", "ShFuelQuantity", "ShGauge", "ShGearIndicator", "ShIconTile", "ShInput", "ShNumDisplay", "ShNumInput", "ShProgress", "ShSegmentBar", "ShSelect", "ShSlider", "ShStatDot", "ShTabs", "ShTape", "ShTelltale", "ShToggle", "ShTrendChart", "ShTripInfo", "ShTurnCoordinator", "ShVSI", "ShValueTile", "ShVehicleStatus", "Text",
        "ShSpeedArc", "ShTractionBar", "ShStationLine", "ShTrainConsist", "ShStatusCard",
        # Compared at its defaults: no source, so both kits draw the shared
        # placeholder. A playing GIF is timing-dependent; test_widgets.c and
        # tests/test_animated_image.py check the frames instead.
        "ShAnimatedImage",
        # A SCADA reading row; at its defaults (no trend) label, box and digits.
        "ShProcessValue",
        # Dashboard pieces: a KPI tile (defaults: title and value, no icon or
        # bar) and a status row (lamp, label, RUNNING badge).
        "ShKpiTile", "ShStatusRow"]


# Style options compared with them set (registry defaults plus these), at the
# type's default size: the header band and gradients, the glow (whose part
# outside the box is off the picture; its rounded corners are not) and the
# bevel. Named <Type>-<sample> in the results and in swarm/qc/ui-parity.
STYLE_SAMPLES = [
    ("ShCard", "header", {"headerHeight": 30, "color": "#161b22", "borderColor": "#2d3742",
                          "radius": 6}),
    ("ShCard", "gradient", {"gradient": True, "headerHeight": 28, "headerColor": "#2a3442"}),
    ("ShButton", "gradient", {"variant": "secondary", "backgroundColor": "#2a3038", "gradient": True}),
    ("ShButton", "activeTab", {"text": "FURNACE", "variant": "secondary", "backgroundColor": "#1f2a24",
                               "gradient": True, "glowColor": "#22c55e", "textColor": "#22c55e",
                               "borderColor": "#22c55e", "borderWidth": 1}),
    ("ShAnnunciator", "litColorGlow", {"text": "RUNNING", "litColor": "#22d34a", "glow": True}),
    ("ShAnnunciator", "litColorUnlit", {"text": "RUNNING", "litColor": "#22d34a", "lit": False}),
    ("ShProcessValue", "bevel", {"label": "Hot Blast Temp", "value": 1185, "unit": "\u00b0C",
                                 "trend": True, "bevel": True}),
    # The neon instrument look (a haul-truck cockpit picture): thick glowing
    # gradient arcs, solid glowing bars. An optional fourth element is the
    # size to compare at instead of the type's default.
    ("ShClusterGauge", "neon", {"style": "neon", "accentColor": "#ff8a1f", "value": 1.6,
                                "maximumValue": 3, "majorStep": 0.5, "redlineFrom": 2.5, "readout": "",
                                "decimals": 1, "caption": "RPM", "readoutUnit": "x1000"}),
    ("ShClusterGauge", "neonGradient", {"style": "neon", "accentColor": "#ffd23f", "accentColor2": "#ff3b1f",
                                        "value": 342, "maximumValue": 400, "majorStep": 50,
                                        "redlineFrom": 400, "readout": "342", "readoutUnit": "t",
                                        "caption": "PAYLOAD", "label": "400 t max"}, (300, 300)),
    ("ShClusterGauge", "neonRedline", {"style": "neon", "value": 7.6, "readout": "", "decimals": 1}),
    ("ShSpeedArc", "neon", {"style": "neon", "outerColor": "#2f8bff", "innerColor": "#1d4ed8", "value": 32,
                            "maximumValue": 60, "unit": "km/h"}, (260, 260)),
    ("ShSegmentBar", "solid", {"style": "solid", "barColor": "#3ee05a", "value": 78, "label": "FUEL"},
     (300, 70)),
    ("ShSegmentBar", "solidLow", {"style": "solid", "value": 12}),
    ("ShEngineBar", "glowRow", {"orientation": "horizontal", "glow": True, "barColor": "#ff3b3b",
                                "value": 82, "label": "Coolant", "units": "\u00b0C"}, (300, 28)),
    ("ShEngineBar", "glow", {"glow": True}),
    # Industrial dashboard pieces (a cement-kiln control picture): a KPI tile
    # with icon, subtitle and progress bar; status rows in each state; the
    # multi-series trend with x labels; the alarm table and the event log
    # showing their sample rows.
    ("ShKpiTile", "full", {"icon": "gauge", "title": "Production Rate", "value": "3,015", "unit": "tpd",
                           "subtitle": "Target 3,200 tpd", "progress": 94, "progressText": "94 %"}),
    ("ShKpiTile", "small", {"title": "Kiln Speed", "value": 3.2, "decimals": 2, "unit": "rpm",
                            "subtitle": "SP 3.20 rpm", "progress": 100, "barColor": "#3ee05a"}, (180, 64)),
    ("ShStatusRow", "warn", {"label": "Main Burner", "status": "WARNING", "state": "warn"}),
    ("ShStatusRow", "fault", {"label": "ID Fan", "status": "TRIPPED", "state": "fault"}),
    ("ShStatusRow", "idle", {"label": "Thrust Roller", "status": "NORMAL", "state": "idle"}),
    ("ShTrendChart", "series", {"series": "Kiln Outlet|#ff3b3b|1150;Kiln Inlet|#ff9f1c|880;Zone 3|#ffd23f|800;"
                                          "Zone 2|#3ee05a|580;Zone 1|#22b8ff|440",
                                "minValue": 0, "maxValue": 1400, "unit": "°C",
                                "xLabels": "12:30,13:00,13:30,14:00,14:30"}, (560, 200)),
    ("ShAlarmTable", "table", {"title": "Active Alarms (3)", "headerColor": "#d32222", "showCount": False,
                               "columns": "Time,Tag,Description,Priority,Status",
                               "sampleRows": "14:28:12|KILN-TEMP-HH|Kiln outlet temperature high|HIGH|ACTIVE;"
                                             "14:25:40|COAL-FLOW-LL|Coal feed rate low|MEDIUM|ACTIVE;"
                                             "14:22:18|IDF-VFD-TRIP|ID Fan VFD trip|HIGH|ACKED"}, (860, 150)),
    ("ShAlarmTable", "events", {"title": "Recent Events", "headerColor": "#1f2a38", "showCount": False,
                                "columns": "Time,Description",
                                "sampleRows": "14:31:05|Kiln speed setpoint changed to 3.20 rpm;"
                                              "14:30:11|Coal feed rate setpoint changed to 22 tph;"
                                              "14:18:22|Main burner started;14:15:03|Cooler fan 3 started;"
                                              "14:10:02|Kiln in Auto mode"}, (550, 150)),
]


# Compared nowhere at their defaults, for a reason given in the results: an
# Image with no file is a framed placeholder on the panel (hmi-ui; the
# Designer canvas draws one too), and a design-time aid QML has no reason to
# draw -- its blank QML picture leaves nothing to compare against.
PANEL_PLACEHOLDER = {"Image"}


# Widgets that are almost entirely small text: glyph rasterisation alone
# keeps them above the relative bar although the pictures match (verified by
# eye in swarm/qc/ui-parity). They pass at 0.8 x blank / 1.0 x blank.
TEXT_HEAVY = {"ShTripInfo", "ShDataField", "ShTabs"}


def _selected():
    sel = os.environ.get("HMI_UI_TYPES", "").strip()
    return [t for t in sel.split(",") if t] if sel else WAVE


class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from designer.palette.widget_registry import default_registry
        from designer.generators.qml_generator import QmlGenerator
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.generator = QmlGenerator(cls.registry)
        os.makedirs(OUT_DIR, exist_ok=True)

    # -- renders ---------------------------------------------------------------

    def _qml_render(self, definition, props):
        from PySide6.QtCore import QUrl, qInstallMessageHandler
        from PySide6.QtGui import QImage
        from PySide6.QtQml import QQmlComponent
        from PySide6.QtQuick import QQuickView
        from PySide6.QtTest import QTest
        from designer.model import DesignerWidget
        w, h = definition.default_width, definition.default_height
        widget = DesignerWidget(definition.type, "sample", {"x": 0, "y": 0, "width": w, "height": h}, props)
        body = "\n".join(self.generator._widget(widget, 1))
        source = ("import QtQuick 2.15\nimport QtQuick.Controls 2.15\nimport Shadcn 1.0\n"
                  f"Rectangle {{ width: {w}; height: {h}; color: \"{BACKGROUND}\"\n"
                  "Component.onCompleted: Theme.mode = \"dark\"\n"
                  f"{body}\n}}")
        msgs = []
        handler = qInstallMessageHandler(lambda _t, _c, m: msgs.append(m))
        try:
            view = QQuickView()
            view.engine().addImportPath(os.path.join(ROOT, "ui", "qml"))
            component = QQmlComponent(view.engine())
            component.setData(source.encode(), QUrl.fromLocalFile(os.path.join(ROOT, "tests", "ui", "parity.qml")))
            self.assertFalse(component.errors(), [e.toString() for e in component.errors()])
            obj = component.create()
            view.setContent(QUrl(), component, obj)
            view.resize(w, h)
            view.show()
            QTest.qWait(250)
            image = view.grabWindow().convertToFormat(QImage.Format_RGB32)
            view.close()
            self.app.processEvents()
        finally:
            qInstallMessageHandler(handler)
        return image

    def _ui_render(self, definition, props):
        from PySide6.QtGui import QImage
        w, h = definition.default_width, definition.default_height
        out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        cmd = [BIN, "--render-widget", definition.type, "--headless", out, "--size", f"{w}x{h}",
               "--props", json.dumps(props), "--kit", os.path.join(ROOT, "ui", "qml", "Shadcn")]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        image = QImage(out).convertToFormat(QImage.Format_RGB32)
        os.unlink(out)
        return image, "not implemented" in proc.stdout

    # -- metrics ---------------------------------------------------------------

    @staticmethod
    def _diff(a, b):
        from PySide6.QtGui import QImage, qRgb
        assert a.size() == b.size(), (a.size(), b.size())
        total = 0
        big = 0
        n = a.width() * a.height()
        diff = QImage(a.size(), QImage.Format_RGB32)
        for y in range(a.height()):
            for x in range(a.width()):
                pa, pb = a.pixel(x, y), b.pixel(x, y)
                dr = abs(((pa >> 16) & 255) - ((pb >> 16) & 255))
                dg = abs(((pa >> 8) & 255) - ((pb >> 8) & 255))
                db = abs((pa & 255) - (pb & 255))
                m = max(dr, dg, db)
                total += dr + dg + db
                if m > 64:
                    big += 1
                    diff.setPixel(x, y, qRgb(255, 0, 0))
                else:
                    diff.setPixel(x, y, qRgb(m * 3, m * 3, 0))
        return total / (3.0 * n), big / n, diff

    @staticmethod
    def _blank(like):
        from PySide6.QtGui import QImage, QColor
        img = QImage(like.size(), QImage.Format_RGB32)
        img.fill(QColor(BACKGROUND))
        return img

    @staticmethod
    def _triptych(qml, ui, diff, path):
        from PySide6.QtGui import QImage, QPainter, QColor
        gap = 8
        out = QImage(qml.width() * 3 + gap * 2, qml.height(), QImage.Format_RGB32)
        out.fill(QColor("#444444"))
        p = QPainter(out)
        p.drawImage(0, 0, qml)
        p.drawImage(qml.width() + gap, 0, ui)
        p.drawImage(qml.width() * 2 + gap * 2, 0, diff)
        p.end()
        out.save(path)

    # -- the test --------------------------------------------------------------

    def _compare(self, name, definition, props, results):
        qml = self._qml_render(definition, props)
        ui, stub = self._ui_render(definition, props)
        mean, frac, diff = self._diff(qml, ui)
        blank_mean, blank_frac, _ = self._diff(qml, self._blank(qml))
        self._triptych(qml, ui, diff, os.path.join(OUT_DIR, f"{name}.png"))
        passed = (mean <= blank_mean * 0.5 and frac <= blank_frac * 0.5) or \
                 (blank_mean >= 4.0 and mean <= 10.0 and frac <= 0.06)
        verdict = "STUB" if stub else ("ok" if passed else "FAIL")
        results.append(f"{name:16s} mean {mean:6.2f} (blank {blank_mean:6.2f})  >64: {frac:6.3f} (blank {blank_frac:6.3f})  {verdict}")
        self.assertFalse(stub, f"{name}: placeholder render")
        self.assertTrue(passed, f"{name}: mean diff {mean:.2f} vs blank {blank_mean:.2f}; "
                                f"{frac:.3f} of pixels differ vs blank {blank_frac:.3f}")

    def test_style_samples_match_qml(self):
        self.assertTrue(os.path.exists(BIN), f"no hmi-ui binary at {BIN} (build native/hmi-ui first)")
        results = []
        self.addCleanup(lambda: sys.stderr.write(
            "\nparity (QML vs hmi-ui, dark, style options set):\n" + "\n".join(results) + "\n"))
        selected = set(_selected())
        for type_name, sample, overrides, *size in STYLE_SAMPLES:
            if os.environ.get("HMI_UI_TYPES") and type_name not in selected:
                continue
            definition = self.registry.get(type_name)
            props = copy.deepcopy(definition.defaults)
            if size:
                definition = dataclasses.replace(definition, default_width=size[0][0],
                                                 default_height=size[0][1])
            props.update(overrides)
            with self.subTest(widget=f"{type_name}-{sample}"):
                self._compare(f"{type_name}-{sample}", definition, props, results)

    def test_wave_matches_qml(self):
        self.assertTrue(os.path.exists(BIN), f"no hmi-ui binary at {BIN} (build native/hmi-ui first)")
        results = []
        self.addCleanup(lambda: sys.stderr.write(
            "\nparity (QML vs hmi-ui, dark, defaults):\n" + "\n".join(results)
            + f"\nimages: {os.path.abspath(OUT_DIR)}\n"))
        for type_name in _selected():
            definition = self.registry.get(type_name)
            self.assertIsNotNone(definition, type_name)
            props = copy.deepcopy(definition.defaults)
            if type_name in PANEL_PLACEHOLDER and not str(props.get("source") or "").strip():
                results.append(f"{type_name:16s} not compared: a panel-only placeholder without a file")
                continue
            with self.subTest(widget=type_name):
                qml = self._qml_render(definition, props)
                ui, stub = self._ui_render(definition, props)
                mean, frac, diff = self._diff(qml, ui)
                blank_mean, blank_frac, _ = self._diff(qml, self._blank(qml))
                self._triptych(qml, ui, diff, os.path.join(OUT_DIR, f"{type_name}.png"))
                # Relative criterion, with an absolute floor for tiny text-only
                # widgets where glyph rasterisation alone exceeds half the blank.
                # The absolute floor is for glyph antialiasing on text-heavy
                # pictures; a nearly blank QML picture (blank mean < 4) gets no floor.
                passed = (mean <= blank_mean * 0.5 and frac <= blank_frac * 0.5) or                          (blank_mean >= 4.0 and mean <= 10.0 and frac <= 0.06)
                if type_name in TEXT_HEAVY:
                    passed = mean <= blank_mean * 0.8 and frac <= blank_frac * 1.0
                verdict = "STUB" if stub else ("ok" if passed else "FAIL")
                results.append(f"{type_name:16s} mean {mean:6.2f} (blank {blank_mean:6.2f})  >64: {frac:6.3f} (blank {blank_frac:6.3f})  {verdict}")
                if stub:
                    self.skipTest(f"{type_name} not implemented (placeholder)")
                self.assertTrue(passed, f"{type_name}: mean diff {mean:.2f} vs blank {blank_mean:.2f}; "
                                        f"{frac:.3f} of pixels differ vs blank {blank_frac:.3f}")


if __name__ == "__main__":
    unittest.main()
