"""The reference layout family (designer/layout/reference.py) beyond the
frozen wave 6 gate: accents, side marks, frameless regions, the rail, and a
region left empty giving its room away."""
import copy
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _generate(plan, width=1024, height=768):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    reply = "```json\n" + json.dumps(plan) + "\n```"
    return AIDesignGenerator().generate(reply, width, height)


def _plan(sections, header=None, title="Rig"):
    return {"name": "t", "pages": [{"id": "main", "name": "Main", "title": title,
                                    "header": header or [], "sections": sections}]}


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        x, y = ox + float(w.geometry.get("x", 0)), oy + float(w.geometry.get("y", 0))
        yield w, (x, y, float(w.geometry.get("width", 0)), float(w.geometry.get("height", 0)))
        yield from _walk(w.children, x, y)


def _by_id(project):
    return {w.id: (w, r) for w, r in _walk(project.pages[0].widgets)}


def _card_of(project, wid):
    """The chrome card that holds widget `wid`."""
    for top in project.pages[0].widgets:
        if any(child.id == wid for child in top.children):
            return top
    return None


GAUGE = {"type": "ShClusterGauge", "properties": {"caption": "RPM", "value": 2, "maximumValue": 3}}
ARC = {"type": "ShSpeedArc", "properties": {"value": 30, "maximumValue": 80}}
TILE = {"type": "ShValueTile", "properties": {"title": "Load", "value": "42"}}


def _w(spec, wid):
    out = copy.deepcopy(spec)
    out["id"] = wid
    return out


class Accent(unittest.TestCase):
    def test_accent_of_reads_hex_and_names(self):
        from designer.layout.compiler import accent_of
        self.assertEqual(accent_of("#F97316"), "#f97316")
        self.assertEqual(accent_of("orange"), "#f97316")
        self.assertEqual(accent_of(" Amber "), "#f59e0b")
        self.assertEqual(accent_of("not a colour"), "")
        self.assertEqual(accent_of(""), "")

    def test_the_plan_accent_is_marked_and_read_back(self):
        from designer.layout.compiler import ACCENT_MARK, infer_sections, sections_from_plan
        from designer.palette.widget_registry import default_registry
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "accent": "blue",
                       "widgets": [_w(ARC, "speed")]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}])
        _t, sections, _h = sections_from_plan(plan["pages"][0], AIDesignGenerator()._convert_widgets)
        self.assertEqual(sections[0].accent, "#3b82f6")
        self.assertEqual(sections[1].accent, "")
        project = _generate(plan)
        speed = _by_id(project)["speed"][0]
        self.assertEqual(speed.properties.get(ACCENT_MARK), "#3b82f6")
        _t, inferred, _h, _n = infer_sections(project.pages[0], default_registry())
        self.assertEqual({s.title: s.accent for s in inferred}.get("Speed"), "#3b82f6")

    def test_an_accent_fills_empty_colours_only(self):
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "accent": "#22c55e",
                       "widgets": [_w(ARC, "speed")]},
                      {"title": "Other", "region": "left", "accent": "#22c55e",
                       "widgets": [dict(_w(ARC, "kept"), properties={"outerColor": "#ff0000"})]},
                      {"title": "Load", "region": "right", "accent": "#f97316",
                       "widgets": [_w(TILE, "load")]}])
        project = _generate(plan)
        ids = _by_id(project)
        speed = ids["speed"][0]
        self.assertEqual(speed.properties.get("outerColor"), "#22c55e")
        self.assertTrue(speed.properties.get("innerColor", "").startswith("#"))
        self.assertNotEqual(speed.properties.get("innerColor"), "#22c55e", "inner ring is a deeper shade")
        self.assertEqual(ids["kept"][0].properties.get("outerColor"), "#ff0000")
        # A framed (right column) card takes the accent on its border.
        self.assertEqual(_card_of(project, "load").properties.get("borderColor"), "#f97316")


class Regions(unittest.TestCase):
    def test_left_center_and_bottom_are_frameless_right_keeps_its_card(self):
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "widgets": [_w(ARC, "speed")]},
                      {"title": "RPM", "region": "bottom", "widgets": [_w(GAUGE, "rpm")]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}])
        project = _generate(plan)
        for wid in ("speed", "rpm"):
            card = _card_of(project, wid)
            self.assertEqual(card.properties.get("color"), "#00000000", wid)
            self.assertEqual(card.properties.get("borderColor"), "#00000000", wid)
            # A lone gauge names itself: no heading over it.
            self.assertFalse(any(c.id.endswith("Heading") for c in card.children), wid)
        right = _card_of(project, "load")
        self.assertNotEqual(right.properties.get("color"), "#00000000")
        self.assertTrue(any(c.id.endswith("Heading") for c in right.children))

    def test_an_empty_region_gives_its_room_away(self):
        W = 1024
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "widgets": [_w(ARC, "speed")]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}])
        project = _generate(plan, W, 768)
        card = _card_of(project, "speed")
        g = card.geometry
        # No center, rail or bottom: the left region runs from the margin to
        # the right column, and down to the bottom margin.
        self.assertLess(g["x"], 40)
        self.assertGreater(g["x"] + g["width"], W * 0.6)
        self.assertGreater(g["y"] + g["height"], 768 * 0.9)

    def test_a_section_without_a_region_joins_the_center(self):
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "widgets": [_w(ARC, "speed")]},
                      {"title": "Loose", "widgets": [_w(TILE, "loose")]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}])
        project = _generate(plan)
        ids = _by_id(project)
        sx = ids["speed"][1][0]
        lx = ids["loose"][1][0]
        rx = ids["load"][1][0]
        self.assertTrue(sx < lx < rx)

    def test_portrait_and_cab_plans_are_not_this_family(self):
        from designer.layout import families
        from designer.layout.compiler import Section
        from designer.model import DesignerWidget
        a = Section("A", "readings", [DesignerWidget(type="ShValueTile", id="a", geometry={})], region="left")
        b = Section("B", "readings", [DesignerWidget(type="ShValueTile", id="b", geometry={})], region="right")
        self.assertEqual(families.family_for([a, b], [], 1024, 768)[0], "reference layout")
        found = families.family_for([a, b], [], 600, 1024)
        self.assertNotEqual(found and found[0], "reference layout")
        cab = [Section("Drive", "hero", [DesignerWidget(type="ShSpeedArc", id="arc", geometry={}),
                                         DesignerWidget(type="ShTractionBar", id="tb", geometry={})], region="left"),
               Section("Route", "readings", [DesignerWidget(type="ShStationLine", id="line", geometry={})], region="center")]
        self.assertEqual(families.family_for(cab, [], 1024, 768)[0], "cab display")
        self.assertLess(families.names().index("cab display"), families.names().index("reference layout"))


