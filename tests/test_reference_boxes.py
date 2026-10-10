"""A reference plan's blocks come with their boxes in the picture, and the
reference layout keeps the picture's proportions from them.

Fixtures: qwen3.8-flash-next-tf's plans (2026-10-10) for the haul truck
cockpit and the blast furnace overview, each section with "box" on the
0..1000 scale. Without boxes the truck's speed arc was a thumbnail, the
payload dial a strip under both columns and the middle of the screen empty.
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


def _project(name, strip_boxes=False):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        reply = json.load(fh)["reply"]
    if strip_boxes:
        plan = json.loads(reply[reply.index("{"):reply.rindex("}") + 1])
        for section in plan["pages"][0]["sections"]:
            section.pop("box", None)
        reply = json.dumps(plan)
    return AIDesignGenerator().generate(reply, W, H)


def _rects(project):
    def walk(ws, ox=0.0, oy=0.0):
        for w in ws:
            g = w.geometry
            x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
            yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
            yield from walk(w.children, x, y)
    return {w.id: r for w, r in walk(project.pages[0].widgets)}


class Truck(unittest.TestCase):
    def setUp(self):
        self.r = _rects(_project("reference_truck_flash_boxes.json"))

    def test_the_payload_dial_sits_under_the_truck_beside_the_rpm_dial(self):
        truck, payload, rpm = self.r["truck"], self.r["payload"], self.r["rpm"]
        self.assertGreater(payload[1], truck[1] + truck[3] - 2, "under the truck")
        mid = payload[0] + payload[2] / 2
        self.assertTrue(truck[0] <= mid <= truck[0] + truck[2], "in the truck's column")
        self.assertLess(rpm[0] + rpm[2], payload[0] + 2, "the RPM dial is beside it, at the left")
        self.assertGreater(payload[2], 180, "a dial, not a strip")

    def test_the_dials_and_the_truck_are_drawn_at_the_pictures_size(self):
        self.assertGreater(self.r["speed"][2], 180)
        self.assertGreater(self.r["rpm"][2], 220)
        self.assertGreater(self.r["truck"][2] * self.r["truck"][3], 0.18 * W * H * 0.6)

    def test_the_right_column_fills_the_body(self):
        cards = [self.r[k] for k in ("inclineCard", "tiresCard", "fuelCard", "vitalsCard")]
        top, bottom = min(c[1] for c in cards), max(c[1] + c[3] for c in cards)
        self.assertGreater(bottom - top, 0.8 * (H - 104 - 24))
        # In the picture's order and about its proportions: tires the tallest.
        self.assertEqual(sorted(cards, key=lambda c: c[1]), cards)
        self.assertEqual(max(cards, key=lambda c: c[3]), self.r["tiresCard"])

    def test_without_boxes_it_is_the_region_layout_as_before(self):
        r = _rects(_project("reference_truck_flash_boxes.json", strip_boxes=True))
        self.assertLess(r["payload"][1], H)       # laid out, the old way
        self.assertNotEqual(r["payload"], self.r["payload"])


class Furnace(unittest.TestCase):
    def test_the_title_is_printed_once(self):
        project = _project("reference_furnace_flash_boxes.json")
        words = [w.properties.get("text") for w in project.pages[0].walk() if w.type == "Text"]
        flat = [str(t or "").replace("\n", " ") for t in words]
        self.assertEqual(sum(1 for t in flat if "SMELTER" in t), 1, flat)

    def test_the_drawing_still_fills_the_body(self):
        r = _rects(_project("reference_furnace_flash_boxes.json"))
        picture = max((v for k, v in r.items() if "iagram" in k or "rocess" in k or "furnace" in k.lower()),
                      key=lambda v: v[2] * v[3])
        self.assertGreater(picture[2], W * 0.6)


class Shares(unittest.TestCase):
    def test_box_heights_are_weights_the_stack_can_use(self):
        from designer.layout.compiler import Section
        from designer.layout.reference import _box_heights, _shares
        sections = [Section("a", "readings", [object()], box=(0, 0.1, 1, 0.3)),
                    Section("b", "readings", [object()], box=(0, 0.3, 1, 0.9))]
        heights = _shares(600, _box_heights(sections), 10)
        self.assertAlmostEqual(sum(heights), 590, delta=1)       # the whole column, not 70 % of it
        self.assertAlmostEqual(heights[1] / heights[0], 3.0, delta=0.05)


if __name__ == "__main__":
    unittest.main()
