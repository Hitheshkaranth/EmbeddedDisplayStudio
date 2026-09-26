"""Extra W4 tests: what the frozen gate does not pin down about the design
brief's layout and truncation, quick actions and the panel menu."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Appended, not inserted: tests/ui/ would otherwise shadow the repo's ui
# package and AgentPanel could not import ui.python.fx.
sys.path.append(str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.agent_backend import ScriptedBackend  # noqa: E402
from designer.ide.agent_context import RULES, QuickAction, design_brief, quick_actions  # noqa: E402
from designer.ide.agent_panel import AgentPanel  # noqa: E402
from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.model.project import DesignerBinding, DesignerPage  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project, widget  # noqa: E402


def big_index(pages=0, tags=300):
    project = make_project()
    for i in range(tags):
        project.pages[0].widgets.append(widget("ShNumDisplay", f"n{i}",
                                               bindings={"value": DesignerBinding(f"ai.sensor{i:03d}")}))
    for p in range(pages):
        project.pages.append(DesignerPage(f"extra{p}", f"Extra page {p}",
                                          [widget("ShLabel", f"label{p}")]))
    return DesignIndex.build(project, default_registry())


class LayoutTests(unittest.TestCase):
    def test_one_blank_line_between_sections_none_inside(self):
        index = DesignIndex.build(make_project(), default_registry(), DECLARED_TAGS)
        text = design_brief(index, "pump")
        blocks = text.split("\n\n")
        self.assertEqual([b.splitlines()[0] for b in blocks],
                         ["## Design", "## Selected widget", "## Tags", "## Issues", "## Rules"])
        self.assertNotIn("\n\n\n", text)
        self.assertEqual(blocks[-1], "## Rules\n" + RULES)

    def test_no_tags_says_none(self):
        project = make_project()
        project.pages = [DesignerPage("p", "P", [widget("ShLabel", "l")])]
        body = design_brief(DesignIndex.build(project)).split("## Tags\n", 1)[1].split("\n\n")[0]
        self.assertEqual(body, "- none")

    def test_unnamed_project(self):
        project = make_project()
        project.name = ""
        self.assertIn('Project "(unnamed)", ', design_brief(DesignIndex.build(project)))


class TruncationTests(unittest.TestCase):
    def test_fits_and_counts_dropped_tags(self):
        index = big_index()
        text = design_brief(index, max_chars=4000)
        self.assertLessEqual(len(text), 4000)
        tags = text.split("## Tags\n", 1)[1].split("\n\n")[0].splitlines()
        kept, marker = tags[:-1], tags[-1]
        self.assertEqual(marker, f"- ... {len(index.tags()) - len(kept)} more tags")

    def test_pages_go_after_tags(self):
        index = big_index(pages=200)
        full = design_brief(index, max_chars=10 ** 6)
        # Small enough that every tag line and some page lines must go.
        budget = len(full.split("## Tags")[0]) // 2 + len(RULES) + 400
        text = design_brief(index, max_chars=budget)
        self.assertLessEqual(len(text), budget)
        self.assertRegex(text, r"- \.\.\. \d+ more pages")
        self.assertIn(f"- ... {len(index.tags())} more tags", text)
        self.assertTrue(text.endswith(RULES))

    def test_unfittable_returns_quickly_with_rules_and_json(self):
        # The opencode draft looped forever here: its "... more tags" line
        # replaced itself and the brief never shrank.
        index = big_index(pages=20)
        start = time.monotonic()
        text = design_brief(index, "rpm", max_chars=10)
        self.assertLess(time.monotonic() - start, 5)
        self.assertGreater(len(text), 10)
        self.assertTrue(text.endswith(RULES))
        self.assertIn('"id": "rpm"', text)
        self.assertIn(f"- ... {len(index.tags())} more tags", text)
        self.assertRegex(text, r"- \.\.\. 22 more pages")


class QuickActionExtraTests(unittest.TestCase):
    def setUp(self):
        self.index = DesignIndex.build(make_project(), default_registry(), DECLARED_TAGS)

    def labels(self, sel):
        return [a.label for a in quick_actions(self.index, sel)]

    def test_no_alarm_for_empty_or_wildcard_binding(self):
        self.assertNotIn("Add alarm to broken", self.labels("broken"))
        self.assertNotIn("Add alarm to table", self.labels("table"))
        self.assertIn("Add alarm to pump", self.labels("pump"))

    def test_unknown_selection_is_ignored(self):
        self.assertEqual(self.labels("ghost"), ["Fix binding issues", "Write backend for tags", "Summarise design"])


class PanelMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.backend = ScriptedBackend(interval_ms=50)
        self.panel = AgentPanel(self.backend)
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_directory("/proj")

    def test_menu_item_sends_its_prompt_with_design(self):
        self.panel.set_design_provider(lambda: "BRIEF")
        self.panel.context_check.setChecked(False)
        self.panel.set_quick_actions([QuickAction("Summarise design", "Summarise")])
        self.panel.quick_button.menu().actions()[0].trigger()
        sends = [c for c in self.backend.calls if c[0] == "send"]
        self.assertEqual(sends[-1][1][0], "Summarise")
        self.assertEqual(sends[-1][1][2], {"design": "BRIEF"})

    def test_menu_is_replaced_not_appended(self):
        self.panel.set_quick_actions([QuickAction("a", "A"), QuickAction("b", "B")])
        self.panel.set_quick_actions([QuickAction("c", "C")])
        self.assertEqual([a.text() for a in self.panel.quick_button.menu().actions()], ["c"])
        self.assertFalse(self.panel.trigger_quick_action("a"))


if __name__ == "__main__":
    unittest.main()
