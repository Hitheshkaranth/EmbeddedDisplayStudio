"""tests/test_designer_studio2.py -- the Studio 2 Design mode.

The Designer's layer names, its Compact/Normal/Large size wish on a compiled
page, and the composer that applies the text vocabulary here and hands
anything else to the AI.
"""
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ui import DesignerWorkspace  # noqa: E402
from tests.test_layout_compiler import PLAN, _reply  # noqa: E402


def _compiled_project():
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator().generate(_reply(PLAN), 1024, 768)


class DesignModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.load_project(_compiled_project())

    def _rows(self):
        out, stack = [], [self.ws.tree.topLevelItem(0)]
        while stack:
            item = stack.pop()
            out.append((item.text(0), item.text(1), item.data(0, 256)))
            stack.extend(item.child(i) for i in range(item.childCount()))
        return out

    def test_layers_use_names_and_tags_not_chrome(self):
        rows = self._rows()
        names = [name for name, _tag, _id in rows]
        self.assertIn("Pressures", names)            # a card, by its heading
        self.assertIn(("Suction", ""), [(n, t) for n, t, _i in rows if n == "Suction"])
        flow = next(row for row in rows if row[2] == "flowRate")
        self.assertEqual(flow[1], "ai.flow_main")
        # Card headings and lamp words belong to their card or lamp.
        self.assertFalse([i for _n, _t, i in rows if i and i.endswith("Heading")])

    def select(self, widget_id):
        self.ws.scene.clearSelection()
        self.ws.scene.item_for_id(widget_id).setSelected(True)

    def test_size_wish_recompiles_and_undoes(self):
        self.select("suction")
        model = lambda: next(w for w in self.ws.current_page.walk() if w.id == "suction")
        before = dict(model().geometry)
        self.ws.set_size_wish("large")
        self.assertEqual(model().properties.get("_size"), "large")
        self.assertNotEqual(dict(model().geometry), before)
        self.ws.undo_stack.undo()
        self.assertIsNone(model().properties.get("_size"))
        self.assertEqual(dict(model().geometry), before)

    def test_selection_names_the_widget_and_scopes_the_composer(self):
        self.select("discharge")
        self.assertEqual(self.ws.selection_title.text(), "Discharge")
        self.assertEqual(self.ws.composer_scope.text(), "Discharge")
        self.assertTrue(self.ws.size_buttons["normal"].isChecked())

    def test_composer_applies_commands_and_sends_the_rest_to_the_ai(self):
        asked = []
        self.ws.aiRequested.connect(asked.append)
        self.ws.chat_input.setText("add Value Tile")
        self.ws._apply_chat()
        self.assertIn("Added Value Tile", self.ws.chat_reply.text())
        self.assertEqual(asked, [])
        self.ws.chat_input.setText("make the pressures card compact")
        self.ws._apply_chat()
        self.assertEqual(asked, ["make the pressures card compact"])
        context = self.ws.ai_context()
        self.assertIn("Pressures", context)
        self.assertIn("ai.flow_main", context)


class ClusterGaugePainterTests(unittest.TestCase):
    """The canvas painter shown until hmi-ui's render lands agrees with it:
    an empty readout shows the value, not the kit's sample."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_readout_is_a_value(self):
        from designer.canvas import automotive_previews
        drawn = []
        original = automotive_previews._text
        automotive_previews._text = lambda _p, _r, text, **_k: drawn.append(text)
        try:
            from PySide6.QtCore import QRectF
            from PySide6.QtGui import QImage, QPainter
            image = QImage(200, 200, QImage.Format_ARGB32)
            painter = QPainter(image)
            automotive_previews.paint_cluster_gauge(
                painter, QRectF(0, 0, 200, 200),
                {"readout": "", "value": 4.2, "readoutUnit": "", "label": ""}, None)
            painter.end()
        finally:
            automotive_previews._text = original
        self.assertIn("4", drawn)
        self.assertNotIn("137", drawn)
        self.assertNotIn("km/h", drawn)


if __name__ == "__main__":
    unittest.main()
