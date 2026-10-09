"""ShAnimatedImage: an animated GIF in every layer.

The registry entry and the generated kit schema, the C kit and the QML kit
agree; the QML component plays, pauses and scales speed; the Designer turns a
dropped .gif into one and plays it on the canvas; the bundle carries the file.
(The C widget's own behaviour, a missing file included, is
native/hmi-ui/tests/test_widgets.c.)

    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_animated_image -v
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRectF, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMovie, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.palette.widget_registry import default_registry  # noqa: E402

GIF = os.path.join(ROOT, "tests", "fixtures", "animated", "two_frames.gif")
HMI_UI = os.path.join(ROOT, "native", "hmi-ui")
RED, BLUE = (220, 38, 38), (37, 99, 235)


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _near(colour, rgb, tolerance=40):
    return all(abs(a - b) <= tolerance for a, b in zip((colour.red(), colour.green(), colour.blue()), rgb))


def _spin(app, seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


class RegistryAndKitSchemaTests(unittest.TestCase):
    """One definition, generated into the C kit: the two must not drift."""

    @classmethod
    def setUpClass(cls):
        cls.registry = default_registry()
        sys.path.insert(0, os.path.join(HMI_UI, "schema"))
        import gen_schema
        cls.gen_schema = gen_schema
        cls.schema = gen_schema.build()

    def test_the_registry_entry(self):
        d = self.registry.get("ShAnimatedImage")
        self.assertIsNotNone(d)
        self.assertEqual((d.display_name, d.category, d.qml_component), ("Animated image", "Basic", "ShAnimatedImage"))
        self.assertEqual(d.properties, {"source": str, "playing": bool, "speed": int, "fillMode": str,
                                        "opacity": float, "visible": bool})
        self.assertEqual(d.defaults["playing"], True)
        self.assertEqual(d.defaults["speed"], 100)
        self.assertEqual(d.defaults["source"], "")
        self.assertIn("playing", d.bindable_properties)
        self.assertEqual(d.asset_properties, ("source",))
        image = self.registry.get("Image")
        self.assertTrue(set(d.choices["fillMode"]) <= set(image.choices["fillMode"]))
        self.assertEqual(d.choices["fillMode"], ("Image.PreserveAspectFit", "Image.PreserveAspectCrop", "Image.Stretch"))

    def test_kit_schema_json_types_are_the_registry(self):
        """Every type, property, default and choice in kit_schema.json is what
        gen_schema builds from the registry today (the sim tag list is left
        out: it follows the QML generator, not the widget kit)."""
        committed = json.loads(_read("native", "hmi-ui", "schema", "kit_schema.json"))
        self.assertEqual(committed["types"], self.schema["types"])
        self.assertIn("ShAnimatedImage", committed["types"])

    def test_kit_schema_c_is_generated_from_the_registry(self):
        header, source = self.gen_schema.render_c(self.schema)
        self.assertEqual(_read("native", "hmi-ui", "src", "gen", "kit_schema.c"), source)
        self.assertEqual(_read("native", "hmi-ui", "src", "gen", "kit_schema.h"), header)
        self.assertIn('{"playing", HMI_KIND_BOOL, "true", true}', source)

    def test_every_kit_type_has_a_c_widget_and_a_qml_face(self):
        kit = _read("native", "hmi-ui", "src", "widgets", "kit.c")
        qmldir = _read("ui", "qml", "Shadcn", "qmldir")
        for name, t in self.schema["types"].items():
            ident = "hmi_widget_" + name.lower()
            with self.subTest(type=name):
                self.assertIn(f"hmi_registry_register(&{ident});", kit)
                if t["qml"].startswith("Sh"):
                    self.assertRegex(qmldir, rf"(?m)^{t['qml']} 1\.0 {t['qml']}\.qml$")
        self.assertTrue(os.path.isfile(os.path.join(HMI_UI, "src", "widgets", "w_shanimatedimage.c")))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "ui", "qml", "Shadcn", "ShAnimatedImage.qml")))

    def test_lvgl_gif_decoder_is_on(self):
        # One lv_conf.h serves build.sh, win64/build.sh and arm64/build.sh.
        self.assertRegex(_read("native", "hmi-ui", "lv_conf.h"), r"(?m)^#define LV_USE_GIF 1\b")
        self.assertIn("LV_BUILD_CONF_PATH \"${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h\"",
                      _read("native", "hmi-ui", "CMakeLists.txt"))

    def test_the_c_type_count_follows_the_schema(self):
        count = len(self.schema["types"])
        self.assertIn(f"CHECK(hmi_kit_type_count == {count});", _read("native", "hmi-ui", "tests", "test_model.c"))

    def test_ai_design_may_plan_one(self):
        from tools.hmi_deployer.ai_generator import PLAN_CATALOGUE
        entries = dict(PLAN_CATALOGUE)
        self.assertEqual(entries["moving picture (a .gif the user supplies)"], ("ShAnimatedImage",))


class QmlComponentTests(unittest.TestCase):
    """ShAnimatedImage.qml offscreen: the placeholder, then the GIF playing."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Removed last, after the view has let go of the GIF (Windows locks it).
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.addCleanup(lambda: (_spin(self.app, 0.1),
                                 QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)))
        self.root = self.dir.name

    def _load(self, body, directory):
        from PySide6.QtQml import QQmlComponent
        from PySide6.QtQuick import QQuickView
        view = QQuickView()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        view.engine().addImportPath(os.path.join(ROOT, "ui", "qml"))
        component = QQmlComponent(view.engine())
        source = ("import QtQuick 2.15\nimport Shadcn 1.0\n"
                  "Rectangle { width: 240; height: 160; color: \"#101318\"\n"
                  "  Component.onCompleted: Theme.mode = \"dark\"\n"
                  f"  ShAnimatedImage {{ objectName: \"anim\"; anchors.fill: parent\n{body}\n  }}\n}}")
        component.setData(source.encode(), QUrl.fromLocalFile(os.path.join(directory, "generated", "Main.qml")))
        self.assertFalse(component.errors(), [e.toString() for e in component.errors()])
        obj = component.create()
        self.assertIsNotNone(obj, [e.toString() for e in component.errors()])
        view.setContent(QUrl(), component, obj)
        view.resize(240, 160)
        view.show()
        anim = obj.findChild(QObject, "anim")
        self.assertIsNotNone(anim)
        self._keep = (component, obj)            # Python owns obj: keep it alive
        self.addCleanup(lambda: setattr(self, "_keep", None))
        self.addCleanup(lambda: anim.setProperty("source", ""))   # lets go of the file
        return view, anim

    @staticmethod
    def _movie(anim):
        for child in anim.childItems():
            if child.metaObject().className().startswith("QQuickAnimatedImage"):
                return child
        return None

    def test_no_source_draws_the_placeholder(self):
        root = self.root
        view, anim = self._load("", root)
        _spin(self.app, 0.3)
        self.assertFalse(self._movie(anim).isVisible())
        image = view.grabWindow()
        # The card is Theme.muted (dark: #27272a), the glyph mutedForeground.
        self.assertTrue(_near(image.pixelColor(10, 10), (0x27, 0x27, 0x2a), 6), image.pixelColor(10, 10).name())
        inks = {image.pixelColor(x, y).name() for y in range(30, 130, 2) for x in range(60, 180, 2)}
        self.assertTrue(any(_near(QColor(c), (0xa1, 0xa1, 0xaa), 12) for c in inks), "no glyph drawn")

    def test_a_missing_file_draws_the_placeholder(self):
        root = self.root
        view, anim = self._load('source: "../assets/gone.gif"', root)
        _spin(self.app, 0.5)
        self.assertFalse(self._movie(anim).isVisible())

    def test_plays_pauses_speeds_and_fills(self):
        root = self.root
        os.makedirs(os.path.join(root, "assets"))
        shutil.copy(GIF, os.path.join(root, "assets", "truck.gif"))
        view, anim = self._load('source: "../assets/truck.gif"\n'
                                'fillMode: Image.PreserveAspectCrop\nspeed: 50', root)
        movie = self._movie(anim)
        self.assertTrue(_spin(self.app, 3, lambda: movie.property("frameCount") == 2),   # loaded
                        f"frameCount {movie.property('frameCount')}")
        self.assertTrue(movie.isVisible())
        self.assertEqual(movie.property("frameCount"), 2)
        self.assertTrue(movie.property("playing"))
        self.assertFalse(movie.property("paused"))
        self.assertAlmostEqual(movie.property("speed"), 0.5)
        # PreserveAspectCrop: a 16x12 picture in a 240x160 box covers it to the
        # edges (fit would leave the background beside it), red or blue.
        image = view.grabWindow()
        for x, y in ((120, 80), (2, 80), (237, 80)):
            colour = image.pixelColor(x, y)
            self.assertTrue(_near(colour, RED) or _near(colour, BLUE), (x, y, colour.name()))
        # It moves: both frames show within a second at half speed (200 ms each).
        seen = set()
        def both():
            seen.add(movie.property("currentFrame"))
            return seen >= {0, 1}
        self.assertTrue(_spin(self.app, 2, both), seen)
        anim.setProperty("playing", False)
        self.assertTrue(movie.property("paused"))
        held = movie.property("currentFrame")
        _spin(self.app, 0.6)
        self.assertEqual(movie.property("currentFrame"), held)
        anim.setProperty("playing", True)
        self.assertFalse(movie.property("paused"))
        anim.setProperty("speed", 300)
        self.assertAlmostEqual(movie.property("speed"), 3.0)


