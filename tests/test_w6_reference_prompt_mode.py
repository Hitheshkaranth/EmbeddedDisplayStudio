"""Wave 6 (agent A) -- the plan prompt's reference mode, beyond the frozen gate:
it explains every compiler region, quotes the colour properties the kit
declares, keeps the brand, and the AI tab stays on the plain prompt when no
picture goes with the brief.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ReferenceModeText(unittest.TestCase):
    def setUp(self):
        from tools.hmi_deployer.ai_generator import build_plan_prompt
        self.build = build_plan_prompt
        self.prompt = build_plan_prompt(None, 1024, 768, brief="like the picture", reference=True)

    def test_every_region_is_explained(self):
        from designer.layout.compiler import REGIONS
        from tools.hmi_deployer.ai_generator import REFERENCE_REGION_GUIDE
        for region in REGIONS:
            self.assertIn(region, REFERENCE_REGION_GUIDE)
            self.assertIn(f'- "{region}": {REFERENCE_REGION_GUIDE[region]}', self.prompt)

    def test_the_catalogue_quotes_colour_properties(self):
        from designer.palette.widget_registry import default_registry
        speed = default_registry().get("ShSpeedArc")
        self.assertIn("colours: " + ", ".join(speed.color_properties), self.prompt)

    def test_the_header_and_picture_rules(self):
        for phrase in ('"side": "left"', '"clock"', "<area>.clock", "ShStatDot",
                       '"gears": "P,R,N,D,L"', '"orientation": "vertical"', '"axles": 3',
                       "accentColor", "barColor", '"source": ""', '"accent"'):
            self.assertIn(phrase, self.prompt)

    def test_the_brand_still_reaches_the_reference_prompt(self):
        prompt = self.build(None, 1024, 768, brief="x", reference=True,
                            brand={"logos": ["assets/acme.png"], "accent": "#ff6600"})
        self.assertIn("assets/acme.png", prompt)
        self.assertIn("#ff6600", prompt)

    def test_the_plain_prompt_ignores_the_flag_default(self):
        self.assertEqual(self.build(None, 800, 480, brief="pump skid"),
                         self.build(None, 800, 480, brief="pump skid", reference=False))


class TabWithoutPictures(unittest.TestCase):
    def test_no_picture_keeps_the_plain_prompt(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from tools.hmi_deployer.ai_design import BYOK_PRESETS, ODConnector, ProviderConfig
        from tools.hmi_deployer.ai_tab import AIDesignTab
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        tab.connector = ODConnector(mode="byok", byok=ProviderConfig.from_dict(
            dict(BYOK_PRESETS["ornith"], provider="ornith", apiKey="k", model="m")))
        tab.model_combo.setEditText("m")
        tab.brief_input.setPlainText("pump skid with two pumps")
        with mock.patch("tools.hmi_deployer.ai_tab.GenerationWorker") as worker:
            worker.return_value.event = mock.MagicMock()
            worker.return_value.finished = mock.MagicMock()
            tab._on_send()
        self.assertNotIn('"rail"', tab.connector.system_prompt)
        self.assertIn("Never write x, y, width, height or any geometry", tab.connector.system_prompt)


if __name__ == "__main__":
    unittest.main()
