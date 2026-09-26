"""TagPanel defects found in review that the frozen gate did not cover."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))  # after the repo: tests/ui must not shadow ui
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.tag_panel import STATUS_COL, TagPanel  # noqa: E402
from designer.ide.tag_source import TagSource  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project  # noqa: E402


class Source(TagSource):
    def __init__(self, values):
        super().__init__()
        self.values = values
        self.writes = []

    def name(self):
        return "S"

    def is_online(self):
        return True

    def value(self, tag):
        return self.values.get(tag)

    def can_write(self):
        return True

    def write(self, tag, value):
        self.writes.append((tag, value))
        return True


class TagPanelQcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.panel = TagPanel()
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_index(DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS))

    def test_context_menu_opens_and_targets_clicked_row(self):
        src = Source({})
        self.panel.set_source(src)
        self.panel.resize(600, 400)
        self.panel.show()
        row = self.panel.tags().index("do.pump")
        self.panel.table.setCurrentCell(0, 0)  # a different row is current
        rect = self.panel.table.visualItemRect(self.panel.table.item(row, 0))
        # Close the menu as soon as it is up; the call must not raise.
        QTimer.singleShot(50, lambda: QApplication.activePopupWidget() and QApplication.activePopupWidget().close())
        self.panel.table.customContextMenuRequested.emit(QPoint(rect.center()))
        self.assertTrue(self.panel._write_action.isEnabled())
        self.panel._copy_tag()
        self.assertEqual(QApplication.clipboard().text(), "do.pump")
        self.assertIsInstance(self.panel._menu, QMenu)

    def test_hidden_rows_stay_fresh(self):
        src = Source({"ai.rpm": 1.0})
        self.panel.set_source(src)
        self.panel.set_filter("pump")
        src.values["ai.rpm"] = 2.0
        self.panel.refresh_values()
        self.panel.set_filter("")
        self.assertEqual(self.panel.value_text("ai.rpm"), "2")

    def test_bool_words_only_for_digital_tags(self):
        src = Source({})
        self.panel.set_source(src)
        self.assertFalse(self.panel.write_value("ai.rpm", "on"))
        self.assertTrue(self.panel.write_value("do.pump", "on"))
        self.assertEqual(src.writes, [("do.pump", True)])

    def test_status_rows_tinted(self):
        row = self.panel.tags().index("ai.oiltemp")
        tint = self.panel.table.item(row, STATUS_COL).foreground().color()
        ok_row = self.panel.tags().index("ai.rpm")
        self.assertNotEqual(tint, self.panel.table.item(ok_row, STATUS_COL).foreground().color())
        self.assertNotEqual(tint, QColor())


if __name__ == "__main__":
    unittest.main()
