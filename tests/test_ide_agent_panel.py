"""designer/ide/agent_panel.py -- W4's gate.

FROZEN: the tests below are the minimum W4 must pass; add more in a class
below them, never change these. The panel runs against ScriptedBackend
(designer/ide/agent_backend.py): no opencode, no network.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.agent_backend import ERROR, ScriptedBackend  # noqa: E402
from designer.ide.agent_panel import SETTINGS_MODEL_KEY, AgentPanel  # noqa: E402
from designer.ide.opencode_client import ModelRef  # noqa: E402

REPLY = [
    {"type": "reasoning", "id": "r1", "delta": "The user wants "},
    {"type": "reasoning", "id": "r1", "delta": "a sub function."},
    {"type": "tool", "id": "t1", "tool": "edit", "status": "running", "title": "math.c",
     "input": {"filePath": "/proj/math.c"}, "output": "", "error": ""},
    {"type": "file_edited", "path": "/proj/math.c"},
    {"type": "tool", "id": "t1", "tool": "edit", "status": "completed", "title": "math.c",
     "input": {"filePath": "/proj/math.c"}, "output": "Edit applied successfully.", "error": ""},
    {"type": "usage", "input": 100, "output": 20, "reasoning": 5},
    {"type": "text", "id": "x1", "delta": "Added `sub` "},
    {"type": "text", "id": "x1", "delta": "to **math.c**."},
    {"type": "usage", "input": 50, "output": 10, "reasoning": 0},
    {"type": "mystery", "foo": 1},
]


class AgentPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)
        QSettings("MIL-HMI", "Deployer").remove(SETTINGS_MODEL_KEY)

    def setUp(self):
        QSettings("MIL-HMI", "Deployer").remove(SETTINGS_MODEL_KEY)
        self.backend = ScriptedBackend({"add sub": REPLY, "perm": [
            {"type": "permission", "id": "per_1", "permission": "bash", "patterns": ["make"], "title": "bash: make"}],
            "boom": [{"type": "error", "message": "model not found"}]})
        self.panel = AgentPanel(self.backend)
        self.panel.resize(420, 700)
        self.panel.show()
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_directory("/proj")

    def _drain(self):
        waited = 0
        while (self.backend._pending or self.panel.is_busy()) and waited < 3000:
            QTest.qWait(20)
            waited += 20
        QTest.qWait(120)  # let throttled Markdown renders land

    def _kinds(self):
        return [k for k, _ in self.panel.blocks()]

    def test_starts_backend_and_lists_models(self):
        self.assertEqual(self.backend.calls[0], ("start", ("/proj",)))
        self.assertEqual(self.panel.directory(), "/proj")
        labels = [self.panel.model_combo.itemText(i) for i in range(self.panel.model_combo.count())]
        self.assertEqual(labels, ["fake/coder", "fake/big"])
        self.assertEqual(self.panel.selected_model(), ModelRef("fake", "coder"))

    def test_full_reply(self):
        edited = []
        self.panel.fileEdited.connect(edited.append)
        self.assertTrue(self.panel.send("add sub"))
        self.assertEqual(self.panel.input.toPlainText(), "")
        self._drain()
        self.assertEqual(self._kinds(), ["user", "reasoning", "tool", "assistant"])
        blocks = dict(self.panel.blocks())
        self.assertEqual(blocks["user"], "add sub")
        self.assertEqual(blocks["reasoning"], "The user wants a sub function.")
        self.assertEqual(blocks["tool"], "edit math.c completed")
        self.assertIn("Added sub to math.c.", blocks["assistant"].replace("`", "").replace("*", ""))
        self.assertEqual(edited, ["/proj/math.c"])
        # Usage is summed over the reply: in 100 + 50, out 20 + 10.
        self.assertIn("150", self.panel.state_label.text())
        self.assertIn("30", self.panel.state_label.text())
        self.assertFalse(self.panel.is_busy())

    def test_send_passes_model_and_context(self):
        self.panel.set_context_provider(lambda: {"path": "/proj/a.c"})
        self.panel.model_combo.setCurrentIndex(1)
        self.panel.send("hi")
        self.assertEqual(self.backend.calls[-1], ("send", ("hi", ModelRef("fake", "big"), {"path": "/proj/a.c"})))
        self._drain()
        self.panel.context_check.setChecked(False)
        self.panel.send("again")
        self.assertIsNone(self.backend.calls[-1][1][2])

    def test_model_choice_persists(self):
        self.panel.model_combo.setCurrentIndex(1)
        other = AgentPanel(ScriptedBackend())
        self.addCleanup(other.deleteLater)
        other.set_directory("/proj")
        self.assertEqual(other.selected_model(), ModelRef("fake", "big"))

    def test_enter_sends_shift_enter_newlines(self):
        self.panel.input.setFocus()
        QTest.keyClicks(self.panel.input, "line one")
        QTest.keyClick(self.panel.input, Qt.Key_Return, Qt.ShiftModifier)
        QTest.keyClicks(self.panel.input, "line two")
        self.assertEqual(self.panel.input.toPlainText(), "line one\nline two")
        QTest.keyClick(self.panel.input, Qt.Key_Return)
        self.assertEqual(self.backend.calls[-1][0], "send")
        self.assertEqual(self.backend.calls[-1][1][0], "line one\nline two")

    def test_busy_blocks_second_send_and_stop(self):
        self.backend.interval_ms = 200
        self.assertTrue(self.panel.send("add sub"))
        QTest.qWait(250)
        self.assertTrue(self.panel.is_busy())
        self.assertFalse(self.panel.send_button.isEnabled())
        self.assertTrue(self.panel.stop_button.isVisible())
        self.assertFalse(self.panel.send("second"))
        self.panel.stop()
        self._drain()
        self.assertIn(("abort", ()), self.backend.calls)
        self.assertFalse(self.panel.is_busy())
        self.assertIn(("notice", "Stopped"), self.panel.blocks())
        self.assertFalse(self.panel.stop_button.isVisible())

    def test_blank_or_not_ready_is_not_sent(self):
        self.assertFalse(self.panel.send("   "))
        self.backend._set_state(ERROR, "opencode is not installed")
        self.assertFalse(self.panel.send("hello"))
        self.assertIn("opencode is not installed", self.panel.state_label.text())
        self.assertFalse(self.panel.state_label.isHidden())

    def test_permission(self):
        self.panel.send("perm")
        self._drain()
        self.assertEqual(self._kinds(), ["user", "permission"])
        from PySide6.QtWidgets import QAbstractButton
        buttons = [b for b in self.panel.findChildren(QAbstractButton) if b.text() == "Always"]
        self.assertEqual(len(buttons), 1)
        buttons[0].click()
        self.assertEqual(self.backend.calls[-1], ("reply_permission", ("per_1", "always")))
        self.assertEqual(self.panel.blocks()[-1], ("permission", "bash: make -> always"))

    def test_error_block(self):
        self.panel.send("boom")
        self._drain()
        self.assertEqual(self.panel.blocks()[-1], ("error", "model not found"))

    def test_tool_link_opens_file(self):
        opened = []
        self.panel.openFileRequested.connect(lambda p, line: opened.append((p, line)))
        self.panel.send("add sub")
        self._drain()
        # The tool block offers the file; activating it asks for it.
        from PySide6.QtWidgets import QAbstractButton, QLabel
        links = [w for w in self.panel.findChildren(QLabel) if "/proj/math.c" in (w.text() or "")]
        links += [w for w in self.panel.findChildren(QAbstractButton) if "math.c" in (w.text() or "")]
        self.assertTrue(links, "the tool block shows a link to the edited file")
        link = links[0]
        if isinstance(link, QLabel):
            link.linkActivated.emit("/proj/math.c")
        else:
            link.click()
        self.assertEqual(opened, [("/proj/math.c", 0)])

    def test_new_chat_clears(self):
        self.panel.send("add sub")
        self._drain()
        self.panel.new_chat()
        self.assertEqual(self.panel.blocks(), [])
        self.assertEqual(self.backend.calls[-1], ("new_session", ()))

    def test_directory_change_restarts(self):
        self.panel.send("add sub")
        self._drain()
        self.panel.set_directory("/other")
        self.assertEqual(self.backend.calls[-1], ("start", ("/other",)))
        self.assertEqual(self.panel.blocks()[-1][0], "notice")
        self.assertIn("/other", self.panel.blocks()[-1][1])
        self.panel.set_directory("")
        self.assertEqual(self.backend.calls[-1], ("stop", ()))

    def test_transcript_text(self):
        self.panel.send("add sub")
        self._drain()
        self.assertTrue(self.panel.transcript_text().startswith("user: add sub\n"))

    def test_themes(self):
        self.panel.send("add sub")
        self._drain()
        self.panel.apply_theme("light")
        self.panel.apply_theme("dark")


if __name__ == "__main__":
    unittest.main()
