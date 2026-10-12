"""A plan written as one flat list of plain widget words.

Ornith, asked for an engine dashboard, ignored the plan format: one page,
widgets typed "gauge", "bar", "button", "status", each tag under "bound",
no sections and no positions. Every widget came out an empty Rectangle in a
grid of equal boxes. It is read now: the words become kit widgets, the tag
binds the widget, and the list is grouped into cards around the dial the
brief calls large.
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

RECORDED = os.path.join(ROOT, "tests", "fixtures", "ai", "engine_ornith_flat.json")


def _generate(path=RECORDED):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    with open(path, encoding="utf-8") as fh:
        recorded = json.load(fh)
    gen = AIDesignGenerator()
    gen.brief = recorded["brief"]
    return gen.generate(recorded["reply"], 1024, 768)


class FlatReply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])
        cls.project = _generate()
        cls.widgets = {w.id: w for w in cls.project.all_widgets()}

    def test_plain_words_are_kit_widgets(self):
        types = {i: self.widgets[i].type for i in ("rpmGauge", "coolantTempGauge", "oilTempGauge",
                                                     "fuelLevelBar", "startStopButton", "statusStrip")}
        self.assertEqual(types, {"rpmGauge": "ShGauge", "coolantTempGauge": "ShGauge",
                                 "oilTempGauge": "ShGauge", "fuelLevelBar": "ShEngineBar",
                                 "startStopButton": "ShButton", "statusStrip": "ShStatusRow"})

    def test_a_tag_beside_the_widget_binds_it(self):
        rpm = self.widgets["rpmGauge"]
        self.assertEqual(rpm.bindings["value"].tag, "eng.rpm")
        self.assertEqual(rpm.bindings["value"].unit, "rpm")
        self.assertEqual(rpm.bindings["value"].warning, "> 6500")
        self.assertEqual(rpm.properties.get("thresholdWarning"), 6500)
        self.assertEqual(rpm.properties.get("maximum"), 8000)
        self.assertEqual(self.widgets["coolantTempGauge"].bindings["value"].tag, "eng.coolant_c")
        self.assertEqual(self.widgets["fuelLevelBar"].bindings["value"].tag, "eng.fuel_level")

    def test_the_large_dial_leads_in_its_own_card(self):
        rpm = self.widgets["rpmGauge"]
        others = [self.widgets[i] for i in ("coolantTempGauge", "oilTempGauge")]
        area = lambda w: float(w.geometry["width"]) * float(w.geometry["height"])
        self.assertTrue(all(area(rpm) > 4 * area(o) for o in others))
        cards = [w for w in self.project.pages[0].widgets if w.type == "ShCard"]
        self.assertGreaterEqual(len(cards), 3)
        held = {c.id: {k.id for k in c.children} for c in cards}
        self.assertTrue(any("statusStrip" in ids for ids in held.values()), "the status strip is kept")

    def test_nothing_is_left_an_empty_rectangle(self):
        empty = [w.id for w in self.project.all_widgets() if w.type == "Rectangle"
                 and not w.children and float(w.geometry.get("height", 0)) > 2]
        self.assertEqual(empty, [])


class SectionedReply(unittest.TestCase):
    """The same brief once the schema closed the page: sections, but plain
    words, tags under "bind" and every dial in a card of its own."""

    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])
        cls.project = _generate(RECORDED.replace("flat", "sections"))
        cls.widgets = {w.id: w for w in cls.project.all_widgets()}

    def test_the_large_dial_leads(self):
        page = self.project.pages[0]
        first = next(w for w in page.widgets if w.type == "ShCard")
        self.assertIn("rpm_gauge", [c.id for c in first.children])
        size = lambda i: float(self.widgets[i].geometry["width"])
        self.assertGreater(size("rpm_gauge"), size("coolant_temp_gauge"))

    def test_buttons_write_their_tags(self):
        for wid, tag in (("start_button", "eng.start"), ("stop_button", "eng.stop")):
            action = self.widgets[wid].actions["clicked"]
            self.assertEqual((action.kind, action.tag, action.value), ("write", tag, True))

    def test_a_band_is_its_start(self):
        rpm = self.widgets["rpm_gauge"]
        self.assertEqual(rpm.bindings["value"].warning, "> 6500")
        self.assertEqual(rpm.properties.get("thresholdWarning"), 6500)


class Schema(unittest.TestCase):
    def test_a_page_is_closed_and_has_sections(self):
        from tools.hmi_deployer.ai_generator import PLAN_SCHEMA
        page = PLAN_SCHEMA["properties"]["pages"]["items"]
        self.assertFalse(page["additionalProperties"])
        self.assertEqual(page["required"], ["sections"])
        self.assertNotIn("widgets", page["properties"])


class LooseNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QApplication.instance() or QApplication([])
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        cls.gen = AIDesignGenerator()

    def test_names(self):
        resolve = self.gen._resolve_type
        for name, expected in (("Gauge", "ShGauge"), ("gauge", "ShGauge"), ("ShGauge", "ShGauge"),
                               ("status_strip", "ShStatusRow"), ("push-button", "ShButton"),
                               ("trendChart", "ShTrendChart"), ("fuelLevelBar", "ShAutoLevel"),
                               ("rpmGauge", "ShGauge"), ("ShLamp", "ShStatDot"),
                               ("arrow", "Rectangle"), ("whatever", "Rectangle"), ("", "Rectangle"),
                               (None, "Rectangle")):
            self.assertEqual(resolve(name), expected, name)

    def test_only_a_dotted_tag_binds(self):
        from tools.hmi_deployer.ai_generator import _shorthand_binding
        self.assertIsNone(_shorthand_binding({"type": "button", "signal": "start"}))
        self.assertIsNone(_shorthand_binding({"tag": 7}))
        self.assertEqual(_shorthand_binding({"tag": "Eng.RPM"}).tag, "eng.rpm")
        self.assertEqual(_shorthand_binding({"bound": "eng.oil_c", "critical": 140}).critical, "> 140")

    def test_placed_widgets_keep_their_positions(self):
        reply = json.dumps({"pages": [{"id": "main", "widgets": [
            {"type": "gauge", "id": "a", "geometry": {"x": 500, "y": 300, "width": 200, "height": 200}}]}]})
        self.gen.polish_enabled = False
        try:
            project = self.gen.generate(reply, 1024, 768)
        finally:
            self.gen.polish_enabled = True
        widget = next(w for w in project.all_widgets() if w.id == "a")
        self.assertEqual(widget.type, "ShGauge")
        self.assertEqual((widget.geometry["x"], widget.geometry["y"]), (500, 300))


if __name__ == "__main__":
    unittest.main()
