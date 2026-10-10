"""A dashboard picture laid out from its blocks' boxes (designer/layout/
reference.py, the box layout).

Fixture: qwen3.8-flash-next-tf's plan (2026-10-10) for a cement plant's
rotary-kiln dashboard: a navigation rail, a row of five KPI tiles, a process
drawing with its live values on it, a row of three panels and a row of two
tables. The region columns could not hold it: the KPI row became a stack of
cards, a 55 px card kept its heading and lost its readings for good, and the
navigation labels were cut to "Over", "Raw".
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_kiln_flash.json")
W, H = 1024, 768


def _plan():
    with open(FIXTURE, encoding="utf-8") as fh:
        reply = json.load(fh)["reply"]
    return json.loads(reply[reply.index("{"):reply.rindex("}") + 1])


def _project(plan=None):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator().generate(json.dumps(plan or _plan()), W, H)


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        g = w.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
        yield from _walk(w.children, x, y)


class BoxLayout(unittest.TestCase):
    def setUp(self):
        self.plan = _plan()
        self.project = _project(self.plan)
        self.items = list(_walk(self.project.pages[0].widgets))
        self.ids = {w.id for w, _r in self.items}

    def test_every_planned_widget_reaches_the_page(self):
        planned = [w.get("id") for s in self.plan["pages"][0]["sections"] for w in s["widgets"]
                   if w.get("type") not in ("Column", "Row")]
        hero = next(s for s in self.plan["pages"][0]["sections"] if s.get("role") == "hero")
        # Readings over the drawing without a box of their own may be left out
        # (the drawing prints them); nothing else is.
        unboxed_hero = {w.get("id") for w in hero["widgets"] if not w.get("box")}
        lost = [i for i in planned if i not in self.ids and i not in unboxed_hero]
        self.assertEqual(lost, [])

    def test_the_kpi_tiles_are_one_row_under_the_strip(self):
        kpis = [r for w, r in self.items if w.type == "ShCard" and r[1] < 160 and r[0] > 100]
        self.assertGreaterEqual(len(kpis), 5)
        self.assertEqual(len({round(r[1]) for r in kpis}), 1, "one row")
        widths = sorted(round(r[2]) for r in kpis)
        self.assertLess(widths[-1] - widths[0], 12, "about equal")

    def test_cards_hold_their_content(self):
        for card, cr in self.items:
            if card.type != "ShCard" or not card.children:
                continue
            for child, r in _walk(card.children, cr[0], cr[1]):
                self.assertLessEqual(r[1] + r[3], cr[1] + cr[3] + 3, f"{child.id} in {card.id}")

    def test_the_navigation_rail_lists_its_items_in_full(self):
        rail = [w for w, _r in self.items if w.type == "ShButton" and w.properties.get("_region") == "rail"]
        self.assertGreaterEqual(len(rail), 8)
        widths = {round(w.geometry["width"]) for w in rail}
        self.assertEqual(len(widths), 1, "full-width items")
        lit = [w for w in rail if str(w.properties.get("backgroundColor") or "").strip()]
        self.assertEqual(len(lit), 1, "the page shown")

    def test_the_strip_reads_a_written_date(self):
        from designer.layout.reference import _DATE_RE
        for text in ("26 Apr 2024  14:32:18", "Apr 26, 2024", "12-10-2026 10:46:02"):
            self.assertTrue(_DATE_RE.search(text), text)
        self.assertFalse(_DATE_RE.search("14:32"))


class Overlays(unittest.TestCase):
    def test_boxed_readings_sit_over_the_drawing(self):
        project = _project()
        items = list(_walk(project.pages[0].widgets))
        picture = max((r for w, r in items if w.type == "Image" and w.properties.get("_crop")),
                      key=lambda r: r[2] * r[3])
        over = [(w, r) for w, r in items if w.properties.get("_wbox")
                and picture[0] <= r[0] + r[2] / 2 <= picture[0] + picture[2]
                and picture[1] <= r[1] + r[3] / 2 <= picture[1] + picture[3]]
        self.assertGreaterEqual(len(over), 5)
        for widget, _r in over:
            if widget.type == "ShProcessValue":
                self.assertEqual(widget.properties.get("label"), "", "the drawing prints the label")


class ReviewCrop(unittest.TestCase):
    def test_the_main_picture_is_trimmed_never_replaced(self):
        from designer.palette.widget_registry import default_registry
        from tools.hmi_deployer.ai_review import _walk as walk, apply_review
        project = _project()
        picture = max((w for w, r, _p in walk(project.pages[0].widgets) if w.type == "Image"),
                      key=lambda w: w.geometry["width"] * w.geometry["height"])
        made = apply_review(project, [{"op": "crop", "id": picture.id, "crop": [200, 300, 450, 450]}],
                            default_registry())
        self.assertEqual(made, [])


if __name__ == "__main__":
    unittest.main()
