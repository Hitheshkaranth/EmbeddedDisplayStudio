"""designer/ide/tag_panel.py (FROZEN gate for W2)."""
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.append(str(Path(__file__).resolve().parent))  # after the repo: tests/ui must not shadow ui
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.tag_panel import COLUMNS, REFRESH_MS, TagPanel, format_value, status_for  # noqa: E402
from designer.ide.tag_source import TagSource  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project  # noqa: E402


def spin(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


class FakeSource(TagSource):
    def __init__(self, values=None, writable=True):
        super().__init__()
        self.values = dict(values or {})
        self.online = True
        self.writable = writable
        self.writes = []
        self.snapshots = 0

    def name(self):
        return "Fake"

    def is_online(self):
        return self.online

    def value(self, tag):
        return self.values.get(tag)

    def snapshot(self, tags):
        self.snapshots += 1
        return super().snapshot(tags)

    def can_write(self):
        return self.writable

    def write(self, tag, value):
        self.writes.append((tag, value))
        return True


class HelperTests(unittest.TestCase):
    def test_format_value(self):
        self.assertEqual(format_value(None), "--")
        self.assertEqual(format_value(True), "true")
        self.assertEqual(format_value(False), "false")
        self.assertEqual(format_value(7), "7")
        self.assertEqual(format_value(3120.5), "3120.5")
        self.assertEqual(format_value(52.11349), "52.113")
        self.assertEqual(format_value(0.0), "0")
        self.assertEqual(format_value(-1.25), "-1.25")
        self.assertEqual(format_value("OK"), "OK")

    def test_status_for(self):
        index = DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS)
        self.assertEqual(status_for(index.tag("ai.fuel")), "unused")
        self.assertEqual(status_for(index.tag("ai.oiltemp")), "not declared")
        self.assertEqual(status_for(index.tag("ai.rpm")), "ok")


class TagPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.index = DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS)
        self.panel = TagPanel()
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_index(self.index)
        self.messages = []
        self.panel.message.connect(self.messages.append)

    def test_rows_and_columns(self):
        self.assertEqual(self.panel.table.columnCount(), len(COLUMNS))
        self.assertEqual([self.panel.table.horizontalHeaderItem(i).text() for i in range(5)], list(COLUMNS))
        self.assertEqual(self.panel.tags(), ["ai.fuel", "ai.oiltemp", "ai.rpm", "di.estop", "do.horn", "do.pump"])
        row = self.panel.tags().index("ai.rpm")
        self.assertEqual(self.panel.table.item(row, 0).text(), "ai.rpm")
        self.assertEqual(self.panel.table.item(row, 1).text(), "R")
        self.assertEqual(self.panel.table.item(row, 2).text(), "rpm, rpm2")
        self.assertEqual(self.panel.table.item(0, 2).text(), "-")
        self.assertEqual(self.panel.status_text("ai.oiltemp"), "not declared")
        self.assertEqual(self.panel.value_text("ai.rpm"), "--")
        self.assertEqual(self.panel.value_text("nope"), "")
        self.assertEqual(self.panel.source_label.text(), "Source: none")

    def test_source_values(self):
        src = FakeSource({"ai.rpm": 3120.5, "do.pump": True})
        self.panel.set_source(src)
        self.assertIs(self.panel.source(), src)
        self.assertEqual(self.panel.value_text("ai.rpm"), "3120.5")
        self.assertEqual(self.panel.value_text("do.pump"), "true")
        self.assertEqual(self.panel.value_text("ai.fuel"), "--")
        self.assertEqual(self.panel.source_label.text(), "Source: Fake (online)")
        src.values["ai.rpm"] = 10
        self.panel.refresh_values()
        self.assertEqual(self.panel.value_text("ai.rpm"), "10")
        src.online = False
        src.onlineChanged.emit(False)
        self.assertEqual(self.panel.source_label.text(), "Source: Fake (offline)")
        self.panel.set_source(None)
        self.assertEqual(self.panel.source_label.text(), "Source: none")
        self.assertEqual(self.panel.value_text("ai.rpm"), "--")

    def test_timer_only_while_visible(self):
        src = FakeSource({"ai.rpm": 1.0})
        self.panel.set_source(src)
        base = src.snapshots
        spin(REFRESH_MS * 3)
        self.assertEqual(src.snapshots, base, "hidden pane must not poll")
        self.panel.show()
        spin(REFRESH_MS * 4)
        self.assertGreater(src.snapshots, base)
        self.panel.hide()
        n = src.snapshots
        spin(REFRESH_MS * 3)
        self.assertLessEqual(src.snapshots, n + 1)

    def test_values_changed_throttled(self):
        src = FakeSource({"ai.rpm": 1.0})
        self.panel.set_source(src)
        base = src.snapshots
        for _ in range(50):
            src.valuesChanged.emit()
        spin(REFRESH_MS + 100)
        self.assertLessEqual(src.snapshots - base, 3)
        self.assertGreaterEqual(src.snapshots - base, 1)

    def test_filter_and_select(self):
        self.panel.set_filter("PUMP")
        self.assertEqual(self.panel.tags(), ["do.pump"])
        self.panel.set_filter("rpm2")
        self.assertEqual(self.panel.tags(), ["ai.rpm"])
        self.panel.set_filter("")
        seen = []
        self.panel.tagActivated.connect(seen.append)
        self.panel.select_tag("di.estop")
        self.assertEqual(seen, [])
        self.assertEqual(self.panel.table.currentRow(), self.panel.tags().index("di.estop"))
        self.panel.set_index(self.index)
        self.assertEqual(len(self.panel.tags()), 6)

    def test_click_emits(self):
        seen = []
        self.panel.tagActivated.connect(seen.append)
        row = self.panel.tags().index("ai.rpm")
        self.panel.table.cellClicked.emit(row, 0)
        self.assertEqual(seen, ["ai.rpm"])

    def test_copy_and_scaffold(self):
        self.panel.set_filter("pump")
        text = self.panel.copy_tags()
        self.assertEqual(text.splitlines(), ["ai.fuel", "ai.oiltemp", "ai.rpm", "di.estop", "do.horn", "do.pump"])
        self.assertEqual(QApplication.clipboard().text(), text)
        seen = []
        self.panel.scaffoldRequested.connect(lambda: seen.append(1))
        self.panel.scaffold_button.click()
        self.assertEqual(seen, [1])

    def test_write_value(self):
        src = FakeSource()
        self.panel.set_source(src)
        self.assertTrue(self.panel.write_value("do.pump", "on"))
        self.assertTrue(self.panel.write_value("do.pump", "0"))
        self.assertTrue(self.panel.write_value("ai.rpm", "12"))
        self.assertTrue(self.panel.write_value("ai.rpm", "12.5"))
        self.assertFalse(self.panel.write_value("ai.rpm", "abc"))
        self.assertEqual(src.writes, [("do.pump", True), ("do.pump", False), ("ai.rpm", 12), ("ai.rpm", 12.5)])
        self.assertIs(type(src.writes[2][1]), int)
        self.assertIn("Wrote do.pump = True", self.messages)
        self.assertIn("Not a value: abc", self.messages)

    def test_empty_and_theme(self):
        self.panel.set_index(None)
        self.assertEqual(self.panel.tags(), [])
        self.panel.refresh_values()
        self.panel.apply_theme("light")
        self.panel.apply_theme("dark")


if __name__ == "__main__":
    unittest.main()
