"""
tests/ui/test_widget_parity.py
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
        python -m unittest tests.ui.test_widget_parity -v
    HMI_UI_TYPES=ShClusterGauge,ShButton restricts the run.
"""
import copy
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
BIN = os.environ.get("HMI_UI_BIN", os.path.join(ROOT, "native", "hmi-ui", "out", "hmi-ui"))
BACKGROUND = "#101318"

# Wave 1: everything the engine-dashboard demo needs, plus the faces with
# exact drawing specs. Wave 2 adds the rest of the 46 types.
WAVE = ["Text", "Image", "Rectangle", "ShButton", "ShLabel", "ShStatDot", "ShSegmentBar", "ShTripInfo",
        "ShAutoReadout", "ShNumDisplay", "ShValueTile", "ShCard", "ShProgress",
        "ShClusterGauge", "ShAutoLevel", "ShEngineGauge", "ShGauge"]


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

    def test_wave_matches_qml(self):
        self.assertTrue(os.path.exists(BIN), f"no hmi-ui binary at {BIN} (build native/hmi-ui first)")
        results = []
        for type_name in _selected():
            definition = self.registry.get(type_name)
            self.assertIsNotNone(definition, type_name)
            props = copy.deepcopy(definition.defaults)
            with self.subTest(widget=type_name):
                qml = self._qml_render(definition, props)
                ui, stub = self._ui_render(definition, props)
                mean, frac, diff = self._diff(qml, ui)
                blank_mean, blank_frac, _ = self._diff(qml, self._blank(qml))
                self._triptych(qml, ui, diff, os.path.join(OUT_DIR, f"{type_name}.png"))
                verdict = "STUB" if stub else ("ok" if mean <= blank_mean * 0.5 and frac <= blank_frac * 0.5 else "FAIL")
                results.append(f"{type_name:16s} mean {mean:6.2f} (blank {blank_mean:6.2f})  >64: {frac:6.3f} (blank {blank_frac:6.3f})  {verdict}")
                if stub:
                    self.skipTest(f"{type_name} not implemented (placeholder)")
                self.assertLessEqual(mean, blank_mean * 0.5, f"{type_name}: mean diff {mean:.2f} vs blank {blank_mean:.2f}")
                self.assertLessEqual(frac, blank_frac * 0.5, f"{type_name}: {frac:.3f} of pixels differ vs blank {blank_frac:.3f}")
        sys.stderr.write("\nparity (QML vs hmi-ui, dark, defaults):\n" + "\n".join(results) + f"\nimages: {os.path.abspath(OUT_DIR)}\n")


if __name__ == "__main__":
    unittest.main()
