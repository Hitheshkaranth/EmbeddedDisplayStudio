"""Wave 5 B2 gate -- the Designer and simulation.

* drop an image file on the canvas: copied into the bundle, an Image placed;
* the project's brand (logos, accent) is saved with the design, offered to
  AI Design, and the cab layout takes its accent;
* a binding may say what it simulates as ("sim"), and tagsim obeys;
* tagsim notices a newly deployed design without a restart;
* Tag Lab can drive the open design from the same simulator;
* the panel mirror's rate is a setting.
FROZEN (skeleton).
"""
import json
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from test_layout_cab import PLAN as CAB_PLAN, _reply  # noqa: E402


def _png(path, colour="#ff0000"):
    img = QImage(40, 20, QImage.Format_ARGB32)
    img.fill(QColor(colour))
    img.save(path)
    return path


class Workspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from designer.ui.designer_workspace import DesignerWorkspace
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.deleteLater)
        self.ws.projects_root = self.dir.name
        self.ws.ensure_bundle()

    def test_a_dropped_image_file_becomes_an_image(self):
        src = _png(os.path.join(self.dir.name, "Company Logo.png"))
        model = self.ws.drop_image_file(src, 120, 40)
        self.assertIsNotNone(model)
        self.assertEqual(model.type, "Image")
        self.assertEqual(model.properties["source"], "assets/company_logo.png")
        self.assertTrue(os.path.isfile(os.path.join(self.ws.bundle_dir, "assets", "company_logo.png")))
        self.assertEqual((model.geometry["x"], model.geometry["y"]), (120, 40))
        self.assertIn(model, list(self.ws.current_page.walk()))
        self.ws.undo_stack.undo()                              # one undo step
        self.assertNotIn(model, list(self.ws.current_page.walk()))
        self.assertIsNone(self.ws.drop_image_file(os.path.join(self.dir.name, "notes.txt"), 0, 0))

    def test_the_brand_is_saved_with_the_design(self):
        src = _png(os.path.join(self.dir.name, "acme.png"))
        self.ws.set_brand(logos=[src], accent="#22c55e")
        self.assertEqual(self.ws.project.brand, {"logos": ["assets/acme.png"], "accent": "#22c55e"})
        self.ws.save()
        with open(self.ws.file_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["brand"]["accent"], "#22c55e")
        from designer.model import DesignerProject
        self.assertEqual(DesignerProject.from_dict(data).brand["logos"], ["assets/acme.png"])
        plain = DesignerProject.from_dict({"version": 1, "name": "x", "screen": {"width": 800, "height": 480},
                                           "pages": []})
        self.assertNotIn("brand", plain.to_dict())             # old designs unchanged on disk


class BrandInAi(unittest.TestCase):
    def test_the_prompt_offers_the_brand_and_the_cab_takes_its_accent(self):
        from tools.hmi_deployer.ai_generator import AIDesignGenerator, build_plan_prompt
        prompt = build_plan_prompt(None, 1024, 768, "metro cab display",
                                   brand={"logos": ["assets/acme.png"], "accent": "#22c55e"})
        self.assertIn("assets/acme.png", prompt)
        gen = AIDesignGenerator()
        gen.brand = {"logos": [], "accent": "#22c55e"}
        project = gen.generate(_reply(CAB_PLAN), 1024, 768)
        title = next(w for w in project.pages[0].walk() if w.id == "screenTitle")
        self.assertEqual(title.properties["color"], "#22c55e")


class SimRoles(unittest.TestCase):
    def test_a_binding_carries_its_sim_role(self):
        from designer.model import DesignerBinding
        b = DesignerBinding.from_data({"tag": "plc.r40001", "sim": "rail_next"})
        self.assertEqual(b.sim, "rail_next")
        self.assertEqual(b.to_dict()["sim"], "rail_next")
        self.assertNotIn("sim", DesignerBinding(tag="x").to_dict())

    def test_tagsim_obeys_the_role(self):
        from daemon import tagsim
        roles = dict(tagsim.SIM_ROLES)
        self.assertIn("rail_next", roles)
        self.assertIn("altitude", roles)
        project = {"pages": [{"id": "main", "widgets": [
            {"type": "ShStationLine", "id": "l", "properties": {"stations": "A,B,C,D"},
             "bindings": {"current": {"tag": "plc.r1"}}},
            {"type": "Text", "id": "t", "bindings": {"text": {"tag": "plc.r40001", "sim": "rail_next"}}},
            {"type": "ShGauge", "id": "g", "bindings": {"value": {"tag": "plc.r2", "sim": "altitude"}}}]}]}
        values = tagsim.values_at(tagsim.plan(project), 10.0, 240.0)
        self.assertEqual(values["plc.r40001"], "B")
        self.assertIsInstance(values["plc.r2"], float)


class TagsimWatch(unittest.TestCase):
    def test_a_new_design_is_noticed(self):
        from daemon import tagsim
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "project.edsui")
            with open(path, "w") as fh:
                json.dump({"pages": [{"widgets": [{"type": "ShGauge", "id": "g",
                                                   "bindings": {"value": {"tag": "a.one"}}}]}]}, fh)
            watch = tagsim.ProjectWatch(path)
            self.assertEqual(sorted(watch.signals()), ["a.one"])
            self.assertFalse(watch.changed())
            time.sleep(0.05)
            with open(path, "w") as fh:
                json.dump({"pages": [{"widgets": [{"type": "ShGauge", "id": "g",
                                                   "bindings": {"value": {"tag": "b.two"}}}]}]}, fh)
            os.utime(path, (time.time() + 5, time.time() + 5))
            self.assertTrue(watch.changed())
            self.assertEqual(sorted(watch.signals()), ["b.two"])


class TagLabDesign(unittest.TestCase):
    def test_tag_lab_drives_the_design_from_the_simulator(self):
        from tools.hmi_deployer.taglab import design_simulation_frame
        project = {"pages": [{"widgets": [
            {"type": "ShStationLine", "id": "l", "properties": {"stations": "A,B,C,D"},
             "bindings": {"current": {"tag": "train.station_index"}}},
            {"type": "Text", "id": "n", "bindings": {"text": {"tag": "train.next_station"}}}]}]}
        frame = design_simulation_frame(project, 10.0)
        self.assertEqual(frame["train.next_station"], "B")
        self.assertIn(frame["train.station_index"], (0, 1))


class MirrorRate(unittest.TestCase):
    def test_the_rate_is_a_choice_of_frames_per_second(self):
        from tools.hmi_deployer.panel_mirror import MIRROR_RATES, interval_for_fps
        self.assertEqual(MIRROR_RATES, (1, 2, 4))
        self.assertEqual(interval_for_fps(1), 1000)
        self.assertEqual(interval_for_fps(4), 250)
        self.assertEqual(interval_for_fps(99), 250)            # clamped to the fastest offered


if __name__ == "__main__":
    unittest.main()
