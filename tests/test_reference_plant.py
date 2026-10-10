"""A plant overview (SCADA) followed from its picture: a blast furnace.

The fixture is Ornith's plan for the picture the user attached (2026-10-10):
a top strip with the plant's name, the screen's title in a box, the status
over the date and an alarm lamp; the process drawing filling the left and
middle; four numbered cards of reading lines at the right; a green status
banner and a row of seven navigation buttons across the foot.

Before, the strip had no title, the banner was a dot in a corner card, the
buttons a 3x3 grid of blue, the readings two lines each and overrunning
their cards, and the drawing's crop the whole screenshot.
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RECORDED = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_furnace_ornith.json")
W, H = 1024, 768


def _reply():
    with open(RECORDED, encoding="utf-8") as fh:
        return json.load(fh)["reply"]


def _plan():
    reply = _reply()
    return json.loads(reply[reply.index("{"):reply.rindex("}") + 1])


def _generate(plan=None):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    reply = _reply() if plan is None else json.dumps(plan)
    return AIDesignGenerator().generate(reply, W, H)


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        g = w.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
        yield from _walk(w.children, x, y)


class PlantOverview(unittest.TestCase):
    def setUp(self):
        self.project = _generate()
        self.items = list(_walk(self.project.pages[0].widgets))
        self.rects = {w.id: r for w, r in self.items}
        self.byid = {w.id: w for w, _r in self.items}

    def test_it_is_the_reference_layout(self):
        from designer.layout.compiler import compile_page
        from designer.palette.widget_registry import default_registry
        report = compile_page(self.project, self.project.pages[0], default_registry())
        self.assertEqual(report.layout, "reference layout")

    def test_the_title_sits_in_a_box_between_the_name_and_the_status(self):
        title = self.byid["screenTitle"]
        self.assertEqual(title.properties["text"], "BLAST FURNACE - 5 (BF5) SMELTER")
        box = self.rects["titleBox"]
        name, status = self.rects["siteName"], self.rects["status"]
        self.assertLess(name[0] + name[2], box[0] + 1, "the plant's name leads the strip")
        self.assertLess(box[0] + box[2], status[0] + 1, "the status follows the title box")
        self.assertGreater(box[2], W * 0.3, "the title box is the strip's middle")
        self.assertIn("\n", self.byid["siteName"].properties["text"], "the name on two lines")
        clock = self.rects["clock"]
        self.assertGreater(clock[1], status[1], "the date is under the status")
        self.assertLess(abs(clock[0] - status[0]), 2, "in the status's column")

    def test_the_banner_and_the_buttons_are_bands_across_the_foot(self):
        banner = self.rects["systemNormal"]
        self.assertGreater(banner[2], W * 0.9, "the banner runs across the screen")
        self.assertLess(banner[3], 48, "a banner's height, not a row of dials")
        buttons = [r for w, r in self.items if w.type == "ShButton"]
        self.assertEqual(len(buttons), 7)
        self.assertEqual(len({round(r[1]) for r in buttons}), 1, "one row")
        self.assertGreater(min(r[1] for r in buttons), banner[1], "under the banner")
        self.assertGreater(max(r[0] + r[2] for r in buttons) - min(r[0] for r in buttons), W * 0.9)
        for w, _r in self.items:
            if w.type == "ShButton" and w.id != "btnFurnace":
                self.assertEqual(w.properties.get("variant"), "secondary", "tabs, not seven calls to action")
        self.assertEqual(self.byid["btnFurnace"].properties.get("borderWidth"), 2,
                         "the highlighted tab's colour is drawn")
        cards = [r for w, r in self.items if w.type == "ShCard" and w.id.endswith("Card")
                 and r[0] > W * 0.6]
        self.assertTrue(cards)
        self.assertLess(max(r[1] + r[3] for r in cards), banner[1], "the right column ends above the bands")

    def test_reading_lines_are_one_row_each_inside_their_card(self):
        rows = [(w, r) for w, r in self.items
                if w.type in ("ShProcessValue", "ShDataField") and r[0] > W * 0.6]
        self.assertEqual(len(rows), 13)
        for widget, r in rows:
            if widget.type == "ShDataField":
                self.assertIs(widget.properties.get("stacked"), False, widget.id)
            self.assertGreaterEqual(r[3], 20, f"{widget.id} has a line's height")
        for card, cr in self.items:
            if card.type != "ShCard":
                continue
            for child, r in _walk(card.children, cr[0], cr[1]):
                self.assertLessEqual(r[1] + r[3], cr[1] + cr[3] + 1, f"{child.id} stays in {card.id}")

    def test_the_drawing_fills_the_body_and_its_crop_stops_at_the_cards(self):
        from designer.layout.compiler import CROP_MARK
        picture = self.byid["processDiagram"]
        r = self.rects["processDiagram"]
        self.assertGreater(r[2], W * 0.6)
        self.assertGreater(r[3], H * 0.6)
        left, top, right, bottom = picture.properties[CROP_MARK]
        self.assertLess(right, 0.75, "the cards at the right are not part of the drawing")
        self.assertGreater(top, 0.05, "nor is the top strip")
        self.assertLess(bottom, 0.9, "nor the banner")

    def test_a_logo_cropped_from_outside_the_strip_is_left_out(self):
        # Ornith placed both logos in the middle of the drawing (y 0.22..0.34).
        self.assertNotIn("companyLogo", self.byid)
        plan = _plan()
        plan["pages"][0]["header"][1]["crop"] = [170, 5, 260, 80]     # where the JSW logo is
        plan["pages"][0]["header"][1]["side"] = "left"
        project = _generate(plan)
        logo = next(w for w, _r in _walk(project.pages[0].widgets) if w.id == "jswLogo")
        from designer.layout.compiler import CROP_MARK
        self.assertEqual(logo.properties[CROP_MARK], [0.17, 0.005, 0.26, 0.08])

    def test_nothing_leaves_the_glass_or_overlaps_at_the_top_level(self):
        tops = [(w, (float(w.geometry["x"]), float(w.geometry["y"]), float(w.geometry["width"]),
                     float(w.geometry["height"]))) for w in self.project.pages[0].widgets
                if w.type == "ShCard"]
        for w, (x, y, ww, hh) in tops:
            self.assertTrue(x >= 0 and y >= 0 and x + ww <= W + 1 and y + hh <= H + 1, w.id)
        for i, (a, ra) in enumerate(tops):
            for b, rb in tops[i + 1:]:
                ix = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
                iy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
                self.assertFalse(ix > 2 and iy > 2, f"{a.id} overlaps {b.id}")


class ReadingRows(unittest.TestCase):
    """A second Ornith run, once the kit had ShProcessValue: every reading
    line is one, and its crop of the drawing started 13 % too low."""

    def setUp(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        path = RECORDED.replace(".json", "_rows.json")
        with open(path, encoding="utf-8") as fh:
            self.project = AIDesignGenerator().generate(json.load(fh)["reply"], W, H)
        self.items = list(_walk(self.project.pages[0].widgets))

    def test_the_cards_hold_process_value_rows(self):
        rows = [(w, r) for w, r in self.items if w.type == "ShProcessValue"]
        self.assertEqual(len(rows), 13)
        for widget, r in rows:
            self.assertGreater(r[0], W * 0.6, f"{widget.id} is in the right column")
            self.assertGreater(r[2], 200, f"{widget.id} spans its card")
            self.assertTrue(18 <= r[3] <= 40, f"{widget.id} has a line's height")
        self.assertTrue(any(w.properties.get("trend") for w, _r in rows), "the sparklines are kept")

    def test_a_lone_drawing_is_cropped_to_the_body(self):
        from designer.layout.compiler import CROP_MARK
        picture = next(w for w, _r in self.items if w.type == "Image")
        left, top, right, bottom = picture.properties[CROP_MARK]
        self.assertLess(top, 0.12, "the drawing's headings are kept")
        self.assertLess(right, 0.75)
        self.assertLess(bottom, 0.87, "the banner is not part of it")


class StudioRun(unittest.TestCase):
    """What Ornith wrote in the Studio itself (2026-10-10 11:29): the drawing's
    source a placeholder photo URL, and the status and the alarm marked to
    the strip's left."""

    def _plan(self):
        plan = _plan()
        page = plan["pages"][0]
        hero = next(s for s in page["sections"] if s.get("role") == "hero")
        hero["widgets"][0]["properties"]["source"] = "https://picsum.photos/seed/bf5process/900x560"
        for item in page["header"]:
            if item["type"] in ("ShAnnunciator", "ShStatDot"):
                item["side"] = "left"
        return plan

    def test_a_web_address_is_no_picture_and_the_drawing_is_still_cut(self):
        from designer.layout.compiler import CROP_MARK
        from tools.hmi_deployer.ai_tab import pictures_to_fill
        project = _generate(self._plan())
        picture = next(w for w, _r in _walk(project.pages[0].widgets) if w.id == "processDiagram")
        self.assertEqual(picture.properties["source"], "")
        self.assertTrue(picture.properties.get(CROP_MARK))
        self.assertIn(picture, pictures_to_fill(project))

    def test_a_drawing_without_a_crop_is_cut_from_the_body(self):
        from designer.layout.compiler import CROP_MARK
        plan = self._plan()
        hero = next(s for s in plan["pages"][0]["sections"] if s.get("role") == "hero")
        hero["widgets"][0]["properties"].pop("crop", None)
        hero["widgets"][0].pop("crop", None)
        project = _generate(plan)
        picture = next(w for w, _r in _walk(project.pages[0].widgets) if w.id == "processDiagram")
        left, top, right, bottom = picture.properties[CROP_MARK]
        self.assertLess(right, 0.75)
        self.assertGreater(top, 0.05)

    def test_the_readings_follow_the_title_whatever_side_was_written(self):
        rects = {w.id: r for w, r in _walk(_generate(self._plan()).pages[0].widgets)}
        box = rects["titleBox"]
        for wid in ("status", "alarm", "clock"):
            self.assertGreater(rects[wid][0], box[0] + box[2] - 1, f"{wid} is right of the title")
        self.assertLess(rects["siteName"][0], box[0])


class LampStates(unittest.TestCase):
    def test_a_models_status_words_light_the_lamp(self):
        # Ornith's alarm lamp said "warning"; the kit's word is "warn", and the
        # lamp was drawn grey (idle).
        from tools.hmi_deployer.ai_generator import _coerce_choices
        from designer.palette.widget_registry import default_registry
        dot = default_registry().get("ShStatDot")
        for said, kit in (("warning", "warn"), ("alarm", "fault"), ("normal", "ok"),
                          ("ok", "ok"), ("Fault", "fault")):
            self.assertEqual(_coerce_choices(dot, {"state": said})["state"], kit, said)
        self.assertNotIn("state", _coerce_choices(dot, {"state": "purple"}))


class PlantPrompt(unittest.TestCase):
    def test_the_reference_prompt_knows_process_screens(self):
        from tools.hmi_deployer.ai_generator import build_plan_prompt
        prompt = build_plan_prompt(None, W, H, brief="like the picture", reference=True)
        for words in ("process drawing", "ShAnnunciator", "navigation buttons", "\"title\""):
            self.assertIn(words, prompt)
        self.assertIn("never readouts", prompt)


if __name__ == "__main__":
    unittest.main()
