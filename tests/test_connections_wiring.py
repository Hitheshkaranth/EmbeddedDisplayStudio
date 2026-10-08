"""Saved connections reach both model pickers.

* AI Design's provider combo lists every saved connection and ends with
  "Manage connections…", which opens the editor rather than switching;
* picking a connection points the connector at its endpoint and model;
* the Code agent's "Manage connections..." opens the dialog and offers the
  agent connection as studio-<name>/<model>.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tools.hmi_deployer.connections import Connection, ConnectionStore
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store = ConnectionStore(QSettings(os.path.join(self.dir.name, "s.ini"), QSettings.IniFormat))
        self.store.add(Connection("spark", "vllm", "http://spark:8080", api_key="k", model="qwen3.8"))


class AIDesignPicker(_Base):
    def _tab(self):
        from tools.hmi_deployer.ai_design import ODConnector
        from tools.hmi_deployer.ai_tab import AIDesignTab
        tab = AIDesignTab()
        self.addCleanup(tab.deleteLater)
        tab._connections = self.store
        tab.connector = ODConnector()
        tab.probe_connection = lambda: None
        tab._fill_models = lambda current: None
        tab._populate_providers()
        return tab

    def test_connections_and_the_manage_entry_are_listed(self):
        tab = self._tab()
        combo = tab.provider_combo
        self.assertGreaterEqual(combo.findData("conn:spark"), 0)
        self.assertEqual(combo.itemData(combo.count() - 1), "__manage__")

    def test_picking_a_connection_uses_its_endpoint(self):
        tab = self._tab()
        index = tab.provider_combo.findData("conn:spark")
        tab._on_provider_changed(index)
        byok = tab.connector.byok
        self.assertEqual((byok.provider, byok.baseUrl, byok.apiKey), ("vllm", "http://spark:8080", "k"))

    def test_the_manage_entry_opens_the_editor_and_keeps_the_pick(self):
        tab = self._tab()
        tab.provider_combo.setCurrentIndex(0)
        tab._on_provider_changed(0)
        manage = tab.provider_combo.count() - 1
        with mock.patch.object(tab, "open_connections") as opened, \
                mock.patch("tools.hmi_deployer.ai_tab.QTimer.singleShot", lambda _ms, fn: fn()):
            tab.provider_combo.setCurrentIndex(manage)
        opened.assert_called_once()
        self.assertEqual(tab.provider_combo.currentIndex(), 0)


class CodeAgentPicker(_Base):
    def test_manage_connections_offers_the_agent_connection(self):
        from designer.ide.agent_backend import ScriptedBackend
        from designer.ide.agent_panel import AgentPanel
        panel = AgentPanel(ScriptedBackend())
        self.addCleanup(panel.deleteLater)
        panel._connections = self.store
        self.store.set_default("agent", "spark")
        with mock.patch.object(QDialog, "exec", lambda self: 0), \
                mock.patch("designer.ide.agent_panel.QSettings") as settings:
            settings.return_value.value.return_value = ""
            panel._open_connections()
        labels = [panel.model_combo.itemText(i) for i in range(panel.model_combo.count())]
        self.assertIn("studio-spark/qwen3.8", labels)


if __name__ == "__main__":
    unittest.main()
