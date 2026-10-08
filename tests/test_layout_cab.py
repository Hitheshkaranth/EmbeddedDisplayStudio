"""tests/test_layout_cab.py -- a planned train screen comes out as a cab display.

designer/layout/cab.py lays out a plan that holds the Rail widgets the way
drivers read a cab display: line and train across the top, speed left, route
and the next station in the middle, the train on the right. The plan below
is the shape ornith-1.5 returned for the Purple Line brief (2026-10-08),
including its slips: a car count instead of car names, a progress in percent,
a "current station" tile beside the station line, and one closing brace too
many after the speed arc.
"""
import copy
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from designer.layout import cab, compiler, intake  # noqa: E402

STATIONS = "Trinity, Halasuru, Indiranagar, Swami Vivekananda Road, Whitefield (Kadugodi)"

PLAN = {"name": "purple-line-cab", "pages": [{
    "id": "main", "name": "Main", "title": "Purple Line - P-412",
    "header": [
        {"type": "ShDataField", "id": "trainId", "properties": {"label": "Train", "value": "P-412"}},
        {"type": "ShDataField", "id": "obstacle", "properties": {"label": "Obstacle Detection", "value": "Active"}},
        {"type": "ShDataField", "id": "signalling", "properties": {"label": "Signalling", "value": "ATP"}},
        {"type": "ShDataField", "id": "doorState", "properties": {"label": "Doors", "value": "Closed"},
         "bindings": {"value": {"tag": "train.doors"}}},
        {"type": "Text", "id": "clock", "properties": {"text": "14:23"}, "bindings": {"text": {"tag": "train.clock"}}}],
    "sections": [
        {"title": "Drive", "role": "hero", "widgets": [
            {"type": "ShSpeedArc", "id": "speedArc", "properties": {"value": 64, "maximumValue": 100, "unit": "km/h"},
             "bindings": {"value": {"tag": "train.speed"}, "target": {"tag": "train.target_speed"}}},
            {"type": "ShTractionBar", "id": "tractionBar", "properties": {"title": "Traction / Brake", "value": 65},
             "bindings": {"value": {"tag": "train.traction_pct"}}},
            {"type": "ShValueTile", "id": "lineVoltage", "properties": {"title": "Line Voltage", "value": "752", "unit": "V"},
             "bindings": {"value": {"tag": "train.line_voltage"}}},
            {"type": "ShValueTile", "id": "atcMode", "properties": {"title": "ATC Mode", "value": "ATP/ATO"}}]},
        {"title": "Route", "role": "readings", "widgets": [
            {"type": "ShStationLine", "id": "stationLine", "properties": {"stations": STATIONS, "current": 1},
             "bindings": {"current": {"tag": "train.station_index"}, "details": {"tag": "train.station_details"}}},
            {"type": "ShValueTile", "id": "currentStation", "properties": {"title": "Current Station", "value": "Halasuru"},
             "bindings": {"value": {"tag": "train.station_name"}}}]},
        {"title": "Next Station", "role": "readings", "widgets": [
            {"type": "ShValueTile", "id": "nextStation", "properties": {"title": "Next Station", "value": "Indiranagar"},
             "bindings": {"value": {"tag": "train.next_station"}}},
            {"type": "ShValueTile", "id": "eta", "properties": {"title": "Arrival", "value": "1m 45s"},
             "bindings": {"value": {"tag": "train.eta"}}},
            {"type": "ShValueTile", "id": "distance", "properties": {"title": "Distance to Go", "value": "1.1", "unit": "km"},
             "bindings": {"value": {"tag": "train.distance_to_go"}}},
            {"type": "ShProgress", "id": "hop", "properties": {"value": 45},
             "bindings": {"value": {"tag": "train.segment_progress"}}}]},
        {"title": "Train", "role": "status", "widgets": [
            {"type": "ShTrainConsist", "id": "consist", "properties": {"cars": 6, "leftLabel": "Left"},
             "bindings": {"doorsLeft": {"tag": "train.doors_left"}}},
            {"type": "ShStatusCard", "id": "hvac", "properties": {"icon": "snowflake", "title": "HVAC", "status": "Running"}},
            {"type": "ShStatusCard", "id": "pa", "properties": {"icon": "volume", "title": "PA System", "status": "On"}},
            {"type": "ShStatusCard", "id": "pea", "properties": {"icon": "bell", "title": "Passenger Emergency Alarm",
                                                                 "status": "Normal"}},
            {"type": "ShTelltale", "id": "stopMark", "properties": {"icon": "align-center", "label": "Stop Marking Aligned"}}]}]}]}


