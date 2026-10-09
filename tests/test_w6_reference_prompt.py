"""Wave 6 gate A -- with a reference picture attached, AI Design asks the
model to reproduce it: every block, where it sits, which widget, its colours.
FROZEN (skeleton).
"""
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RECORDED = os.path.join(ROOT, "tests", "fixtures", "ai", "reference_truck_ornith.json")


class ReferencePrompt(unittest.TestCase):
    def test_the_reference_mode_names_regions_widgets_and_colours(self):
        from tools.hmi_deployer.ai_generator import build_plan_prompt
        prompt = build_plan_prompt(None, 1024, 768, brief="like the picture", reference=True)
        for region in ("top", "rail", "left", "center", "right", "bottom"):
            self.assertIn(f'"{region}"', prompt)
        for widget in ("ShGearIndicator", "ShVehicleStatus", "ShCompass", "ShAttitude",
                       "ShEngineBar", "ShSpeedArc", "ShClusterGauge", "Image"):
            self.assertIn(widget, prompt)
        self.assertIn('"region"', prompt)
        self.assertIn("colour", prompt.lower())
        self.assertNotIn("Never write x, y, width, height or any geometry, colours", prompt)

    def test_without_a_picture_the_prompt_is_unchanged(self):
        from tools.hmi_deployer.ai_generator import build_plan_prompt
        prompt = build_plan_prompt(None, 1024, 768, brief="pump skid")
        self.assertNotIn('"rail"', prompt)
        self.assertIn("Never write x, y, width, height or any geometry", prompt)

    def test_the_ai_tab_asks_for_the_reference_mode_when_images_go(self):
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tools.hmi_deployer.ai_design import BYOK_PRESETS, ODConnector, ProviderConfig
        from tools.hmi_deployer.ai_tab import AIDesignTab
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        tab.connector = ODConnector(mode="byok", byok=ProviderConfig.from_dict(
            dict(BYOK_PRESETS["ornith"], provider="ornith", apiKey="k", model="m")))
        tab.model_combo.setEditText("m")
        image = QImage(40, 20, QImage.Format_RGB32)
        image.fill(QColor("#123456"))
        tab.add_images([image])
        with mock.patch("tools.hmi_deployer.ai_tab.GenerationWorker") as worker:
            worker.return_value.event = mock.MagicMock()
            worker.return_value.finished = mock.MagicMock()
            tab._on_send()
        self.assertIn('"rail"', tab.connector.system_prompt)

    def test_the_recorded_ornith_plan_for_the_truck_compiles_by_region(self):
        self.assertTrue(os.path.isfile(RECORDED), "record Ornith's plan for the truck reference")
        with open(RECORDED, encoding="utf-8") as fh:
            recorded = json.load(fh)
        reply = recorded["reply"]
        from designer.layout.compiler import REGION_MARK
        from tools.hmi_deployer.ai_generator import AIDesignGenerator
        project = AIDesignGenerator().generate(reply, 1024, 768)

        def walk(ws):
            for w in ws:
                yield w
                yield from walk(w.children)

        widgets = list(walk(project.pages[0].widgets))
        regions = {w.properties.get(REGION_MARK) for w in widgets} - {None, ""}
        self.assertGreaterEqual(len(regions), 4, regions)
        types = {w.type for w in widgets}
        for wanted in ("ShGearIndicator", "ShSpeedArc"):
            self.assertIn(wanted, types)
        self.assertGreaterEqual(len({w.type for w in widgets} & {
            "ShVehicleStatus", "ShCompass", "ShAttitude", "ShEngineBar", "ShClusterGauge"}), 3)


if __name__ == "__main__":
    unittest.main()
