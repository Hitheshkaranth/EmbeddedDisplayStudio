"""designer/ide/agent_context.py + the W4 hooks in agent_backend/agent_panel (FROZEN gate for W4)."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))  # after the repo: tests/ui must not shadow ui
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.agent_backend import ScriptedBackend, build_prompt  # noqa: E402
from designer.ide.agent_context import RULES, QuickAction, design_brief, find_widget, quick_actions  # noqa: E402
from designer.ide.agent_panel import AgentPanel  # noqa: E402
from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.model.project import DesignerBinding  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project, widget  # noqa: E402


def sections(text):
    out, name = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:]
            out[name] = []
        elif name:
            out[name].append(line)
    return out


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.project = make_project()
        self.index = DesignIndex.build(self.project, default_registry(), DECLARED_TAGS)

    def test_sections_and_order(self):
        text = design_brief(self.index)
        heads = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(heads, ["## Design", "## Tags", "## Issues", "## Rules"])
        self.assertTrue(text.rstrip().endswith(RULES.rstrip()))
        with_sel = design_brief(self.index, "pump")
        heads = [line for line in with_sel.splitlines() if line.startswith("## ")]
        self.assertEqual(heads, ["## Design", "## Selected widget", "## Tags", "## Issues", "## Rules"])
        self.assertEqual(design_brief(None), "")

    def test_design_section(self):
        body = sections(design_brief(self.index))["Design"]
        self.assertEqual(body[0], 'Project "Fixture", 2 pages, 10 widgets, 6 tags')
        self.assertIn('- main "Main": 5 widgets (ShGauge x1, ShCard x1, ShToggle x1, ShButton x2)', body)
        self.assertIn('- alarms "Alarms": 5 widgets (ShAlarmTable x1, ShNumDisplay x3, ShToggle x1)', body)

    def test_selected_section(self):
        body = sections(design_brief(self.index, "pump"))["Selected widget"]
        self.assertEqual(body[0], "pump (ShToggle) on page main, parent panel")
        self.assertIn("Bindable properties: checked", body)
        self.assertIn("Action signals: toggled", body)
        start = body.index("```json")
        end = body.index("```", start + 1)
        data = json.loads("\n".join(body[start + 1:end]))
        self.assertEqual(data["id"], "pump")
        self.assertEqual(data["bindings"]["checked"]["tag"], "do.pump")
        body = sections(design_brief(self.index, "rpm"))["Selected widget"]
        self.assertEqual(body[0], "rpm (ShGauge) on page main, parent none")
        self.assertIn("Action signals: none", body)
        self.assertNotIn("Selected widget", sections(design_brief(self.index, "ghost")))

    def test_tags_and_issues(self):
        s = sections(design_brief(self.index))
        self.assertIn("- ai.rpm [R] read by rpm, rpm2; written by nothing", s["Tags"])
        self.assertIn("- do.pump [RW] read by pump; written by pump (writable)", s["Tags"])
        self.assertIn("- ai.oiltemp [R] read by oil; written by nothing (not declared)", s["Tags"])
        self.assertIn("- ai.fuel [-] read by nothing; written by nothing", s["Tags"])
        self.assertIn("- broken.value: Empty binding", s["Issues"])
        self.assertIn("- oil.value: Tag not declared", s["Issues"])
        clean = make_project()
        clean.pages = clean.pages[:1]
        self.assertNotIn("Issues", sections(design_brief(DesignIndex.build(clean))))

    def test_max_chars(self):
        big = make_project()
        for i in range(300):
            big.pages[0].widgets.append(widget("ShNumDisplay", f"n{i}",
                                               bindings={"value": DesignerBinding(f"ai.sensor{i:03d}")}))
        index = DesignIndex.build(big, default_registry())
        text = design_brief(index, "rpm", max_chars=4000)
        self.assertLessEqual(len(text), 4000)
        self.assertIn(RULES, text)
        self.assertRegex(text, r"- \.\.\. \d+ more tags")
        self.assertIn("## Selected widget", text)
        full = design_brief(index, "rpm", max_chars=10 ** 6)
        self.assertNotIn("more tags", full)


class QuickActionTests(unittest.TestCase):
    def setUp(self):
        self.index = DesignIndex.build(make_project(), default_registry(), DECLARED_TAGS)

    def labels(self, sel=""):
        return [a.label for a in quick_actions(self.index, sel)]

    def test_lists(self):
        self.assertEqual(self.labels("rpm"), ["Explain rpm", "Bind rpm...", "Add alarm to rpm", "Fix binding issues",
                                              "Write backend for tags", "Summarise design"])
        self.assertEqual(self.labels("horn"), ["Explain horn", "Fix binding issues", "Write backend for tags",
                                               "Summarise design"])
        self.assertEqual(self.labels(""), ["Fix binding issues", "Write backend for tags", "Summarise design"])
        self.assertEqual(quick_actions(None), [])
        acts = {a.label: a.prompt for a in quick_actions(self.index, "rpm")}
        self.assertEqual(acts["Explain rpm"],
                         "Explain what widget rpm (ShGauge) shows and how it is wired: its bindings, actions "
                         "and the tags involved.")
        self.assertIn("Bind widget rpm's value to a suitable tag", acts["Bind rpm..."])
        self.assertIn("widget rpm's value binding", acts["Add alarm to rpm"])
        self.assertIsInstance(quick_actions(self.index)[0], QuickAction)

    def test_find_widget(self):
        project = make_project()
        self.assertEqual(find_widget(project, "horn").type, "ShButton")
        self.assertIsNone(find_widget(project, "ghost"))


class BuildPromptTests(unittest.TestCase):
    def test_design_block(self):
        header = "Design context (from the Studio, current as of this message):"
        self.assertEqual(build_prompt("hi", {"design": "BRIEF"}), f"hi\n\n{header}\nBRIEF")
        out = build_prompt("hi", {"path": "/p/a.c", "relative": "a.c", "cursor_line": 3, "design": "BRIEF"})
        self.assertTrue(out.startswith("hi\n\n(Open in the editor: a.c, cursor on line 3.)"))
        self.assertTrue(out.endswith(f"\n\n{header}\nBRIEF"))
        self.assertEqual(build_prompt("hi", {"design": ""}), "hi")
        self.assertEqual(build_prompt("hi", None), "hi")


class PanelHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.backend = ScriptedBackend(interval_ms=50)
        self.panel = AgentPanel(self.backend)
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_directory("/proj")

    def sent_context(self):
        return [c for c in self.backend.calls if c[0] == "send"][-1][1][2]

    def test_design_context(self):
        self.assertTrue(self.panel.design_check.isChecked())
        self.panel.set_context_provider(lambda: {"path": "/proj/a.c", "cursor_line": 1})
        self.panel.set_design_provider(lambda: "BRIEF")
        self.assertTrue(self.panel.send("one"))
        self.assertEqual(self.sent_context(), {"path": "/proj/a.c", "cursor_line": 1, "design": "BRIEF"})

    def test_design_only_and_off(self):
        self.panel.set_design_provider(lambda: "BRIEF")
        self.panel.context_check.setChecked(False)
        self.assertTrue(self.panel.send("one"))
        self.assertEqual(self.sent_context(), {"design": "BRIEF"})

    def test_design_unticked(self):
        self.panel.set_design_provider(lambda: "BRIEF")
        self.panel.design_check.setChecked(False)
        self.panel.context_check.setChecked(False)
        self.assertTrue(self.panel.send("one"))
        self.assertIsNone(self.sent_context())

    def test_empty_brief(self):
        self.panel.set_design_provider(lambda: "")
        self.panel.context_check.setChecked(False)
        self.assertTrue(self.panel.send("one"))
        self.assertIsNone(self.sent_context())

    def test_quick_actions(self):
        self.assertEqual(self.panel.quick_actions(), [])
        self.assertTrue(self.panel.quick_button.isHidden())
        acts = [QuickAction("Explain rpm", "Explain it"), QuickAction("Summarise design", "Summarise")]
        self.panel.set_quick_actions(acts)
        self.assertFalse(self.panel.quick_button.isHidden())
        self.assertEqual([a.text() for a in self.panel.quick_button.menu().actions()],
                         ["Explain rpm", "Summarise design"])
        self.assertEqual(self.panel.quick_actions(), acts)
        self.assertTrue(self.panel.trigger_quick_action("Explain rpm"))
        self.assertEqual([c[1][0] for c in self.backend.calls if c[0] == "send"], ["Explain it"])
        # Busy now: the second prompt must land in the input, not vanish.
        self.assertTrue(self.panel.trigger_quick_action("Summarise design"))
        self.assertEqual(self.panel.input.toPlainText(), "Summarise")
        self.assertFalse(self.panel.trigger_quick_action("nope"))
        self.panel.set_quick_actions([])
        self.assertTrue(self.panel.quick_button.isHidden())


if __name__ == "__main__":
    unittest.main()
