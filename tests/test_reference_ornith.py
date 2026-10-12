"""A cement kiln dashboard as Ornith plans it (designer/layout/reference.py,
compiler.py, palette.py).

Fixtures: three ornith-1.5-35b-a3b replies (2026-10-12) for the same picture
(a navigation rail, five KPI tiles, a process drawing with its live values,
a control panel, a trend, a status list and two tables):
- reference_kiln_ornith_boxes.json puts the five tiles in one section of
  region "top", gives each reading's place as boxLeft/boxTop/boxRight/
  boxBottom, makes Mode and Start/Stop ShToggles and its boxes are rough;
- reference_kiln_ornith_1280.json measures x on 0..1280 and y on 0..1000,
  crops the drawing as "the whole picture" on 0..1000 and writes its lists
  with ";" and "|";
- reference_kiln_ornith_loose.json gives no crop for the drawing, writes
  values as text ("3,015", "3.20"), puts colours in a "colours" object
  beside "properties", closes every reading's box inside a key ('"box
  [192, 232, 280, 300] },, "') and puts two readings on one spot.
The Studio laid them out as a crammed title strip over an empty body, an
empty picture frame, and a KPI tile turned into a text tile.
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "ai")
W, H = 1024, 768


def _reply(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)["reply"]


def _project(name):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator().generate(_reply(name), W, H)


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        g = w.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
        yield from _walk(w.children, x, y)


class _Layout:
    FIXTURE = ""

    @classmethod
    def setUpClass(cls):
        cls.project = _project(cls.FIXTURE)
        cls.items = list(_walk(cls.project.pages[0].widgets))
        cls.by_id = {w.id: (w, r) for w, r in cls.items}

    def test_the_kpi_tiles_are_a_row_under_the_strip(self):
        strip = self.by_id["topStrip"][1]
        tiles = [r for w, r in self.items if w.type == "ShKpiTile"]
        self.assertEqual(len(tiles), 5)
        for r in tiles:
            self.assertGreaterEqual(r[1], strip[1] + strip[3], "below the strip")
            self.assertGreaterEqual(r[0], 0)
            self.assertLessEqual(r[0] + r[2], W)
        self.assertEqual(len({round(r[1]) for r in tiles}), 1, "one row")

    def test_every_block_reaches_the_page(self):
        types = {w.type for w, _r in self.items}
        for wanted in ("ShTrendChart", "ShStatusRow", "ShAlarmTable", "ShNumInput", "Image"):
            self.assertIn(wanted, types)
        self.assertEqual(sum(1 for w, _r in self.items if w.type == "ShAlarmTable"), 2)

    def test_cards_hold_their_content(self):
        for card, cr in self.items:
            if card.type != "ShCard":
                continue
            for child, r in _walk(card.children, cr[0], cr[1]):
                self.assertLessEqual(r[1] + r[3], cr[1] + cr[3] + 3, f"{child.id} in {card.id}")

    def test_the_control_panel_rows_are_readable(self):
        rows = [r for w, r in self.items if w.type in ("ShNumInput", "ShButton")
                and w.properties.get("_region") == "bottom"]
        self.assertTrue(rows)
        for r in rows:
            self.assertGreaterEqual(r[3], 18, "a row a finger can read")

    def test_mode_is_a_lit_pair_of_buttons(self):
        texts = {w.properties.get("text"): w for w, _r in self.items if w.type == "ShButton"}
        self.assertIn("AUTO", texts)
        self.assertIn("MANUAL", texts)
        self.assertTrue(texts["AUTO"].properties.get("backgroundColor"), "the current mode is lit")
        self.assertFalse(any(w.type == "ShToggle" for w, _r in self.items))
        labels = [w.properties.get("text") for w, _r in self.items if w.type == "Text"]
        self.assertIn("Mode", labels)
        self.assertIn("Speed Setpoint", labels)

    def test_the_trend_labels_are_comma_lists(self):
        trend = next(w for w, _r in self.items if w.type == "ShTrendChart")
        self.assertNotIn(";", trend.properties.get("xLabels", ""))
        self.assertIn(",", trend.properties.get("xLabels", ""))

    def test_the_rail_runs_to_the_foot(self):
        rail = next(r for w, r in self.items if w.type == "ShCard"
                    and any(c.properties.get("_region") == "rail" for c in w.children))
        self.assertGreater(rail[1] + rail[3], H - 40)


class BoxesReply(_Layout, unittest.TestCase):
    FIXTURE = "reference_kiln_ornith_boxes.json"

    def test_readings_keep_their_place_on_the_drawing(self):
        picture = max((r for w, r in self.items if w.type == "Image"), key=lambda r: r[2] * r[3])
        over = [w for w, r in self.items if w.type == "ShProcessValue" and w.properties.get("_wbox")
                and picture[0] <= r[0] + r[2] / 2 <= picture[0] + picture[2]
                and picture[1] <= r[1] + r[3] / 2 <= picture[1] + picture[3]]
        self.assertGreaterEqual(len(over), 15)
        for widget in over:
            self.assertTrue(widget.properties.get("unitInside"))
            self.assertEqual(widget.properties.get("label"), "")


class Scale1280Reply(_Layout, unittest.TestCase):
    FIXTURE = "reference_kiln_ornith_1280.json"

    def test_the_plan_scale_is_read_per_axis(self):
        from designer.layout.compiler import plan_scale
        from designer.layout.intake import loads_lenient
        reply = _reply(self.FIXTURE)
        page = loads_lenient(reply[reply.index("{"):])["pages"][0]
        self.assertEqual(plan_scale(page), (1280.0, 1000.0))

    def test_the_whole_picture_crop_stays_whole(self):
        from designer.layout.compiler import crop_of
        self.assertEqual(crop_of([0, 0, 1000, 1000], (1280.0, 1000.0), own=True), [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(crop_of([0, 0, 1260, 1000], (1280.0, 1000.0), own=True)[2], 0.9844)

    def test_the_tab_bar_spans_its_block(self):
        tabs = next(r for w, r in self.items if w.type == "ShTabs")
        self.assertGreater(tabs[2], 600)
        tab = next(w for w, _r in self.items if w.type == "ShTabs")
        self.assertNotIn("|", tab.properties["tabs"])


class LooseReply(unittest.TestCase):
    FIXTURE = "reference_kiln_ornith_loose.json"

    @classmethod
    def setUpClass(cls):
        cls.project = _project(cls.FIXTURE)
        cls.items = list(_walk(cls.project.pages[0].widgets))
        cls.by_id = {w.id: w for w, _r in cls.items}

    def test_a_value_with_thousands_marked_stays_on_its_tile(self):
        self.assertEqual(self.by_id["prodRate"].type, "ShKpiTile")
        self.assertEqual(self.by_id["prodRate"].properties["value"], "3,015")
        self.assertEqual(self.by_id["kilnOutletTemp"].type, "ShProcessValue")

    def test_a_set_point_written_as_text_keeps_its_decimals(self):
        field = next(w for w, _r in self.items if w.type == "ShNumInput"
                     and abs(float(w.properties.get("value") or 0) - 3.2) < 1e-6)
        self.assertEqual(field.properties.get("decimalPlaces"), 2)

    def test_the_drawing_is_cut_from_its_block(self):
        picture = next(w for w, _r in self.items if w.type == "Image")
        self.assertTrue(picture.properties.get("_crop"), "cut on Apply, not an empty frame")

    def test_readings_keep_a_box_written_into_a_key(self):
        spots = [w for w, _r in self.items if w.type == "ShProcessValue" and w.properties.get("_wbox")]
        self.assertGreaterEqual(len(spots), 15)

    def test_colours_beside_the_properties_are_kept(self):
        rail = [w for w, _r in self.items if w.type == "ShButton" and w.properties.get("_region") == "rail"]
        lit = [w for w in rail if str(w.properties.get("backgroundColor") or "").lower() == "#dc2626"]
        self.assertEqual(len(lit), 1)


class PipesReply(unittest.TestCase):
    """reference_kiln_ornith_pipes.json: table columns written with "|",
    and the fifth KPI tile's box a third as wide as the others'."""

    @classmethod
    def setUpClass(cls):
        cls.project = _project("reference_kiln_ornith_pipes.json")
        cls.items = list(_walk(cls.project.pages[0].widgets))

    def test_table_columns_are_comma_lists(self):
        tables = [w for w, _r in self.items if w.type == "ShAlarmTable"]
        self.assertEqual(len(tables), 2)
        for table in tables:
            self.assertNotIn("|", table.properties["columns"])
            self.assertIn(",", table.properties["columns"])

    def test_the_kpi_row_shares_its_span(self):
        widths = [r[2] for w, r in self.items if w.type == "ShKpiTile"]
        self.assertEqual(len(widths), 5)
        self.assertLess(max(widths) - min(widths), 0.2 * max(widths))


class TwinSpots(unittest.TestCase):
    """Two readings the model put on one spot get no box of their own: a
    guess would show one's value over the other's printed box."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_twins_are_left_to_the_drawing(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QImage, QPainter
        from designer.layout.palette import align_spots
        from designer.model import DesignerPage, DesignerProject, DesignerScreen, DesignerWidget
        image = QImage(1000, 800, QImage.Format_RGB32)
        image.fill(QColor("#1d2830"))
        painter = QPainter(image)
        painter.fillRect(QRect(120, 180, 860, 340), QColor("#e6ebef"))
        boxes = [(160, 260), (160, 340), (460, 300), (850, 250), (850, 300)]
        for x, y in boxes:
            painter.fillRect(QRect(x, y, 50, 22), QColor("#05080a"))
        painter.end()
        spot = lambda x, y: [(x + 5) / 1000, (y + 2) / 800, (x + 55) / 1000, (y + 24) / 800]
        spots = [spot(*boxes[0]), spot(*boxes[1]), spot(*boxes[2]), spot(850, 260), spot(850, 260)]
        widgets = [DesignerWidget(type="Image", id="drawing", geometry={},
                                  properties={"_crop": [0.12, 0.225, 0.98, 0.65]})]
        widgets += [DesignerWidget(type="ShProcessValue", id=f"r{i}", geometry={}, properties={"_wbox": s})
                    for i, s in enumerate(spots)]
        project = DesignerProject(name="t", screen=DesignerScreen(width=1024, height=768),
                                  pages=[DesignerPage(id="main", name="Main", widgets=widgets)])
        self.assertEqual(align_spots(image, project), 3)
        self.assertNotIn("_wbox", widgets[4].properties)
        self.assertNotIn("_wbox", widgets[5].properties)


