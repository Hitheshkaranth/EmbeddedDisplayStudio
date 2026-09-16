"""The Designer canvas draws each widget with its real QML.

The QPainter sketches in widget_previews.py stay as the fallback; the
renderer must produce a picture for every non-container widget, cache it
by content, and never take the canvas down when a render fails.
"""
import os
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.canvas.qml_previews import QmlPreviewRenderer, preview_key  # noqa: E402
from designer.generators.qml_generator import QmlGenerator  # noqa: E402
from designer.model import DesignerBinding, DesignerWidget  # noqa: E402
from designer.palette import default_registry  # noqa: E402


class QmlPreviewRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.registry = default_registry()
        cls.renderer = QmlPreviewRenderer(QmlGenerator(cls.registry))

    def _wait_for(self, widget, width, height, theme="dark", scale=1.0, timeout=5.0):
        deadline = time.time() + timeout
        image = self.renderer.image_for(widget, width, height, theme, scale)
        while image is None and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
            image = self.renderer.image_for(widget, width, height, theme, scale)
        return image

    def test_every_non_container_widget_renders(self):
        for definition in self.registry.definitions():
            if definition.container or definition.type == "Image":
                continue
            with self.subTest(widget=definition.type):
                widget = DesignerWidget(definition.type, "w", {"x": 0, "y": 0, "width": definition.default_width,
                                                              "height": definition.default_height},
                                        dict(definition.defaults))
                image = self._wait_for(widget, definition.default_width, definition.default_height)
                self.assertIsNotNone(image, "render never landed")
                self.assertFalse(image.isNull(), "render failed; the painter fallback would be used")
                self.assertEqual((image.width(), image.height()),
                                 (definition.default_width, definition.default_height))

    def test_zoom_renders_real_pixels(self):
        definition = self.registry.get("ShClusterGauge")
        widget = DesignerWidget("ShClusterGauge", "g", {"x": 0, "y": 0, "width": 200, "height": 200},
                                dict(definition.defaults))
        image = self._wait_for(widget, 200, 200, scale=2.0)
        self.assertEqual((image.width(), image.height()), (400, 400))

    def test_a_bound_property_shows_its_sample_value_not_the_feed(self):
        definition = self.registry.get("ShClusterGauge")
        props = dict(definition.defaults, readout="137")
        live = DesignerWidget("ShClusterGauge", "g", {"x": 0, "y": 0, "width": 240, "height": 240}, props,
                              {"readout": DesignerBinding("mb.speed")})
        still = DesignerWidget("ShClusterGauge", "g", {"x": 0, "y": 0, "width": 240, "height": 240}, props)
        a = self._wait_for(live, 240, 240)
        b = self._wait_for(still, 240, 240)
        self.assertEqual(preview_key(live, 240, 240, "dark") == preview_key(still, 240, 240, "dark"), False)
        same = all(a.pixel(x, y) == b.pixel(x, y) for y in range(0, 240, 3) for x in range(0, 240, 3))
        self.assertTrue(same, "the still must not depend on the (absent) feed")

    def test_cache_hits_do_not_requeue(self):
        definition = self.registry.get("ShTelltale")
        widget = DesignerWidget("ShTelltale", "t", {"x": 0, "y": 0, "width": 48, "height": 48},
                                dict(definition.defaults))
        self._wait_for(widget, 48, 48)
        before = len(self.renderer._queue)
        self.assertIsNotNone(self.renderer.image_for(widget, 48, 48, "dark"))
        self.assertEqual(len(self.renderer._queue), before)

    def test_disabled_renderer_hands_back_nothing(self):
        self.renderer.enabled = False
        try:
            widget = DesignerWidget("ShGauge", "g", {"x": 0, "y": 0, "width": 100, "height": 100}, {})
            self.assertIsNone(self.renderer.image_for(widget, 100, 100, "dark"))
        finally:
            self.renderer.enabled = True


if __name__ == "__main__":
    unittest.main()