class Strip(unittest.TestCase):
    HEADER = [{"type": "ShTelltale", "id": "lte", "side": "left", "properties": {"label": "LTE"}},
              {"type": "Text", "id": "clock", "properties": {"text": "09:41"}},
              {"type": "ShStatDot", "id": "ok", "properties": {"label": "System"}}]

    def test_side_left_is_marked_on_any_header_item(self):
        from designer.layout.compiler import SIDE_MARK, sections_from_plan
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        page = _plan([], header=self.HEADER)["pages"][0]
        _t, _s, header = sections_from_plan(page, AIDesignGenerator()._convert_widgets)
        marks = {w.id: w.properties.get(SIDE_MARK) for w in header}
        self.assertEqual(marks.get("lte"), "left")
        self.assertIsNone(marks.get("ok"))

    def test_the_strip_puts_left_items_left_the_clock_centre_the_rest_right(self):
        W = 1024
        plan = _plan([{"title": "Speed", "role": "hero", "region": "left", "widgets": [_w(ARC, "speed")]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}],
                     header=self.HEADER)
        ids = _by_id(_generate(plan, W, 768))
        self.assertLess(ids["lte"][1][0], W * 0.2)
        cx = ids["clock"][1][0] + ids["clock"][1][2] / 2
        self.assertLess(abs(cx - W / 2), 4)
        self.assertGreater(ids["clock"][0].properties.get("fontSize"), 28)
        self.assertGreater(ids["ok"][1][0], W * 0.6)
        # The title is kept (small, after the left items) and marked so a
        # recompile finds it again.
        self.assertIn("screenTitle", ids)

    def test_the_card_header_still_moves_only_logos_left(self):
        """A plan without regions keeps the card layout's header: a telltale
        marked "side": "left" stays at the right end as before."""
        W = 1024
        plan = _plan([{"title": "A", "widgets": [_w(TILE, "a")]},
                      {"title": "B", "widgets": [_w(GAUGE, "b")]}],
                     header=[self.HEADER[0]])
        project = _generate(plan, W, 768)
        ids = _by_id(project)
        self.assertGreater(ids["lte"][1][0], W * 0.5)


class Rail(unittest.TestCase):
    def test_a_gear_selector_stands_up_when_the_kit_can(self):
        """With "orientation" declared (wave 6 gate C) the rail's gear selector
        is set vertical and its pill is tall and narrow."""
        import designer.palette.widget_registry as wr
        original = wr.default_registry

        def with_orientation():
            registry = original()
            registry.get("ShGearIndicator").properties.setdefault("orientation", str)
            return registry
        plan = _plan([{"title": "Gear", "region": "rail", "widgets": [
                          {"type": "ShGearIndicator", "id": "gear",
                           "properties": {"gears": "P,R,N,D,L", "gear": "D"}}]},
                      {"title": "Speed", "role": "hero", "region": "left", "widgets": [_w(ARC, "speed")]}])
        with mock.patch("tools.hmi_deployer.ai_generator.default_registry", with_orientation):
            project = _generate(plan)
        gear, (x, y, w, h) = _by_id(project)["gear"]
        self.assertEqual(gear.properties.get("orientation"), "vertical")
        self.assertGreater(h, w * 3)
        pill = _card_of(project, "gear")
        self.assertGreaterEqual(pill.properties.get("radius"), pill.geometry["width"] // 2 - 1)


class Picture(unittest.TestCase):
    def test_a_picture_fills_its_region_under_its_readings(self):
        plan = _plan([{"title": "Truck", "role": "hero", "region": "center", "widgets": [
                          {"type": "Image", "id": "pic", "properties": {"source": ""}},
                          {"type": "ShDataField", "id": "pitch", "properties": {"label": "Pitch", "value": "3"}}]},
                      {"title": "Load", "region": "right", "widgets": [_w(TILE, "load")]}])
        ids = _by_id(_generate(plan))
        pic, pitch = ids["pic"][1], ids["pitch"][1]
        self.assertGreater(pic[1], pitch[1] + pitch[3] - 1, "readings above the picture")
        self.assertGreater(pic[2] * pic[3], 4 * pitch[2] * pitch[3])


if __name__ == "__main__":
    unittest.main()