def _reply(design, extra_brace=False) -> str:
    text = json.dumps(design)
    if extra_brace:
        # ornith's slip: `}}}}]}` where `}}}]}` closes the speed arc's widget.
        marker = '"train.target_speed"}}}'
        text = text.replace(marker, marker + "}", 1)
    return "```json\n" + text + "\n```"


def _by_id(page):
    return {w.id: w for w in compiler._walk(page.widgets)}


class CabLayoutTest(unittest.TestCase):
    def setUp(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        self.generator = AIDesignGenerator()
        self.registry = self.generator.registry

    def _page(self, design=PLAN, size=(1024, 768), extra_brace=False):
        project = self.generator.generate(_reply(design, extra_brace), *size)
        self.assertIsNotNone(project)
        return project, project.pages[0]

    def test_a_rail_plan_is_laid_out_as_a_cab_display(self):
        _project, page = self._page()
        self.assertEqual(self.generator.last_compile[0].layout, "cab display")
        w = _by_id(page)
        # Speed left, route middle, train right.
        self.assertLess(w["speedArc"].geometry["x"], 340)
        self.assertTrue(340 < w["stationLine"].geometry["x"] < 690)
        self.assertGreater(w["consist"].geometry["x"], 690)
        self.assertGreater(w["hvac"].geometry["x"], w["consist"].geometry["x"])

    def test_the_header_names_the_line_in_its_colour(self):
        _project, page = self._page()
        title = _by_id(page)["screenTitle"]
        self.assertEqual(title.properties["text"], "PURPLE LINE - P-412")
        self.assertEqual(title.properties["color"], "#a855f7")
        self.assertEqual(_by_id(page)["clock"].bindings["text"].tag, "train.clock")
        self.assertEqual(_by_id(page)["clock"].properties["horizontalAlignment"], "Text.AlignRight")

    def test_the_next_station_leads_its_card_and_keeps_its_binding(self):
        _project, page = self._page()
        name = _by_id(page)["nextStation"]
        self.assertEqual(name.type, "Text")
        self.assertEqual(name.properties["text"], "Indiranagar")
        self.assertEqual(name.bindings["text"].tag, "train.next_station")
        labels = [w.properties.get("text") for w in compiler._walk(page.widgets) if w.type == "Text"]
        self.assertIn("NEXT:", labels)
        self.assertIn("ARRIVAL:", labels)
        self.assertIn("DISTANCE TO GO:", labels)
        self.assertNotIn("currentStation", _by_id(page))      # the line already shows it

    def test_model_slips_are_put_right(self):
        _project, page = self._page()
        w = _by_id(page)
        self.assertEqual(w["consist"].properties["cars"], "MC1,M1,T1,T2,M2,MC2")
        self.assertEqual(w["consist"].properties["leftLabel"], "DOORS L")
        self.assertAlmostEqual(w["hop"].properties["value"], 0.45)
        self.assertEqual(w["tractionBar"].properties["title"], "T/B")
        self.assertEqual(w["pea"].properties["title"], "PEA\n(Emergency Alarm)")
        self.assertEqual(w["stopMark"].properties["icon"], "check")

    def test_one_brace_too_many_loses_nothing(self):
        _project, page = self._page(extra_brace=True)
        w = _by_id(page)
        for wid in ("speedArc", "stationLine", "nextStation", "consist", "pea"):
            self.assertIn(wid, w)

    def test_a_whole_line_becomes_a_window_round_the_next_station(self):
        design = copy.deepcopy(PLAN)
        line = design["pages"][0]["sections"][1]["widgets"][0]
        line["properties"]["stations"] = ("Challaghatta, Kengeri, Mysuru Road, Magadi Road, Majestic, "
                                          "MG Road, Trinity, Halasuru, Indiranagar, "
                                          "Swami Vivekananda Road, Baiyappanahalli, Whitefield (Kadugodi)")
        _project, page = self._page(design)
        stations = _by_id(page)["stationLine"].properties["stations"].split(",")
        self.assertLessEqual(len(stations), 6)
        self.assertIn("Indiranagar", stations)
        self.assertEqual(stations[-1], "Whitefield (Kadugodi)")

    def test_recompiling_gives_the_same_screen(self):
        project, page = self._page()
        before = [(w.id, w.type, dict(w.geometry)) for w in page.widgets]
        compiler.compile_page(project, page, self.registry)
        after = [(w.id, w.type, dict(w.geometry)) for w in page.widgets]
        self.assertEqual(before, after)

    def test_a_logo_dropped_into_the_header_is_placed_by_tidy_up(self):
        from designer.model import DesignerWidget
        project, page = self._page()
        for wid, x in (("nammaLogo", 20), ("datasolLogo", 930)):
            page.widgets.append(DesignerWidget(type="Image", id=wid,
                                               geometry={"x": x, "y": 12, "width": 80, "height": 40},
                                               properties={"source": f"assets/{wid}.png"}))
        compiler.compile_page(project, page, self.registry)
        w = _by_id(page)
        self.assertLess(w["nammaLogo"].geometry["x"], w["screenTitle"].geometry["x"])
        self.assertGreater(w["datasolLogo"].geometry["x"], w["clock"].geometry["x"])
        self.assertIn("nammaLogoPlate", w)
        # ... and stays there on the next Tidy up.
        before = [(x.id, dict(x.geometry)) for x in page.widgets]
        compiler.compile_page(project, page, self.registry)
        self.assertEqual(before, [(x.id, dict(x.geometry)) for x in page.widgets])

    def test_what_is_always_live_is_bound_even_when_the_plan_forgot(self):
        design = copy.deepcopy(PLAN)
        sections = design["pages"][0]["sections"]
        for widget in sections[2]["widgets"]:          # next station, ETA, distance, hop
            widget.pop("bindings", None)
        _project, page = self._page(design)
        w = _by_id(page)
        self.assertEqual(w["nextStation"].bindings["text"].tag, "train.next_station")
        self.assertEqual(w["eta"].bindings["text"].tag, "train.eta")
        self.assertEqual(w["distance"].bindings["text"].tag, "train.distance_to_go")
        self.assertEqual(w["hop"].bindings["value"].tag, "train.segment_progress")
        # A reading that is not live on every cab stays as the plan had it.
        self.assertNotIn("text", w["atcMode"].bindings)

    def test_other_screens_keep_their_own_layout(self):
        sections = [compiler.Section("Flow", "hero", [])]
        self.assertFalse(cab.applies(sections))

    def test_a_larger_screen_scales_the_cab(self):
        _project, page = self._page(size=(1280, 960))
        self.assertGreater(_by_id(page)["consist"].geometry["x"], 860)


class RailPromptTest(unittest.TestCase):
    def test_a_train_brief_gets_the_cab_guide(self):
        from tools.hmi_deployer.ai_generator import build_plan_prompt
        rail = build_plan_prompt(None, 1024, 768, "Metro driver cab display for the Purple Line")
        pump = build_plan_prompt(None, 1024, 768, "Pump station overview with two pumps")
        self.assertIn("ShTrainConsist", rail)
        self.assertIn("driver cab display", rail)
        self.assertNotIn("driver cab display", pump)


class StrayCloserTest(unittest.TestCase):
    def test_one_closer_too_many_inside_a_list_is_dropped(self):
        text = '{"widgets": [{"a": {"b": 1}}}, {"c": 2}], "title": "T"}'
        data = intake.loads_lenient(text)
        self.assertEqual(len(data["widgets"]), 2)
        self.assertEqual(data["title"], "T")


if __name__ == "__main__":
    unittest.main()
