"""designer/ide/agent_panel.py -- the IDE agent panel.

The panel runs against ScriptedBackend
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


class AgentPanelQcTests(unittest.TestCase):
    """Regression checks for agent panel defects."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        QSettings("MIL-HMI", "Deployer").remove(SETTINGS_MODEL_KEY)
        self.backend = ScriptedBackend({"add sub": REPLY}, interval_ms=30)
        self.panel = AgentPanel(self.backend)
        self.panel.resize(420, 700)
        self.addCleanup(self.panel.deleteLater)
        self.panel.set_directory("/proj")

    def _drain(self, backend=None, panel=None):
        backend, panel = backend or self.backend, panel or self.panel
        waited = 0
        while (backend._pending or panel.is_busy()) and waited < 5000:
            QTest.qWait(20)
            waited += 20
        QTest.qWait(120)

    def _panel(self, script, interval_ms=0):
        backend = ScriptedBackend(script, interval_ms=interval_ms)
        panel = AgentPanel(backend)
        panel.resize(420, 700)
        self.addCleanup(panel.deleteLater)
        panel.set_directory("/proj")
        panel.show()
        return backend, panel

    def test_busy_while_hidden(self):
        # The Code tab is often not the current tab: busy must not depend on
        # a button being visible on screen.
        self.assertFalse(self.panel.isVisible())
        self.assertTrue(self.panel.send("add sub"))
        QTest.qWait(60)
        self.assertTrue(self.panel.is_busy())
        self.assertFalse(self.panel.send("second"))
        self._drain()
        self.assertFalse(self.panel.is_busy())

    def test_reply_renders_while_streaming(self):
        # A throttle, not a debounce: deltas 10 ms apart must show up before
        # the stream pauses.
        from PySide6.QtWidgets import QLabel
        backend, panel = self._panel({"go": [{"type": "text", "id": "x", "delta": f"w{i} "}
                                             for i in range(60)]}, interval_ms=10)
        panel.send("go")
        QTest.qWait(300)
        self.assertTrue(backend._pending, "the stream is still going")
        shown = [w for w in panel.findChildren(QLabel) if "w1 " in w.text()]
        self.assertTrue(shown, "streamed text is on screen before the stream ends")

    def test_tool_file_link_visible_and_output_escaped(self):
        from PySide6.QtWidgets import QLabel
        _backend, panel = self._panel({"t": [{"type": "tool", "id": "t1", "tool": "bash",
                                              "status": "completed", "title": "run",
                                              "input": {"path": "/proj/a.c"},
                                              "output": "<b>bold</b> & more", "error": ""}]})
        panel.send("t")
        QTest.qWait(150)
        links = [w for w in panel.findChildren(QLabel) if "href" in w.text()]
        self.assertTrue(any(w.isVisibleTo(panel) for w in links),
                        "the file link is visible without expanding the block")
        holders = [w for w in panel.findChildren(QLabel) if "bold" in w.text()]
        self.assertTrue(holders)
        for label in holders:
            self.assertTrue(label.textFormat() == Qt.PlainText or "<b>bold</b>" not in label.text(),
                            "tool output is shown as text, never rendered as HTML")

    def test_user_text_is_plain(self):
        from PySide6.QtWidgets import QLabel
        self.panel.send("a *b* <i>c</i>")
        labels = [w for w in self.panel.findChildren(QLabel) if "a *b*" in w.text()]
        self.assertTrue(labels)
        self.assertEqual(labels[0].textFormat(), Qt.PlainText)

    def test_usage_is_visible(self):
        self.panel.show()
        self.panel.send("add sub")
        self._drain()
        self.assertFalse(self.panel.state_label.isHidden())
        self.assertIn("150", self.panel.state_label.text())

    def test_saved_model_survives_when_not_offered(self):
        QSettings("MIL-HMI", "Deployer").setValue(SETTINGS_MODEL_KEY, "fake/elsewhere")
        panel = AgentPanel(ScriptedBackend())
        self.addCleanup(panel.deleteLater)
        panel.set_directory("/proj")
        self.assertEqual(panel.selected_model(), ModelRef("fake", "coder"))
        self.assertEqual(QSettings("MIL-HMI", "Deployer").value(SETTINGS_MODEL_KEY), "fake/elsewhere")

    def test_blocks_do_not_shadow_qwidget_methods(self):
        from PySide6.QtWidgets import QWidget
        import designer.ide.agent_panel as ap
        for name in dir(ap):
            cls = getattr(ap, name)
            if isinstance(cls, type) and issubclass(cls, QWidget) and cls.__module__ == ap.__name__:
                for attr in ("update", "show", "hide", "close", "repaint"):
                    self.assertNotIn(attr, cls.__dict__, f"{name}.{attr} shadows QWidget.{attr}")

    def test_scrolls_to_bottom(self):
        backend, panel = self._panel({"long": [{"type": "text", "id": f"x{i}", "delta": "line\n\nline"}
                                               for i in range(30)]})
        panel.send("long")
        self._drain(backend, panel)
        bar = panel._transcript_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.value(), bar.maximum())

    def test_error_state_is_shown(self):
        from designer.ide.agent_backend import STARTING
        self.backend._set_state(STARTING, "Starting opencode...")
        self.assertIn("Starting", self.panel.state_label.text())
        self.backend._set_state(ERROR, "opencode is not installed")
        self.assertIn("#", self.panel.state_label.styleSheet() + self.panel.styleSheet(),
                      "the error line is coloured")


if __name__ == "__main__":
    unittest.main()
