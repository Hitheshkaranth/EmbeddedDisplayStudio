"""designer/ide/code_section.py -- the Code tab put together (integration).

Runs the real pieces with a ScriptedBackend in place of opencode. The last
class drives a real opencode server and model; it runs only with
OPENCODE_LIVE=1 (and OPENCODE_LIVE_MODEL=provider/model to pick the model).
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.agent_backend import OpencodeBackend, ScriptedBackend  # noqa: E402
from designer.ide.code_section import SETTINGS_ROOT_KEY, CodeSection  # noqa: E402
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402


def _wait(predicate, ms=5000):
    """Spins a QEventLoop, not QTest.qWait: in PySide6 6.11 qWait holds the
    GIL and starves the agent backend's threads (see test_ide_opencode)."""
    deadline = time.monotonic() + ms / 1000
    while not predicate() and time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    return predicate()


class CodeSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        QSettings("MIL-HMI", "Deployer").remove(SETTINGS_ROOT_KEY)
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-section-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        os.makedirs(os.path.join(self.dir, "src"))
        self.math = os.path.join(self.dir, "src", "math.c")
        with open(self.math, "w", newline="\n") as f:
            f.write("int add(int a, int b) { return a + b; }\n")
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.add_widget("ShGauge")
        self.ws.add_widget("ShButton")
        self.ws.bundle_dir = self.dir
        self.backend = ScriptedBackend({"sub": [
            {"type": "tool", "id": "t1", "tool": "edit", "status": "completed", "title": "src/math.c",
             "input": {"filePath": self.math}, "output": "ok", "error": ""},
            {"type": "file_edited", "path": self.math},
            {"type": "text", "id": "x", "delta": "Added sub."},
        ]})
        self.section = CodeSection(self.ws, backend=self.backend)
        self.section.resize(1400, 800)
        self.addCleanup(self.section.deleteLater)

    def test_follows_the_design_folder(self):
        self.ws.designChanged.emit()
        self.assertEqual(self.section.root(), self.dir)
        self.assertIn(os.path.join(self.dir, "src"), self.section.tree.visible_paths())

    def test_agent_starts_when_shown(self):
        self.ws.designChanged.emit()
        self.assertEqual(self.backend.calls, [])
        self.section.show()
        self.assertEqual(self.backend.calls[0], ("start", (self.dir,)))

    def test_design_is_pinned_first_with_preview(self):
        self.assertIs(self.section.tabs.widget(0), self.section.design)
        self.assertTrue(self.section.design.preview_visible())
        self.assertEqual(self.section.tabs.current_path(), "")

    def test_pick_widget_shows_its_code(self):
        self.section.show()
        target = [w.id for w in self.ws.current_page.widgets][1]
        self.section.picker.pick(target)
        self.assertIs(self.section.tabs.currentWidget(), self.section.design)
        self.assertEqual(self.ws.selected_widget().id, target)
        self.assertIn(f'"id": "{target}"', self.section.design.editor.code())

    def test_tree_opens_file_and_ctrl_s_saves(self):
        self.ws.designChanged.emit()
        self.section.show()
        self.section.tree.reveal(self.math)
        self.section.tree.fileActivated.emit(self.math)
        editor = self.section.tabs.editor_for(self.math)
        self.assertIsNotNone(editor)
        editor.setFocus()
        editor.moveCursor(QTextCursor.End)
        QTest.keyClicks(editor, "// x")
        QTest.keyClick(editor, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(editor, Qt.Key_Y, Qt.ControlModifier)
        QTest.keyClick(editor, Qt.Key_S, Qt.ControlModifier)
        with open(self.math) as f:
            self.assertTrue(f.read().endswith("// x"))

    def test_design_tab_keys_drive_the_designer(self):
        self.section.show()
        self.section.show_design()
        count = len(self.ws.current_page.widgets)
        self.section.design.preview.setFocus()
        QTest.keyClick(self.section.design.preview, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(len(self.ws.current_page.widgets), count - 1)
        QTest.keyClick(self.section.design.preview, Qt.Key_Y, Qt.ControlModifier)
        self.assertEqual(len(self.ws.current_page.widgets), count)

    def test_agent_edit_reloads_the_open_file(self):
        self.ws.designChanged.emit()
        self.section.show()
        editor = self.section.open_file(self.math)
        with open(self.math, "a", newline="\n") as f:
            f.write("int sub(int a, int b) { return a - b; }\n")
        self.section.agent.send("sub")
        self.assertTrue(_wait(lambda: "sub(" in editor.code()))
        self.assertFalse(self.section.tabs.is_dirty(self.math))

    def test_agent_gets_the_editor_context(self):
        self.ws.designChanged.emit()
        self.section.show()
        self.section.open_file(self.math, line=1)
        self.section.agent.send("explain")
        context = self.backend.calls[-1][1][2]
        self.assertEqual(context["relative"], "src/math.c")

    def test_open_folder_and_theme(self):
        other = tempfile.mkdtemp(prefix="ide-other-")
        self.addCleanup(shutil.rmtree, other, True)
        self.section.open_folder(other)
        self.assertEqual(self.section.root(), os.path.abspath(other))
        self.section.apply_theme("light")
        self.section.apply_theme("dark")


@unittest.skipUnless(os.environ.get("OPENCODE_LIVE") == "1", "live opencode test: set OPENCODE_LIVE=1")
class LiveOpencodeTests(unittest.TestCase):
    """A real opencode server and model edit a file in a scratch project."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_agent_edits_a_file(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix="ide-live-"))
        self.addCleanup(shutil.rmtree, root, True)
        path = os.path.join(root, "math.c")
        with open(path, "w", newline="\n") as f:
            f.write("int add(int a, int b) { return a + b; }\n")
        ws = DesignerWorkspace()
        self.addCleanup(ws.close)
        ws.bundle_dir = root
        backend = OpencodeBackend()
        section = CodeSection(ws, backend=backend)
        self.addCleanup(section.shutdown)
        section.resize(1400, 800)
        section.show()
        ws.designChanged.emit()
        self.assertTrue(_wait(lambda: backend.state() == "ready", 60000), backend.detail())
        from designer.ide.opencode_client import ModelRef
        wanted = ModelRef.parse(os.environ.get("OPENCODE_LIVE_MODEL", ""))
        if wanted is not None:
            index = section.agent.model_combo.findText(wanted.label)
            self.assertGreaterEqual(index, 0, wanted.label)
            section.agent.model_combo.setCurrentIndex(index)
        editor = section.open_file(path)
        self.assertTrue(section.agent.send("Add a function int sub(int a, int b) returning a - b to math.c, "
                                           "right after add. Change nothing else."))
        self.assertTrue(_wait(lambda: not section.agent.is_busy() and "sub(" in editor.code(), 240000),
                        section.agent.transcript_text())
        kinds = [k for k, _ in section.agent.blocks()]
        self.assertIn("tool", kinds)
        self.assertIn("assistant", kinds)
        print("\n" + section.agent.transcript_text())


if __name__ == "__main__":
    unittest.main()
