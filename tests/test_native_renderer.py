"""designer/preview/native_renderer.py -- previews by hmi-ui.

They need the Linux hmi-ui binary
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


# ---------------------------------------------------------------- further tests

def _wait_signal(renderer, key, timeout_ms=15000):
    """Both outcomes for a key: ('ready',) or ('failed', message)."""
    loop = QEventLoop()
    got = []
    renderer.ready.connect(lambda k: (got.append(("ready",)), loop.quit()) if k == key else None)
    renderer.failed.connect(lambda k, m: (got.append(("failed", m)), loop.quit()) if k == key else None)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return got


@unittest.skipUnless(BIN.exists(), "needs the Linux hmi-ui binary (native/hmi-ui/build.sh)")
class NativeRendererBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_failed_render_emits_failed_and_caches_null(self):
        # A binary that exists, runs and exits non-zero without a PNG.
        false = "/bin/false" if os.path.isfile("/bin/false") else "/usr/bin/false"
        r = NativeRenderer(binary=false)
        self.assertTrue(r.available)
        w = _gauge()
        key = preview_key(w, 180, 180, "dark", 1.0)
        self.assertIsNone(r.image_for(w, 180, 180, "dark"))
        got = _wait_signal(r, key)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0][0], "failed")
        self.assertIn("exited with 1", got[0][1])
        # The failure is remembered: the caller gets a null image and nothing
        # is queued again on the next repaint.
        image = r.image_for(w, 180, 180, "dark")
        self.assertIsInstance(image, QImage)
        self.assertTrue(image.isNull())
        self.assertEqual(len(r._queue), 0)
        self.assertEqual(len(r._running), 0)
        self.assertIsNone(r.render_widget_sync(w, 180, 180, "dark"))
        r.shutdown()

    def test_queue_coalesces_duplicate_keys(self):
        r = NativeRenderer()
        r.parallel = 1
        w = _gauge()
        others = [DesignerWidget(type="ShGauge", id=f"g{i}", geometry={"x": 0, "y": 0, "width": 120, "height": 120},
                                 properties={"label": f"G{i}", "value": i}) for i in range(4)]
        key = preview_key(w, 180, 180, "dark", 1.0)
        # One render takes the only slot; the rest wait in the queue.
        r.image_for(others[0], 120, 120, "dark")
        for other in others[1:]:
            r.image_for(other, 120, 120, "dark")
        r.image_for(w, 180, 180, "dark")
        r.image_for(w, 180, 180, "dark")
        r.image_for(w, 180, 180, "dark")
        # Nothing has started yet (the pump waits for the event loop): five
        # distinct keys are queued, the repeated one once and at the front.
        self.assertEqual(list(r._queue).count(key), 1)
        self.assertEqual(next(iter(r._queue)), key)
        self.assertEqual(len(r._queue), 5)
        # Then everything lands exactly once.
        seen = []
        loop = QEventLoop()
        r.ready.connect(lambda k: (seen.append(k), loop.quit() if len(seen) == 5 else None))
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        self.assertEqual(len(seen), 5)
        self.assertEqual(seen.count(key), 1)
        self.assertEqual(len(r._running), 0)
        r.shutdown()

    def test_shutdown_kills_running_processes(self):
        r = NativeRenderer()
        r.parallel = 2
        widgets = [DesignerWidget(type="ShGauge", id=f"k{i}", geometry={"x": 0, "y": 0, "width": 200, "height": 200},
                                  properties={"label": f"K{i}", "value": i}) for i in range(6)]
        for w in widgets:
            r.image_for(w, 200, 200, "dark")
        # Let the pump start the first processes.
        loop = QEventLoop()
        QTimer.singleShot(50, loop.quit)
        loop.exec()
        self.assertGreater(len(r._running), 0)
        tmp_dirs = [job.tmp for job in r._running.values()]
        landed = []
        r.ready.connect(landed.append)
        r.failed.connect(lambda k, m: landed.append(k))
        r.shutdown()
        self.assertEqual(len(r._running), 0)
        self.assertEqual(len(r._queue), 0)
        for tmp in tmp_dirs:
            self.assertFalse(os.path.exists(tmp))
        # Killed renders are discarded, not reported.
        QTimer.singleShot(300, loop.quit)
        loop.exec()
        self.assertEqual(landed, [])
        # The renderer is still usable after a shutdown.
        self.assertIsInstance(r.render_widget_sync(widgets[0], 200, 200, "dark"), QImage)
        r.shutdown()

    def test_theme_light_renders_differently(self):
        r = NativeRenderer()
        w = _gauge()
        dark = r.render_widget_sync(w, 180, 180, "dark")
        light = r.render_widget_sync(w, 180, 180, "light")
        self.assertIsInstance(dark, QImage)
        self.assertIsInstance(light, QImage)
        self.assertNotEqual(preview_key(w, 180, 180, "dark"), preview_key(w, 180, 180, "light"))
        self.assertNotEqual(dark, light)
        r.shutdown()

    def test_clear_discards_running_renders(self):
        r = NativeRenderer()
        w = _gauge()
        key = preview_key(w, 180, 180, "dark", 1.0)
        r.image_for(w, 180, 180, "dark")
        # Let the child start (a render can finish in tens of milliseconds
        # once the kit is local, so do not wait for it to be *running*).
        self.app.processEvents()
        self.assertTrue(key in r._running or key in r._queue or key in r._cache)
        r.clear()
        got = _wait_signal(r, key, timeout_ms=3000)
        self.assertEqual(got, [])
        self.assertEqual(len(r._running), 0)
        self.assertIsNone(r.image_for(w, 180, 180, "dark"))
        self.assertEqual(_wait_signal(r, key), [("ready",)])
        r.shutdown()

    def test_page_key_is_stable_and_scale_aware(self):
        project = DesignerProject(name="demo", pages=[DesignerPage("main", "Main", widgets=[_gauge()])])
        page = project.pages[0]
        self.assertEqual(page_key(project, page, "dark"), page_key(project, page, "dark", 1.0))
        self.assertNotEqual(page_key(project, page, "dark"), page_key(project, page, "dark", 0.5))
        self.assertNotEqual(page_key(project, page, "dark"), page_key(project, page, "light"))
        project.screen.background = "#000000"
        self.assertNotEqual(page_key(project, page, "dark"), page_key(DesignerProject(name="demo", pages=[page]), page, "dark"))


if __name__ == "__main__":
    unittest.main()
