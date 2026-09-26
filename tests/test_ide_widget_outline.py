"""designer/ide/widget_outline.py (FROZEN gate for W1)."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))  # after the repo: tests/ui must not shadow ui
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.widget_outline import (  # noqa: E402
    COLUMNS, PAGE_ROLE, WidgetOutline, summary_text, widget_tags_text, widget_tooltip,
)
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, edsui_text, make_project  # noqa: E402


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.index = DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS,
                                       edsui_text=edsui_text())

    def test_summary_text(self):
        self.assertEqual(summary_text(self.index.summary()), "2 pages, 10 widgets, 6 types, 6 tags, 2 issues")
        self.assertEqual(summary_text({"pages": 1, "widgets": 1, "types": 1, "tags": 0, "bound": 0, "issues": 1}),
                         "1 page, 1 widget, 1 type, 0 tags, 1 issue")

    def test_tags_text(self):
        w = self.index.widget
        self.assertEqual(widget_tags_text(w("rpm"), self.index), "ai.rpm")
        self.assertEqual(widget_tags_text(w("pump"), self.index), "do.pump (rw)")
        self.assertEqual(widget_tags_text(w("horn"), self.index), "do.horn (w)")
        self.assertEqual(widget_tags_text(w("next"), self.index), "-> Alarms")
        self.assertEqual(widget_tags_text(w("panel"), self.index), "")
        self.assertEqual(widget_tags_text(w("table"), self.index), "")

    def test_tooltip(self):
        tip = widget_tooltip(self.index.widget("rpm"), self.index).splitlines()
        self.assertEqual(tip[:3], ["rpm (ShGauge)", "Page: Main", "Geometry: 10, 10, 200 x 200"])
        self.assertIn("Binds value <- ai.rpm", tip)
        tip = widget_tooltip(self.index.widget("horn"), self.index).splitlines()
        self.assertIn("On clicked: pulse do.horn", tip)


class OutlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="outline-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        path = os.path.join(self.dir, "project.edsui")
        self.text = edsui_text()
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.text)
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.load_file(path)
        self.index = DesignIndex.build(self.ws.project, declared_tags=DECLARED_TAGS, edsui_text=self.text)
        self.outline = WidgetOutline(self.ws)
        self.addCleanup(self.outline.deleteLater)
        self.outline.set_index(self.index)

    def test_tree_shape(self):
        tree = self.outline.tree
        self.assertEqual(tree.columnCount(), len(COLUMNS))
        self.assertEqual(tree.topLevelItemCount(), 2)
        main = tree.topLevelItem(0)
        self.assertEqual(main.text(0), "Main (5)")
        self.assertEqual(main.data(0, PAGE_ROLE), 0)
        self.assertEqual(main.data(0, Qt.UserRole), "")
        self.assertEqual(tree.topLevelItem(1).text(0), "Alarms (5)")
        panel = self.outline.item_for("panel")
        self.assertEqual(panel.childCount(), 2)
        self.assertEqual(panel.child(0).text(0), "pump  ShToggle")
        self.assertEqual(panel.child(0).text(1), "do.pump (rw)")
        self.assertTrue(panel.isExpanded())
        self.assertEqual(self.outline.item_for("oil").text(2), "1")
        self.assertEqual(self.outline.item_for("rpm").text(2), "")
        self.assertIsNone(self.outline.item_for("ghost"))
        self.assertEqual(self.outline.widget_ids(),
                         ["rpm", "panel", "pump", "horn", "next", "table", "oil", "rpm2", "broken", "estop"])
        self.assertEqual(self.outline.summary_label.text(), "2 pages, 10 widgets, 6 types, 6 tags, 2 issues")
        self.assertIn("ShNumDisplay: 3", self.outline.summary_label.toolTip())

    def test_filter_and_modes(self):
        self.outline.set_filter("toggle")
        self.assertEqual(self.outline.widget_ids(), ["panel", "pump", "estop"])
        self.outline.set_filter("")
        self.outline.set_mode("issues")
        self.assertEqual(self.outline.widget_ids(), ["oil", "broken"])
        self.assertTrue(self.outline.tree.topLevelItem(0).isHidden())
        self.outline.set_mode("bound")
        self.assertEqual(self.outline.widget_ids(), ["rpm", "panel", "pump", "horn", "oil", "rpm2", "estop"])
        self.assertTrue(self.outline.mode_buttons["bound"].isChecked())
        self.outline.mode_buttons["all"].click()
        self.assertEqual(self.outline.mode(), "all")
        with self.assertRaises(ValueError):
            self.outline.set_mode("everything")

    def test_show_tag(self):
        self.outline.show_tag("ai.rpm")
        self.assertEqual(self.outline.shown_tag(), "ai.rpm")
        self.assertEqual(self.outline.widget_ids(), ["rpm", "rpm2"])
        self.assertFalse(self.outline.tag_chip.isHidden())
        self.assertIn("ai.rpm", self.outline.tag_chip.text())
        self.outline.tag_chip.click()
        self.assertEqual(self.outline.shown_tag(), "")
        self.assertTrue(self.outline.tag_chip.isHidden())
        self.assertEqual(len(self.outline.widget_ids()), 10)

    def test_pick_switches_page(self):
        seen = []
        self.outline.widgetPicked.connect(seen.append)
        self.outline.pick("oil")
        self.assertEqual(self.ws.current_page_index, 1)
        self.assertEqual(self.ws.selected_widget().id, "oil")
        self.assertEqual(seen, ["oil"])
        self.assertEqual(self.outline.highlighted_id(), "oil")
        self.outline.pick("pump")
        self.assertEqual(self.ws.current_page_index, 0)
        self.assertEqual(self.ws.selected_widget().id, "pump")

    def test_click_and_double_click(self):
        seen, sources = [], []
        self.outline.widgetPicked.connect(seen.append)
        self.outline.sourceRequested.connect(lambda i, n: sources.append((i, n)))
        item = self.outline.item_for("rpm")
        self.outline.tree.itemClicked.emit(item, 0)
        self.assertEqual(seen, ["rpm"])
        self.outline.tree.itemDoubleClicked.emit(item, 0)
        line = self.index.widget("rpm").line
        self.assertGreater(line, 0)
        self.assertIn(("rpm", line), sources)
        self.outline.tree.itemClicked.emit(self.outline.tree.topLevelItem(0), 0)
        self.assertEqual(seen, ["rpm"], "page rows do not pick")

    def test_follows_designer_selection(self):
        seen = []
        self.outline.widgetPicked.connect(seen.append)
        self.ws.select_widget("next")
        self.assertEqual(self.outline.highlighted_id(), "next")
        self.assertEqual(seen, [])

    def test_rebuild_keeps_state_and_empty(self):
        self.outline.set_filter("rpm")
        self.outline.set_index(self.index)
        self.assertEqual(self.outline.widget_ids(), ["rpm", "rpm2"])
        self.outline.set_index(None)
        self.assertEqual(self.outline.widget_ids(), [])
        self.assertIsNone(self.outline.index())
        self.outline.apply_theme("light")
        self.outline.apply_theme("dark")


if __name__ == "__main__":
    unittest.main()
