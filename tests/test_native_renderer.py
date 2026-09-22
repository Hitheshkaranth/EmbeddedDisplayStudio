"""designer/preview/native_renderer.py -- previews by hmi-ui (W2 gate).

FROZEN: the tests below are the minimum W2 must pass; add more below them,
never change these. They need the Linux hmi-ui binary
(native/hmi-ui/out/hmi-ui, built by native/hmi-ui/build.sh) -- run in WSL.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.canvas.qml_previews import preview_key  # noqa: E402
from designer.model import DesignerBinding, DesignerPage, DesignerProject, DesignerWidget  # noqa: E402
from designer.preview import NativeRenderer, find_hmi_ui, kit_dir  # noqa: E402
from designer.preview.native_renderer import page_key  # noqa: E402

BIN = REPO_ROOT / "native" / "hmi-ui" / "out" / "hmi-ui"


def _wait_ready(renderer, key, timeout_ms=15000):
    loop = QEventLoop()
    got = []
    renderer.ready.connect(lambda k: (got.append(k), loop.quit()) if k == key else None)
    renderer.failed.connect(lambda k, m: (got.append("FAILED:" + m), loop.quit()) if k == key else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return got


def _gauge():
    return DesignerWidget(type="ShGauge", id="gauge1", geometry={"x": 40, "y": 40, "width": 180, "height": 180},
                          properties={"label": "RPM", "value": 137},
                          bindings={"value": DesignerBinding(tag="engine.rpm")})


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class NativeRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_find_and_kit(self):
        self.assertEqual(os.path.abspath(find_hmi_ui()), str(BIN))
        self.assertTrue(os.path.isdir(os.path.join(kit_dir(), "fonts")))
        self.assertTrue(os.path.isdir(os.path.join(kit_dir(), "icons")))
        os.environ["HMI_UI_BIN"] = "/nonexistent/hmi-ui"
        try:
            self.assertIsNone(find_hmi_ui())
        finally:
            del os.environ["HMI_UI_BIN"]

    def test_widget_render_async_and_cached(self):
        r = NativeRenderer()
        self.assertTrue(r.available)
        w = _gauge()
        key = preview_key(w, 180, 180, "dark", 1.0)
        self.assertIsNone(r.image_for(w, 180, 180, "dark"))
        self.assertEqual(_wait_ready(r, key), [key])
        image = r.image_for(w, 180, 180, "dark")
        self.assertIsInstance(image, QImage)
        self.assertEqual((image.width(), image.height()), (180, 180))
        # Something was drawn: not a flat image.
        colours = {image.pixel(x, y) for x in range(0, 180, 9) for y in range(0, 180, 9)}
        self.assertGreater(len(colours), 3)
        r.shutdown()

    def test_widget_render_scaled(self):
        r = NativeRenderer()
        w = _gauge()
        key = preview_key(w, 180, 180, "dark", 0.5)
        r.image_for(w, 180, 180, "dark", 0.5)
        self.assertEqual(_wait_ready(r, key), [key])
        image = r.image_for(w, 180, 180, "dark", 0.5)
        self.assertEqual((image.width(), image.height()), (90, 90))
        r.shutdown()

    def test_container_children_render(self):
        r = NativeRenderer()
        card = DesignerWidget(type="ShCard", id="card1", geometry={"x": 0, "y": 0, "width": 300, "height": 200},
                              children=[DesignerWidget(type="Text", id="t", geometry={"x": 20, "y": 20, "width": 200, "height": 30},
                                                       properties={"text": "hello", "color": "#ffffff"})])
        self.assertIsInstance(r.render_widget_sync(card, 300, 200, "dark"), QImage)
        r.shutdown()

    def test_page_render_sync_and_async(self):
        r = NativeRenderer()
        project = DesignerProject(name="demo", pages=[DesignerPage("main", "Main", widgets=[_gauge()])])
        image = r.render_page_sync(project, project.pages[0], "dark")
        self.assertIsInstance(image, QImage)
        self.assertEqual((image.width(), image.height()), (project.screen.width, project.screen.height))
        key = page_key(project, project.pages[0], "dark", 1.0)
        self.assertIsNone(r.page_image_for(project, project.pages[0], "dark"))
        self.assertEqual(_wait_ready(r, key), [key])
        self.assertIsInstance(r.page_image_for(project, project.pages[0], "dark"), QImage)
        # The key follows the content.
        project.pages[0].widgets[0].properties["label"] = "Speed"
        self.assertNotEqual(page_key(project, project.pages[0], "dark", 1.0), key)
        r.shutdown()

    def test_disabled_and_clear(self):
        r = NativeRenderer()
        r.enabled = False
        self.assertIsNone(r.image_for(_gauge(), 180, 180, "dark"))
        r.enabled = True
        r.clear()
        r.shutdown()

    def test_missing_binary(self):
        r = NativeRenderer(binary="/nonexistent/hmi-ui")
        self.assertFalse(r.available)
        self.assertIsNone(r.image_for(_gauge(), 180, 180, "dark"))
        self.assertIsNone(r.render_page_sync(DesignerProject(), DesignerProject().pages[0], "dark"))


if __name__ == "__main__":
    unittest.main()
