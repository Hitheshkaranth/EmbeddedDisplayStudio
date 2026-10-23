"""QML formatted numeric text follows the native bind.c decimal contract."""
import unittest

from designer.generators.qml_generator import QmlGenerator
from designer.model import DesignerBinding, DesignerProject
from designer.palette import default_registry


class NumericFormattingTests(unittest.TestCase):
    def setUp(self):
        self.generator = QmlGenerator(default_registry())

    def test_format_keeps_requested_decimals_after_scaling(self):
        binding = DesignerBinding("sim.temperature", decimals=2, multiplier=.1,
                                  offset=3, format="Temperature %1 C")
        expression = self.generator._value_expression(binding)
        self.assertEqual(expression,
                         '"Temperature %1 C".arg(Number(((Bus.value("sim.temperature", 0) * 0.1) + 3)).toFixed(2))')

    def test_numeric_properties_stay_numeric(self):
        binding = DesignerBinding("sim.pressure", decimals=2)
        self.assertNotIn("toFixed", self.generator._value_expression(binding))
        self.assertIn("toFixed(2)", self.generator._value_expression(binding, text_property=True))

    def test_automatic_precision_unchanged(self):
        binding = DesignerBinding("sim.pressure", format="%1 bar")
        self.assertEqual(self.generator._value_expression(binding),
                         '"%1 bar".arg(Bus.value("sim.pressure", 0))')

    def test_generated_text_uses_fixed_precision(self):
        project = DesignerProject.from_dict({"pages": [{"id": "main", "widgets": [{
            "id": "reading", "type": "Text", "properties": {"text": "5.00"},
            "bindings": {"text": {"tag": "sim.pressure", "decimals": 2}}}]}]})
        output = "\n".join(self.generator.generate(project).values())
        self.assertIn('Number(Bus.value("sim.pressure", "")).toFixed(2)', output)
