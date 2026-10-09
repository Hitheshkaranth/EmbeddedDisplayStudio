"""Fidelity to a reference picture, from live runs of the haul-truck reference.

* a picture's "crop" in the reference is read (fractions or Qwen's 0..1000)
  and the Studio cuts that part of the reference into the bundle's assets;
* untitled sections keep apart through a recompile (two bottom dials of one
  role became one "Instruments" card);
* text printed beside an instrument is its caption, not content that shrinks it.
"""
import copy
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PLAN = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_truck_plan.json")


def _plan():
    with open(PLAN, encoding="utf-8") as fh:
        return json.load(fh)


def _generate(plan, width=1024, height=768):
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator().generate("```json\n" + json.dumps(plan) + "\n```", width, height)


def _walk(widgets, ox=0.0, oy=0.0):
    for w in widgets:
        g = w.geometry
        x, y = ox + float(g.get("x", 0)), oy + float(g.get("y", 0))
        yield w, (x, y, float(g.get("width", 0)), float(g.get("height", 0)))
        yield from _walk(w.children, x, y)


class Crops(unittest.TestCase):
    def test_fractions_and_the_qwen_scale(self):
        from designer.layout.compiler import crop_of
        self.assertEqual(crop_of([0.35, 0.3, 0.69, 0.67]), [0.35, 0.3, 0.69, 0.67])
        self.assertEqual(crop_of([350, 320, 688, 625]), [0.35, 0.32, 0.688, 0.625])
        for bad in (None, [1, 2, 3], ["a", 0, 1, 1], [0.5, 0.5, 0.5, 0.5]):
            self.assertIsNone(crop_of(bad), bad)

    def test_the_picture_is_cut_out_of_the_reference(self):
        QApplication.instance() or QApplication([])
        from designer.layout.compiler import CROP_MARK
        from tools.hmi_deployer.ai_design import encode_brief_image
        from tools.hmi_deployer.ai_tab import fill_pictures, pictures_to_fill
        plan = _plan()
        truck = plan["pages"][0]["sections"][2]["widgets"][0]
        truck["crop"] = [250, 250, 750, 750]
        project = _generate(plan)
        picture = next(w for w, _r in _walk(project.pages[0].widgets) if w.id == "truckPicture")
        self.assertEqual(picture.properties.get(CROP_MARK), [0.25, 0.25, 0.75, 0.75])
        self.assertEqual(pictures_to_fill(project), [picture])
        reference = QImage(400, 200, QImage.Format_RGB32)
        reference.fill(QColor("#22d3ee"))
        with tempfile.TemporaryDirectory() as bundle:
            self.assertEqual(fill_pictures(project, [encode_brief_image(reference, "ref.png")], bundle), 1)
            self.assertEqual(picture.properties["source"], "assets/truckPicture.png")
            cut = QImage(os.path.join(bundle, "assets", "truckPicture.png"))
            self.assertEqual((cut.width(), cut.height()), (200, 100))
        self.assertEqual(pictures_to_fill(project), [])          # filled: not cut twice


class SectionsKeepApart(unittest.TestCase):
    def test_two_untitled_dials_of_one_role_stay_two_through_a_recompile(self):
        from designer.layout.compiler import compile_page
        from designer.palette.widget_registry import default_registry
        plan = _plan()
        for section in plan["pages"][0]["sections"]:
            if section["region"] == "bottom":
                section["title"] = ""                      # as Ornith and Flash wrote them
        project = _generate(plan)
        compile_page(project, project.pages[0], default_registry())
        rects = {w.id: r for w, r in _walk(project.pages[0].widgets)}
        texts = [w.properties.get("text") for w, _r in _walk(project.pages[0].widgets) if w.type == "Text"]
        self.assertNotIn("Instruments", texts, "an untitled block gets no role title")
        self.assertLess(rects["rpm"][0] + rects["rpm"][2], rects["payload"][0] + 2,
                        "RPM and payload are side by side, each in its own section")
        self.assertGreater(min(rects["rpm"][3], rects["payload"][3]), 150, "each dial is large")


class Captions(unittest.TestCase):
    def test_words_beside_a_dial_do_not_shrink_it(self):
        plan = _plan()
        rpm = next(s for s in plan["pages"][0]["sections"] if s["title"] == "RPM")
        rpm["widgets"] += [{"type": "Text", "id": f"note{i}", "properties": {"text": text}}
                           for i, text in enumerate(("RPM", "x1000", "Active level telemetry arcs"))]
        project = _generate(plan)
        rects = {w.id: r for w, r in _walk(project.pages[0].widgets)}
        self.assertGreater(rects["rpm"][3], 150, "the dial keeps its size")
        notes = sorted(rects[f"note{i}"][1] for i in range(3))
        self.assertGreater(notes[0], rects["rpm"][1] + rects["rpm"][3] - 2, "captions sit under the dial")
        for a, b in zip(notes, notes[1:]):
            self.assertGreater(b - a, 8, "caption lines do not overlap")


if __name__ == "__main__":
    unittest.main()
