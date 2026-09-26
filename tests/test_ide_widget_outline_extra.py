"""designer/ide/widget_outline.py -- behaviour the frozen gate does not cover."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Repo root only: tests/ on sys.path would shadow the top-level `ui` package
# with tests/ui.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide import widget_outline  # noqa: E402
from designer.ide.design_index import DesignIndex, WidgetEntry  # noqa: E402
from designer.ide.project_files import color  # noqa: E402
from designer.ide.widget_outline import WidgetOutline, summary_text, widget_tags_text  # noqa: E402
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402
from tests.ide_v2_fixture import DECLARED_TAGS, edsui_text  # noqa: E402


def _spin(ms=50):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


class HelperExtraTests(unittest.TestCase):
    def test_tags_grouped_read_rw_written_then_navigate(self):
        entry = WidgetEntry(id="w", type="T", page_index=0, page_id="p", page_name="P", parent_id="", depth=0,
                            bindings=(("a", "t.both"), ("b", "t.read")),
                            actions=(("s1", "write", "t.write"), ("s2", "navigate", "ghost"),
                                     ("s3", "pulse", "t.both")))
        index = DesignIndex.build(None)
        self.assertEqual(widget_tags_text(entry, index), "t.read, t.both (rw), t.write (w), -> ghost")

    def test_summary_singular_tag(self):
        self.assertEqual(summary_text({"pages": 2, "widgets": 0, "types": 0, "tags": 1, "issues": 0}),
                         "2 pages, 0 widgets, 0 types, 1 tag, 0 issues")


class OutlineExtraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="outline-extra-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        path = os.path.join(self.dir, "project.edsui")
        text = edsui_text()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.load_file(path)
        self.index = DesignIndex.build(self.ws.project, declared_tags=DECLARED_TAGS, edsui_text=text)
        self.outline = WidgetOutline(self.ws)
        self.addCleanup(self.outline.deleteLater)
        self.outline.set_index(self.index)

    def test_page_rows_hold_top_level_widgets(self):
        main = self.outline.tree.topLevelItem(0)
        self.assertIs(self.outline.item_for("rpm").parent(), main)
        self.assertIs(self.outline.item_for("pump").parent(), self.outline.item_for("panel"))

    def test_summary_tooltip_lists_type_counts(self):
        expected = "\n".join(f"{t}: {n}" for t, n in self.index.type_counts().items())
        self.assertEqual(self.outline.summary_label.toolTip(), expected)

    def test_issues_cell_tooltip_lists_details(self):
        rows = self.index.issues_for("oil")
        self.assertTrue(rows)
        self.assertEqual(self.outline.item_for("oil").toolTip(2), "\n".join(r.detail for r in rows))
        self.assertEqual(self.outline.item_for("rpm").toolTip(2), "")
        self.assertTrue(self.outline.item_for("rpm").toolTip(0).startswith("rpm (ShGauge)"))

    def test_issue_count_uses_destructive_colour(self):
        for theme in ("light", "dark"):
            self.outline.apply_theme(theme)
            try:
                expected = color("destructive", theme)
            except KeyError:
                expected = "#ef4444"
            got = self.outline.item_for("oil").foreground(2).color().name()
            self.assertEqual(got.lower(), expected.lower()[:7])

    def test_destructive_missing_falls_back(self):
        real = widget_outline.color

        def no_destructive(name, theme="dark"):
            if name == "destructive":
                raise KeyError(name)
            return real(name, theme)

        with mock.patch.object(widget_outline, "color", no_destructive):
            self.outline.apply_theme("light")
            self.outline.set_index(self.index)
        self.assertEqual(self.outline.item_for("oil").foreground(2).color().name(), "#ef4444")

    def test_filter_matches_type(self):
        self.outline.set_filter("shalarm")
        self.assertEqual(self.outline.widget_ids(), ["table"])
        self.assertTrue(self.outline.tree.topLevelItem(0).isHidden())

    def test_rebuild_keeps_mode_and_tag(self):
        self.outline.set_mode("bound")
        self.outline.show_tag("ai.rpm")
        self.outline.set_index(self.index)
        self.assertEqual(self.outline.mode(), "bound")
        self.assertEqual(self.outline.widget_ids(), ["rpm", "rpm2"])
        self.assertFalse(self.outline.tag_chip.isHidden())

    def test_rebuild_rehighlights_designer_selection(self):
        self.ws.select_widget("next")
        self.outline.set_index(self.index)
        self.assertEqual(self.outline.highlighted_id(), "next")

    def test_rebuild_keeps_scroll_position(self):
        self.outline.resize(300, 140)
        self.outline.show()
        self.addCleanup(self.outline.hide)
        _spin()
        bar = self.outline.tree.verticalScrollBar()
        self.assertGreater(bar.maximum(), 1, "tree must overflow for this test")
        bar.setValue(bar.maximum() - 1)
        before = bar.value()
        self.outline.set_index(self.index)
        self.assertEqual(bar.value(), before)
        _spin()
        self.assertEqual(bar.value(), before)


if __name__ == "__main__":
    unittest.main()