class SplitBoxKeys(unittest.TestCase):
    def test_a_box_closed_inside_a_key(self):
        from designer.layout.compiler import item_box
        item = {"type": "ShProcessValue", "properties": {}, "box [192, 232, 280, 300] },, ": {"tag": "k.x"}}
        self.assertEqual(item_box(item), [0.192, 0.232, 0.28, 0.3])

    def test_box_keys_beside_the_properties(self):
        from designer.layout.compiler import item_box
        item = {"type": "ShProcessValue", "properties": {}, "boxLeft": 195, "boxTop": 230,
                "boxRight": 270, "boxBottom": 270}
        self.assertEqual(item_box(item), [0.195, 0.23, 0.27, 0.27])
        self.assertEqual(item_box({"box": {"left": 100, "top": 100, "right": 200, "bottom": 300}}),
                         [0.1, 0.1, 0.2, 0.3])


class PictureFit(unittest.TestCase):
    """palette.trim_crops and align_spots on a drawn reference: a light
    panel on a dark screen, with dark value boxes printed on it."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _reference(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QImage, QPainter
        image = QImage(1000, 800, QImage.Format_RGB32)
        image.fill(QColor("#1d2830"))
        painter = QPainter(image)
        painter.fillRect(QRect(120, 180, 860, 340), QColor("#e6ebef"))   # the drawing's panel
        self.boxes = [(160, 260), (160, 340), (460, 300), (520, 300), (580, 300), (850, 420)]
        for x, y in self.boxes:
            painter.fillRect(QRect(x, y, 50, 22), QColor("#05080a"))
        painter.end()
        return image

    def _project(self, crop, spots):
        from designer.model import DesignerPage, DesignerProject, DesignerScreen, DesignerWidget
        picture = DesignerWidget(type="Image", id="drawing", geometry={}, properties={"_crop": crop})
        readings = [DesignerWidget(type="ShProcessValue", id=f"r{i}", geometry={},
                                   properties={"_wbox": spot}) for i, spot in enumerate(spots)]
        page = DesignerPage(id="main", name="Main", widgets=[picture] + readings)
        return DesignerProject(name="t", screen=DesignerScreen(width=1024, height=768), pages=[page])

    def test_a_short_crop_grows_to_its_panel(self):
        from designer.layout.palette import trim_crops
        project = self._project([0.19, 0.25, 0.98, 0.70], [])
        self.assertEqual(trim_crops(self._reference(), project), 1)
        l, t, r, b = project.pages[0].widgets[0].properties["_crop"]
        self.assertAlmostEqual(l, 0.12, delta=0.012)
        self.assertAlmostEqual(t, 0.225, delta=0.012)
        self.assertAlmostEqual(b, 0.65, delta=0.012)

    def test_shifted_spots_take_their_printed_boxes(self):
        from designer.layout.palette import align_spots
        reference = self._reference()
        # Every spot 6 % low and 2 % right of its box, as Ornith's were.
        spots = [[(x + 25) / 1000 + 0.02 - 0.025, (y + 11) / 800 + 0.06 - 0.014,
                  (x + 25) / 1000 + 0.02 + 0.025, (y + 11) / 800 + 0.06 + 0.014] for x, y in self.boxes]
        project = self._project([0.12, 0.225, 0.98, 0.65], spots)
        self.assertEqual(align_spots(reference, project), len(self.boxes))
        for widget, (x, y) in zip(project.pages[0].widgets[1:], self.boxes):
            l, t, r, b = widget.properties["_wbox"]
            self.assertAlmostEqual((l + r) / 2, (x + 25) / 1000, delta=0.004, msg=widget.id)
            self.assertAlmostEqual((t + b) / 2, (y + 11) / 800, delta=0.004, msg=widget.id)


class ReviewLimits(unittest.TestCase):
    def test_a_review_asks_for_a_short_reply(self):
        from tools.hmi_deployer.ai_design import MAX_OUTPUT_TOKENS, ODConnector
        from tools.hmi_deployer.ai_review import MAX_REVIEW_TOKENS
        connector = ODConnector()
        self.assertEqual(connector._output_limit(MAX_OUTPUT_TOKENS), MAX_OUTPUT_TOKENS)
        connector.max_output_tokens = MAX_REVIEW_TOKENS
        self.assertEqual(connector._output_limit(MAX_OUTPUT_TOKENS), MAX_REVIEW_TOKENS)


class BlankWords(unittest.TestCase):
    def test_a_blank_label_reaches_the_qml(self):
        from designer.generators.qml_generator import QmlGenerator
        from designer.palette.widget_registry import default_registry
        definition = default_registry().get("ShProcessValue")
        self.assertTrue(QmlGenerator._blank_text(definition, "label"))
        self.assertFalse(QmlGenerator._blank_text(definition, "unit"), "its default is blank already")
        self.assertFalse(QmlGenerator._blank_text(definition, "valueColor"))


if __name__ == "__main__":
    unittest.main()
