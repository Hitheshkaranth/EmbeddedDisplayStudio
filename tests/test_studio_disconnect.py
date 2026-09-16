"""The Studio can drop the link to a panel, not only make one.

Connect starts the telemetry relay and hands the panel's tag catalogue to
the Designer; Disconnect must undo both, reset every indicator that said
"link up", and -- while a connect is still in flight -- cancel it.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer.mainwindow import MainWindow  # noqa: E402


class _FakeRelay(QObject):
    """Stands in for TelemetryRelay: records start/stop, never touches SSH."""
    error = Signal(str)
    catalogueReceived = Signal(list)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeWorker:
    def __init__(self):
        self.cancelled = False

    def isRunning(self):
        return True

    def cancel(self):
        self.cancelled = True


class DisconnectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls._stylesheet, cls._font = cls.app.styleSheet(), cls.app.font()
        cls._last_bundle = QSettings("MIL-HMI", "Deployer").value("last_bundle", "")

    @classmethod
    def tearDownClass(cls):
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)
        QSettings("MIL-HMI", "Deployer").setValue("last_bundle", cls._last_bundle)

    def setUp(self):
        self.window = MainWindow()
        self.addCleanup(self._dispose)

    def _dispose(self):
        self.window._stop_all_senders()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _connect(self):
        """What a successful Test Connection leaves behind, without SSH."""
        import tools.hmi_deployer.mainwindow as module
        original = module.TelemetryRelay
        module.TelemetryRelay = _FakeRelay
        self.addCleanup(lambda: setattr(module, "TelemetryRelay", original))
        window = self.window
        window._set_link_state("connected")
        window.device_panel.set_led_state(1)
        window.start_relay()
        window._on_catalogue(["di.estop", "do.relay1"])
        return window.relay

    def test_the_button_is_only_live_with_something_to_drop(self):
        window = self.window
        self.assertFalse(window.btn_disconnect.isEnabled())
        window._set_link_state("connecting")
        self.assertTrue(window.btn_disconnect.isEnabled())
        self.assertEqual(window.btn_disconnect.text(), "Cancel")
        window._set_link_state("connected")
        self.assertEqual(window.btn_disconnect.text(), "Disconnect")
        window._set_link_state("fault")
        self.assertFalse(window.btn_disconnect.isEnabled())

    def test_disconnect_stops_the_relay_and_forgets_the_panel(self):
        window = self.window
        relay = self._connect()
        self.assertTrue(relay.started)
        self.assertIn("di.estop", window.designer_workspace.bindings.tags)

        window.disconnect_panel()

        self.assertTrue(relay.stopped)
        self.assertIsNone(window.relay)
        self.assertEqual(window._link_state, "idle")
        self.assertEqual(window.btn_test.text(), "Connect")
        self.assertFalse(window.btn_disconnect.isEnabled())
        self.assertEqual(window.device_panel.get_led_state(), 0)
        self.assertIn("DISCONNECTED", window.lbl_connection.text())
        self.assertNotIn("di.estop", window.designer_workspace.bindings.tags)

    def test_cancel_stops_a_connect_in_flight(self):
        window = self.window
        window._set_link_state("connecting")
        worker = _FakeWorker()
        window._ssh_workers.append(worker)
        window.disconnect_panel()
        self.assertTrue(worker.cancelled)
        self.assertEqual(window._link_state, "idle")

    def test_disconnect_when_idle_is_a_no_op(self):
        window = self.window
        before = window.lbl_connection.text()
        window.disconnect_panel()
        self.assertEqual(window.lbl_connection.text(), before)
        self.assertEqual(window._link_state, "idle")


if __name__ == "__main__":
    unittest.main()
