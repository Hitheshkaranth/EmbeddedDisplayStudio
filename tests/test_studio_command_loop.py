"""
tests/test_studio_command_loop.py
Layer: Test (Layer 3, Studio)

Offline, Tag Lab stands in for the panel's daemon: while it is sending, the
Studio answers the daemon's command port, so a button in the bezel that
does Bus.write("do.relay1", true) changes the tag Tag Lab is driving -- and
the change shows in Tag Lab's Commands log. The sink lives exactly as long
as Tag Lab is sending. Connected, the relay takes the port instead and the
panel's own tag catalogue is offered in the Designer's binding inspector.
"""
import json
import os
import socket
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer.mainwindow import MainWindow  # noqa: E402
from tools.hmi_deployer.taglab import COMMAND_SINK_DEFAULT_PORT, ConstantWaveform  # noqa: E402


def _port_free(port):
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _pump(seconds=0.2):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)


class StudioCommandLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._org, cls._name = cls.app.organizationName(), cls.app.applicationName()
        cls.app.setOrganizationName("MIL-HMI-tests")
        cls.app.setApplicationName("StudioCommandLoop")

    @classmethod
    def tearDownClass(cls):
        cls.app.setOrganizationName(cls._org)
        cls.app.setApplicationName(cls._name)

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.window._stop_all_senders()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_tag_lab_answers_preview_commands_while_sending(self):
        if not _port_free(COMMAND_SINK_DEFAULT_PORT):
            self.skipTest(f"UDP {COMMAND_SINK_DEFAULT_PORT} is held by another process")
        window = self.window
        model = window.taglab_panel.model()
        model.add_tag("do.relay1")
        self.assertIsNone(window._cmd_sink, "no sink before Tag Lab sends")

        window._on_taglab_start()
        self.assertIsNotNone(window._cmd_sink)
        self.assertTrue(window._cmd_sink.online)
        self.assertIs(window._cmd_sink._model, model)

        # What the preview's TagEngine sends for Bus.write("do.relay1", true).
        preview = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        preview.bind(("127.0.0.1", 0))
        preview.settimeout(1.0)
        self.addCleanup(preview.close)
        preview.sendto(json.dumps({"id": "gui-1", "cmd": "set", "tag": "do.relay1", "value": True}).encode(),
                       ("127.0.0.1", COMMAND_SINK_DEFAULT_PORT))
        _pump(0.3)   # the window polls the sink from a timer
        ack = json.loads(preview.recv(8192))
        self.assertEqual((ack["t"], ack["id"], ack["ok"]), ("ack", "gui-1", True))
        entry = model.find("do.relay1")
        self.assertIsInstance(entry.waveform, ConstantWaveform)
        self.assertEqual(entry.waveform.value, 1.0)
        # Other suites' engines may still be subscribing to this port, so
        # look for our rows rather than counting rows.
        def rows():
            table = window.taglab_panel._cmd_log
            return [(table.item(r, 3).text(), table.item(r, 4).text()) for r in range(table.rowCount())]
        self.assertEqual(rows().count(("set", "do.relay1")), 1, rows())

        # A second command lands on a later row, not on top of the first.
        preview.sendto(json.dumps({"id": "gui-2", "cmd": "ping"}).encode(),
                       ("127.0.0.1", COMMAND_SINK_DEFAULT_PORT))
        _pump(0.3)
        preview.recv(8192)
        logged = rows()
        self.assertEqual(logged.count(("set", "do.relay1")), 1, logged)
        self.assertGreater(logged.index(("ping", "")), logged.index(("set", "do.relay1")), logged)

        window._on_taglab_stop()
        self.assertIsNone(window._cmd_sink)
        self.assertTrue(_port_free(COMMAND_SINK_DEFAULT_PORT), "stopping Tag Lab releases the port")

    def test_panel_catalogue_reaches_the_designer_and_leaves_with_the_relay(self):
        window = self.window
        workspace = window.designer_workspace
        workspace.add_widget("ShGauge")
        gauge = workspace.project.pages[0].widgets[0]
        from designer.model import DesignerBinding
        gauge.bindings["value"] = DesignerBinding("ai.pot")
        window._on_catalogue(["di.estop", "do.relay1", "ai.pot"])
        self.assertEqual(workspace.bindings.tags, ["ai.pot", "di.estop", "do.relay1"])
        self.assertEqual(workspace.actions.tags, ["ai.pot", "di.estop", "do.relay1"])
        # Dropping the relay restores the design's own list.
        window._stop_all_senders()
        self.assertEqual(workspace.bindings.tags, ["ai.pot"])


if __name__ == "__main__":
    unittest.main()
