"""Wave 6 contract -- a plan that follows a reference picture says where each
section sits (compiler.REGIONS), and that survives a recompile.
FROZEN (skeleton): the reference-design agents build on this.
"""
import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLAN = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_truck_plan.json")


def reference_project(width=1024, height=768):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    with open(PLAN, encoding="utf-8") as fh:
        reply = "```json\n" + fh.read() + "\n```"
    return AIDesignGenerator().generate(reply, width, height)


class Regions(unittest.TestCase):
    def test_region_names_and_what_models_write(self):
        from designer.layout.compiler import REGIONS, region_of
        self.assertEqual(REGIONS, ("top", "rail", "left", "center", "right", "bottom"))
        for written, region in (("Centre", "center"), ("right column", "right"), ("header", "top"),
                                ("left-rail", "rail"), ("Footer", "bottom"), ("LEFT", "left"),
                                ("", ""), ("somewhere", "")):
            self.assertEqual(region_of(written), region, written)

    def test_the_plan_keeps_each_sections_region(self):
        from designer.layout.compiler import sections_from_plan
        with open(PLAN, encoding="utf-8") as fh:
            page = json.load(fh)["pages"][0]
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        _title, sections, _header = sections_from_plan(page, AIDesignGenerator()._convert_widgets)
        self.assertEqual([s.region for s in sections],
                         ["rail", "left", "center", "bottom", "bottom", "right", "right", "right", "right"])

    def test_the_region_is_marked_on_the_widgets_and_read_back(self):
        from designer.layout.compiler import REGION_MARK, infer_sections
        from designer.palette.widget_registry import default_registry
        project = reference_project()
        page = project.pages[0]

        def walk(widgets):
            for w in widgets:
                yield w
                yield from walk(w.children)

        marked = {w.id: w.properties.get(REGION_MARK) for w in walk(page.widgets)
                  if w.properties.get(REGION_MARK)}
        self.assertEqual(marked.get("gear"), "rail")
        self.assertEqual(marked.get("tires"), "right")
        _t, sections, _h, _n = infer_sections(page, default_registry())
        regions = {s.title: s.region for s in sections}
        self.assertEqual(regions.get("Vitals"), "right")
        self.assertEqual(regions.get("Gear"), "rail")


if __name__ == "__main__":
    unittest.main()
