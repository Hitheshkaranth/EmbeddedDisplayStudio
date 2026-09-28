"""Wave 1 gate for W2 (FROZEN): CONTRACT 13.2 in the Designer -- the
expression language (shared table with expr.c), binding validation and tags,
and the inspector's BindingExtras."""
import json
import math
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget  # noqa: E402

from designer.model import DesignerBinding, DesignerProject, DesignerWidget  # noqa: E402
from designer.model.binding_v2 import binding_tags, validate_binding  # noqa: E402
from designer.model.expr import ExprError, compile_expr, truthy  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from designer.ui.binding_extras import BindingExtras  # noqa: E402

CASES = json.loads((REPO_ROOT / "tests" / "fixtures" / "expr_cases.json").read_text(encoding="utf-8"))


class ExpressionTable(unittest.TestCase):
    def test_every_row(self):
        self.assertGreater(len(CASES), 90)
        for row in CASES:
            with self.subTest(expr=row["expr"][:60]):
                if row.get("error"):
                    with self.assertRaises(ExprError):
                        compile_expr(row["expr"])
                    continue
                got = compile_expr(row["expr"]).evaluate(row["values"])
                want = row["expect"]
                if isinstance(want, bool) or want is None or isinstance(want, str):
                    self.assertEqual(got, want)
                    self.assertIs(type(got), type(want))
                else:
                    self.assertIsInstance(got, float)
                    self.assertTrue(math.isclose(got, want, abs_tol=1e-9), (got, want))

    def test_tags_in_first_appearance_order(self):
        self.assertEqual(compile_expr("b.x + a.y * b.x - c.z").tags, ("b.x", "a.y", "c.z"))

    def test_error_text_is_one_line(self):
        with self.assertRaises(ExprError) as ctx:
            compile_expr("sqrt(4)")
        self.assertTrue(str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_truthy(self):
        self.assertFalse(truthy("false"))
        self.assertTrue(truthy(0.1))


class Binding(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.tile = DesignerWidget("ShValueTile", "tile", {"x": 0, "y": 0, "width": 200, "height": 100})
        self.definition = self.registry.get("ShValueTile")

    def issues(self, binding, prop="value"):
        return [i.message for i in validate_binding(binding, prop, self.tile, self.definition, "p")]

    def test_tags(self):
        self.assertEqual(binding_tags(DesignerBinding("a.b")), {"a.b"})
        self.assertEqual(binding_tags(DesignerBinding("", expr="e.a + e.b * e.a")), {"e.a", "e.b"})
        self.assertEqual(binding_tags(DesignerBinding("x.y", expr="z.w > 1")), {"x.y", "z.w"})
        self.assertEqual(binding_tags(DesignerBinding("", expr="1 +")), set())

    def test_decimals(self):
        self.assertEqual(self.issues(DesignerBinding("a.b", decimals=7)), ["decimals must be -1..6"])
        self.assertEqual(self.issues(DesignerBinding("a.b", decimals=-2)), ["decimals must be -1..6"])
        self.assertEqual(self.issues(DesignerBinding("a.b", decimals=3)), [])

    def test_expr(self):
        (msg,) = self.issues(DesignerBinding("", expr="sqrt(1)"))
        self.assertTrue(msg.startswith("expression: "))
        self.assertEqual(self.issues(DesignerBinding("", expr="a.b * 2")), [])

    def test_rules(self):
        rules = [{"if": "> 80", "prop": "title", "value": "HOT"},        # 0 fine
                 {"if": "hot", "prop": "title", "value": "X"},          # 1 bad condition
                 {"if": "> 1", "prop": "nope", "value": 1},             # 2 unknown prop
                 {"if": "> 1", "prop": "value", "value": 1},            # 3 bound prop
                 {"if": "> 1", "prop": "title", "value": [1]},          # 4 not scalar
                 {"if": "> 1", "prop": "title"}]                        # 5 missing value
        self.tile.bindings["value"] = DesignerBinding("a.b", rules=rules)
        got = self.issues(self.tile.bindings["value"])
        self.assertEqual(got, [
            "rule 1: condition 'hot' is not '<op> <number>'",
            "rule 2: ShValueTile has no property 'nope'",
            "rule 3: property 'value' is bound",
            "rule 4: value must be a scalar",
            "rule 5: needs if, prop and value",
        ])

    def test_project_level(self):
        project = DesignerProject.from_dict({"version": 1, "pages": [{"id": "main", "widgets": [
            {"type": "ShGauge", "id": "g", "geometry": {"x": 0, "y": 0, "width": 100, "height": 100},
             "bindings": {"value": {"tag": "", "expr": "e.a + e.b"}}}]}]})
        self.assertEqual(project.required_tags(), ["e.a", "e.b"])
        self.assertEqual([i.message for i in project.validate(self.registry)], [])
        saved = project.to_dict()["pages"][0]["widgets"][0]["bindings"]["value"]
        self.assertEqual(saved["expr"], "e.a + e.b")


class Extras(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.x = BindingExtras()
        self.addCleanup(self.x.deleteLater)
        self.definition = default_registry().get("ShValueTile")
        self.decimals = self.x.findChild(QSpinBox, "extraDecimals")
        self.expr = self.x.findChild(QLineEdit, "extraExpr")
        self.state = self.x.findChild(QLabel, "extraExprState")
        self.rules = self.x.findChild(QTableWidget, "extraRules")
        self.add = self.x.findChild(QPushButton, "extraAddRule")
        self.remove = self.x.findChild(QPushButton, "extraRemoveRule")

    def test_fields(self):
        for field in (self.decimals, self.expr, self.state, self.rules, self.add, self.remove):
            self.assertIsNotNone(field)
        self.assertEqual((self.decimals.minimum(), self.decimals.maximum()), (-1, 6))
        self.assertEqual(self.decimals.specialValueText(), "auto")
        self.assertEqual(self.rules.columnCount(), 3)

    def test_load_apply_roundtrip(self):
        b = DesignerBinding("a.b", decimals=2, expr="a.b * 2",
                            rules=[{"if": "> 80", "prop": "title", "value": "HOT"},
                                   {"if": "<= 0", "prop": "state", "value": 0.5}])
        self.x.load(b, self.definition)
        self.assertEqual(self.decimals.value(), 2)
        self.assertEqual(self.expr.text(), "a.b * 2")
        self.assertEqual(self.rules.rowCount(), 2)
        self.assertEqual(self.rules.item(0, 2).text(), '"HOT"')
        out = self.x.apply_to(DesignerBinding("a.b"))
        self.assertEqual((out.decimals, out.expr), (2, "a.b * 2"))
        self.assertEqual(out.rules, b.rules)

    def test_expression_state_updates_as_you_type(self):
        self.x.load(DesignerBinding("a.b"), self.definition)
        self.expr.setText("1 +")
        self.assertTrue(self.state.text())
        self.expr.setText("a.b + 1")
        self.assertEqual(self.state.text(), "")

    def test_add_and_remove_rule(self):
        self.x.load(DesignerBinding("a.b"), self.definition)
        self.add.click()
        self.assertEqual(self.rules.rowCount(), 1)
        out = self.x.apply_to(DesignerBinding("a.b"))
        self.assertEqual(out.rules[0]["if"], "> 0")
        self.assertIn(out.rules[0]["prop"], self.definition.properties)
        self.rules.selectRow(0)
        self.remove.click()
        self.assertEqual(self.rules.rowCount(), 0)

    def test_value_cell_json_or_text(self):
        self.x.load(DesignerBinding("a.b"), self.definition)
        self.add.click()
        self.rules.item(0, 2).setText("12.5")
        self.assertEqual(self.x.apply_to(DesignerBinding("a.b")).rules[0]["value"], 12.5)
        self.rules.item(0, 2).setText("plain words")
        self.assertEqual(self.x.apply_to(DesignerBinding("a.b")).rules[0]["value"], "plain words")

    def test_load_none_clears(self):
        self.x.load(DesignerBinding("a.b", decimals=3, expr="1"), self.definition)
        self.x.load(None, self.definition)
        self.assertEqual((self.decimals.value(), self.expr.text(), self.rules.rowCount()), (-1, "", 0))


if __name__ == "__main__":
    unittest.main()
