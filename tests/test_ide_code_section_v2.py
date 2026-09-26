"""designer/ide/code_section.py -- the v2 panes wired together (integration)."""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QEventLoop, QObject, QSettings, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from designer.ide.agent_backend import ScriptedBackend  # noqa: E402
from designer.ide.code_section import BACKEND_TAB, OUTLINE_TAB, SETTINGS_ROOT_KEY, CodeSection  # noqa: E402
from designer.ide.tag_source import EngineTagSource, SimulatedTagSource  # noqa: E402
from designer.ui.designer_workspace import DesignerWorkspace  # noqa: E402
from ide_v2_fixture import edsui_text  # noqa: E402


def spin(ms):
    deadline = time.monotonic() + ms / 1000
    while time.monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()


class FakeEngine(QObject):
    onlineChanged = Signal()

    def __init__(self):
        super().__init__()
        self.online = False

    def get_online(self):
        return self.online

    def value(self, name, fallback=None):
        return {"ai.rpm": 777.0}.get(name, fallback)

    def write(self, tag, value):
        pass


class CodeSectionV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        QSettings("MIL-HMI", "Deployer").remove(SETTINGS_ROOT_KEY)
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="ide-v2-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "project.edsui")
        with open(self.path, "w", encoding="utf-8", newline="\n") as f:
            f.write(edsui_text())
        self.ws = DesignerWorkspace()
        self.addCleanup(self.ws.close)
        self.ws.load_file(self.path)
        self.backend = ScriptedBackend()
        self.section = CodeSection(self.ws, backend=self.backend)
        self.addCleanup(self.section.shutdown)
        self.addCleanup(self.section.deleteLater)

    def test_panes_and_index(self):
        self.assertIs(self.section.left.widget(OUTLINE_TAB), self.section.outline)
        self.assertIs(self.section.left.widget(BACKEND_TAB), self.section.backend_pane)
        self.assertEqual(self.section.index().summary()["widgets"], 10)
        self.assertEqual(len(self.section.outline.widget_ids()), 10)
        self.assertIn("ai.rpm", self.section.backend_pane.tags())
        self.assertGreater(self.section.index().widget("rpm").line, 0)
        self.ws.add_widget("ShGauge")
        self.assertEqual(self.section.index().summary()["widgets"], 11)
        self.assertEqual(len(self.section.outline.widget_ids()), 11)

    def test_tag_click_filters_outline(self):
        pane = self.section.backend_pane
        pane.table.cellClicked.emit(pane.tags().index("ai.rpm"), 0)
        self.assertEqual(self.section.outline.widget_ids(), ["rpm", "rpm2"])

    def test_outline_source_opens_edsui_at_line(self):
        line = self.section.index().widget("oil").line
        self.section.outline.sourceRequested.emit("oil", line)
        editor = self.section.tabs.currentWidget()
        self.assertEqual(os.path.normcase(self.section.tabs.current_path()), os.path.normcase(self.path))
        self.assertEqual(editor.textCursor().blockNumber() + 1, line)

    def test_simulator_then_engine(self):
        self.section.show()
        spin(50)
        self.assertIsInstance(self.section.tag_source(), SimulatedTagSource)
        self.assertTrue(self.section.simulator.is_online())
        engine = FakeEngine()
        self.section.set_engine_provider(lambda: engine)
        self.assertIsInstance(self.section.tag_source(), SimulatedTagSource, "offline engine: keep simulating")
        engine.online = True
        engine.onlineChanged.emit()
        self.assertIsInstance(self.section.tag_source(), EngineTagSource)
        self.assertFalse(self.section.simulator.is_online())
        self.section.backend_pane.refresh_values()
        self.assertEqual(self.section.backend_pane.value_text("ai.rpm"), "777")
        engine.online = False
        engine.onlineChanged.emit()
        self.assertIsInstance(self.section.tag_source(), SimulatedTagSource)
        self.section.hide()
        self.assertFalse(self.section.simulator.is_online())

    def test_agent_gets_design_and_quick_actions(self):
        self.section.agent.set_directory(self.dir)
        self.ws.select_widget("rpm")
        labels = [a.label for a in self.section.agent.quick_actions()]
        self.assertEqual(labels[0], "Explain rpm")
        self.assertTrue(self.section.agent.send("hello"))
        context = [c for c in self.backend.calls if c[0] == "send"][-1][1][2]
        self.assertIn("## Selected widget", context["design"])
        self.assertIn("rpm (ShGauge)", context["design"])

    def test_generate_backend(self):
        result = self.section.generate_backend(overwrite=False)
        self.assertEqual(len(result["written"]), 4)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "backend", "backend.py")))
        self.assertTrue(self.section.tabs.current_path().endswith("backend.py"))
        again = self.section.generate_backend(overwrite=False)
        self.assertEqual(len(again["skipped"]), 4)


if __name__ == "__main__":
    unittest.main()
