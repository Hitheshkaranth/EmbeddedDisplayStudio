"""Extra tests for designer/ide/tag_panel.py (W2). Not part of the frozen gate."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.design_index import DesignIndex  # noqa: E402
from designer.ide.tag_panel import TagPanel, format_value, status_for  # noqa: E402
from designer.ide.tag_source import TagSource  # noqa: E402
from ide_v2_fixture import DECLARED_TAGS, make_project  # noqa: E402


class FakeSource(TagSource):
    def __init__(self, values=None):
        super().__init__()
        self.values = dict(values or {})
        self._online = True

    def name(self):
        return "Fake"

    def is_online(self):
        return self._online

    def value(self, tag):
        return self.values.get(tag)


class ExtraHelperTests(unittest.TestCase):
    def test_format_value_edge_cases(self):
        self.assertEqual(format_value(-0.0), "0")
        self.assertEqual(format_value(1.0), "1")
        self.assertEqual(format_value("hello world"), "hello world")

    def test_status_for_all(self):
        index = DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS)
        self.assertEqual(status_for(index.tag("do.pump")), "ok")
        self.assertEqual(status_for(index.tag("ai.fuel")), "unused")
        self.assertEqual(status_for(index.tag("ai.oiltemp")), "not declared")


class ExtraTagPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        self.index = DesignIndex.build(make_project(), declared_tags=DECLARED_TAGS)
        self.panel = TagPanel()
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_index(self.index)

    def test_write_refused_without_source(self):
        self.assertFalse(self.panel.write_value("do.pump", "1"))

    def test_write_refused_when_not_writable(self):
        src = FakeSource({"ai.rpm": 1.0})
        src.can_write = lambda: False
        self.panel.set_source(src)
        self.assertFalse(self.panel.write_value("ai.rpm", "5"))


if __name__ == "__main__":
    unittest.main()