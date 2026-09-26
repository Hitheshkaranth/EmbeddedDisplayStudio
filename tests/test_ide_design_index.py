"""designer/ide/design_index.py (FROZEN gate, skeleton)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from designer.ide.design_index import DesignIndex, edsui_lines, is_writable_tag  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, edsui_text, make_project  # noqa: E402


class DesignIndexTests(unittest.TestCase):
    def setUp(self):
        self.project = make_project()
        self.text = edsui_text(self.project)
        self.index = DesignIndex.build(self.project, default_registry(), DECLARED_TAGS, self.text)

    def test_widgets_all_pages_depth_first(self):
        self.assertEqual([w.id for w in self.index.widgets()],
                         ["rpm", "panel", "pump", "horn", "next", "table", "oil", "rpm2", "broken", "estop"])
        pump = self.index.widget("pump")
        self.assertEqual((pump.page_index, pump.parent_id, pump.depth, pump.page_name), (0, "panel", 1, "Main"))
        self.assertEqual([w.id for w in self.index.widgets(1)][:2], ["table", "oil"])

    def test_bindings_and_actions(self):
        pump = self.index.widget("pump")
        self.assertEqual(pump.tags_read(), ("do.pump",))
        self.assertEqual(pump.tags_written(), ("do.pump",))
        self.assertEqual(self.index.widget("next").actions, (("clicked", "navigate", "alarms"),))
        self.assertEqual(self.index.widget("table").tags_read(), ())

    def test_tags(self):
        names = [t.tag for t in self.index.tags()]
        self.assertEqual(names, ["ai.fuel", "ai.oiltemp", "ai.rpm", "di.estop", "do.horn", "do.pump"])
        rpm = self.index.tag("ai.rpm")
        self.assertEqual(rpm.readers, (("rpm", "value"), ("rpm2", "value")))
        self.assertEqual((rpm.access, rpm.declared, rpm.writable), ("R", True, False))
        self.assertEqual(self.index.tag("do.pump").access, "RW")
        self.assertEqual(self.index.tag("do.horn").access, "W")
        self.assertEqual(self.index.tag("ai.fuel").access, "")
        self.assertFalse(self.index.tag("ai.oiltemp").declared)
        self.assertEqual(self.index.widgets_using("do.pump"), ["pump"])
        self.assertEqual(self.index.widgets_using("nope"), [])

    def test_lines_point_at_the_widget(self):
        lines = self.text.splitlines()
        for entry in self.index.widgets():
            self.assertGreater(entry.line, 0, entry.id)
            self.assertIn(f'"id": "{entry.id}"', lines[entry.line - 1])
        self.assertEqual(DesignIndex.build(self.project).widget("rpm").line, 0)
        self.assertEqual(edsui_lines('{"id": "a\\"b"}'), {'a"b': 1})

    def test_issues(self):
        issues = {(r.widget_id, r.status) for r in self.index.issues()}
        self.assertIn(("broken", "error"), issues)
        self.assertIn(("oil", "warning"), issues)
        self.assertNotIn("table", {r.widget_id for r in self.index.issues()})
        self.assertEqual(self.index.issues_for("rpm"), [])

    def test_summary_and_counts(self):
        s = self.index.summary()
        self.assertEqual(s, {"pages": 2, "widgets": 10, "types": 6, "tags": 6, "bound": 6, "issues": 2})
        self.assertEqual(list(self.index.type_counts())[:2], ["ShNumDisplay", "ShButton"])
        self.assertEqual(self.index.definition("ShGauge").bindable_properties, ("value",))
        self.assertIsNone(DesignIndex.build(None).widget("x"))
        self.assertTrue(is_writable_tag("do.x") and not is_writable_tag("ai.x"))


if __name__ == "__main__":
    unittest.main()