class GeneratorTests(unittest.TestCase):
    def test_the_generator_writes_the_component_with_its_asset_path(self):
        from designer.generators.qml_generator import QmlGenerator
        from designer.model import DesignerBinding, DesignerWidget
        registry = default_registry()
        props = dict(registry.get("ShAnimatedImage").defaults, source="assets/truck.gif",
                     fillMode="Image.Stretch", speed=0)
        widget = DesignerWidget("ShAnimatedImage", "truck", {"x": 0, "y": 0, "width": 240, "height": 160},
                                props, {"playing": DesignerBinding("mb.truck_moving")})
        text = "\n".join(QmlGenerator(registry)._widget(widget, 1))
        self.assertIn("ShAnimatedImage {", text)
        self.assertIn('source: "../assets/truck.gif"', text)
        self.assertIn("fillMode: Image.Stretch", text)
        self.assertIn("speed: 1", text)                 # clamped to its floor
        self.assertRegex(text, r"playing: .*mb\.truck_moving")


def _workspace(test, root):
    from designer.ui.designer_workspace import DesignerWorkspace
    ws = DesignerWorkspace()
    test.addCleanup(ws.deleteLater)

    def release():
        # The canvas plays a dropped GIF with a QMovie that holds the file
        # open; Windows will not delete it until the movie is gone.
        for item in ws.scene.items():
            if hasattr(item, "_drop_movie"):
                item._drop_movie()
        _spin(QApplication.instance(), 0.1)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    test.addCleanup(release)
    ws.projects_root = root
    ws.ensure_bundle()
    return ws


class DesignerDropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ws = _workspace(self, self.dir.name)

    def test_a_dropped_gif_becomes_an_animated_image(self):
        src = os.path.join(self.dir.name, "Wireframe Truck.GIF")
        shutil.copy(GIF, src)
        model = self.ws.drop_image_file(src, 40, 30)
        self.assertIsNotNone(model)
        self.assertEqual(model.type, "ShAnimatedImage")
        self.assertEqual(model.properties["source"], "assets/wireframe_truck.gif")
        copied = os.path.join(self.ws.bundle_dir, "assets", "wireframe_truck.gif")
        with open(copied, "rb") as a, open(GIF, "rb") as b:
            self.assertEqual(a.read(), b.read(), "the GIF is copied as it is, every frame kept")
        self.assertEqual((model.geometry["x"], model.geometry["y"]), (40, 30))
        self.assertEqual((model.geometry["width"], model.geometry["height"]), (240, 160))
        self.assertTrue(model.properties["playing"])
        self.assertIn(model, list(self.ws.current_page.walk()))
        self.assertEqual(self.ws.project.validate(self.ws.registry, self.ws.bundle_dir), [])
        self.ws.undo_stack.undo()
        self.assertNotIn(model, list(self.ws.current_page.walk()))

    def test_other_pictures_stay_images(self):
        src = os.path.join(self.dir.name, "logo.jpg")
        image = QImage(20, 10, QImage.Format_RGB32)
        image.fill(QColor("#22c55e"))
        image.save(src, "JPG")
        model = self.ws.drop_image_file(src, 0, 0)
        self.assertEqual(model.type, "Image")
        self.assertEqual(model.properties["source"], "assets/logo.png")

    def test_a_gif_brand_logo_is_still_a_still_image(self):
        src = os.path.join(self.dir.name, "acme.gif")
        shutil.copy(GIF, src)
        self.ws.set_brand(logos=[src])
        self.assertEqual(self.ws.project.brand["logos"], ["assets/acme.png"])
        self.assertEqual(self.ws.current_page.widgets[-1].type, "Image")

    def test_the_bundle_carries_the_gif(self):
        from schema.bundle import plan_bundle
        src = os.path.join(self.dir.name, "truck.gif")
        shutil.copy(GIF, src)
        self.ws.drop_image_file(src, 0, 0)
        paths = self.ws.generate()
        self.assertTrue(paths)
        generated = "".join(open(p, encoding="utf-8").read() for p in paths)
        self.assertIn('source: "../assets/truck.gif"', generated)
        entries, _total = plan_bundle(self.ws.bundle_dir)
        names = [name for _full, name in entries]
        self.assertIn("assets/truck.gif", names)
        self.assertTrue(any(re.search(r"\.edsui$", n) for n in names), names)


class CanvasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ws = _workspace(self, self.dir.name)

    def _pixel(self, model, x=None, y=None):
        item = self.ws.scene.item_for_id(model.id)
        rect = item.sceneBoundingRect()
        frame = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        frame.fill(0)
        painter = QPainter(frame)
        self.ws.scene.render(painter, QRectF(frame.rect()), rect)
        painter.end()
        return frame.pixelColor(frame.width() // 2 if x is None else x, frame.height() // 2 if y is None else y)

    def test_the_gif_plays_on_the_canvas(self):
        self.assertIn(b"gif", [bytes(f) for f in QMovie.supportedFormats()])
        src = os.path.join(self.dir.name, "truck.gif")
        shutil.copy(GIF, src)
        model = self.ws.drop_image_file(src, 0, 0)
        item = self.ws.scene.item_for_id(model.id)
        colours = set()
        def both():
            c = self._pixel(model)
            colours.add("red" if _near(c, RED) else "blue" if _near(c, BLUE) else c.name())
            return {"red", "blue"} <= colours
        self.assertTrue(_spin(self.app, 2, both), colours)
        self.assertIsNotNone(item._movie)
        # playing false holds the frame
        self.ws.scene.clearSelection(); item.setSelected(True)
        self.ws._property_command("playing", False)
        item = self.ws.scene.item_for_id(model.id)
        self._pixel(model)
        self.assertEqual(item._movie.state(), QMovie.Paused)

    def test_no_source_or_a_missing_file_shows_the_placeholder(self):
        self.ws.add_widget("ShAnimatedImage")
        model = self.ws.current_page.widgets[-1]
        corner = self._pixel(model, 12, 12)
        self.assertTrue(_near(corner, (0x27, 0x27, 0x2a), 6), corner.name())
        model.properties["source"] = "assets/not_there.gif"
        self.ws.scene.item_for_id(model.id).update()
        corner = self._pixel(model, 12, 12)
        self.assertTrue(_near(corner, (0x27, 0x27, 0x2a), 6), corner.name())
        self.assertIsNone(getattr(self.ws.scene.item_for_id(model.id), "_movie", None))


if __name__ == "__main__":
    unittest.main()
