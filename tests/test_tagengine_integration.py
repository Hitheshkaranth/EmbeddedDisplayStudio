"""
tests/test_tagengine_integration.py
Layer: Test (W11)
End-to-end integration: daemon --sim -> UDP -> TagEngine -> real QML.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

# Must be set BEFORE PySide6 imports
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Add gui to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "gui")))

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
from hmi_loader.tagengine import TagEngine

class TestTagEngineIntegration(unittest.TestCase):
    """
    Integration tests for TagEngine and QML binding (CONTRACT 2).
    """
    _port_counter = 5150

    @classmethod
    def setUpClass(cls):
        """Create the QGuiApplication once for all tests in this class."""
        cls.app = QGuiApplication.instance()
        if not cls.app:
            cls.app = QGuiApplication(sys.argv)

    def setUp(self):
        """
        Starts the daemon subprocess with --sim on non-default ports,
        and constructs the TagEngine.
        """
        self.__class__._port_counter += 2
        self.cmd_port = self.__class__._port_counter
        self.telemetry_port = self.__class__._port_counter + 1

        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "hwd.json")
        config_data = {
            "daemon": {
                "cmd_port": self.cmd_port,
                "telemetry_sink": f"127.0.0.1:{self.telemetry_port}",
                "poll_interval_ms": 50
            },
            "gpio": {
                "chip": "/dev/gpiochip3",
                "inputs": {"di.estop": {"offset": 4, "active_low": True}},
                "outputs": {"do.relay1": {"offset": 5, "active_low": False, "initial": 0}}
            }
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f)
            
        cmd = [
            sys.executable,
            os.path.join(os.path.dirname(__file__), "..", "daemon", "hmi_hwd.py"),
            "--config", self.config_path,
            "--sim"
        ]
        self.daemon_proc = subprocess.Popen(cmd)
        
        self.qml_engine = QQmlApplicationEngine()
        self.tag_engine = TagEngine(
            expected_tags=["di.estop", "do.relay1"],
            rx_port=self.telemetry_port,
            daemon_port=self.cmd_port
        )
        
        self.qml_engine.rootContext().setContextProperty("Tags", self.tag_engine.tagMap())
        self.qml_engine.rootContext().setContextProperty("Bus", self.tag_engine)

    def tearDown(self):
        """Always terminate the subprocess in tearDown, even on failure."""
        if self.daemon_proc.poll() is None:
            self.daemon_proc.terminate()
            try:
                self.daemon_proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.daemon_proc.kill()
        self.temp_dir.cleanup()
        del self.tag_engine
        del self.qml_engine

    def _wait_for(self, condition, timeout_sec=5.0):
        """Pump the Qt event loop until condition is true or timeout."""
        start = time.time()
        while time.time() - start < timeout_sec:
            if condition():
                return True
            self.app.processEvents()
            time.sleep(0.01)
        return False

    def test_qml_binding_and_write(self):
        """
        - QML sees a live tag value and Tags.online becomes true
        - Bus.value("does.not.exist", "FALLBACK") returns the fallback
        - Bus.write("do.relay1", True) reaches the daemon and comes back as read-back state
        """
        # Create a small inline QML component from a REAL FILE ON DISK
        qml_path = os.path.join(self.temp_dir.name, "TestComponent.qml")
        with open(qml_path, "w", encoding="utf-8") as f:
            f.write('''
import QtQuick

Item {
    id: root
    property bool isOnline: Tags.online
    property int tagValue: Tags.do_relay1 !== undefined ? Tags.do_relay1 : -1
    property string fallbackVal: Bus.value("does.not.exist", "FALLBACK")
    
    function writeRelay(val) {
        Bus.write("do.relay1", val)
    }
}
''')
        
        component = QQmlComponent(self.qml_engine, QUrl.fromLocalFile(qml_path))
        self.assertEqual(component.status(), QQmlComponent.Ready, f"QML Component failed to load: {component.errorString()}")
        
        item = component.create()
        self.assertIsNotNone(item, "Failed to create QML item")
        
        # Wait for online to become true
        self.assertTrue(self._wait_for(lambda: item.property("isOnline")), "Link never came online")
        
        # Check fallback
        self.assertEqual(item.property("fallbackVal"), "FALLBACK")
        
        # Write to do.relay1 and observe read-back
        self.tag_engine.write("do.relay1", True)
        
        # The daemon will ack it and update its state, then publish. 
        # So we wait for the tag to become 1 (True).
        self.assertTrue(self._wait_for(lambda: item.property("tagValue") == 1), "Read-back never matched written value")

    def test_malformed_datagram_resilience(self):
        """
        - a malformed/foreign datagram sent to the engine's port does not raise
        """
        # Send a garbage datagram directly to the TagEngine's listen port
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(b"garbage json that is totally invalid", ("127.0.0.1", self.telemetry_port))
        sock.close()
        
        # Pump the event loop to ensure TagEngine processes it
        self._wait_for(lambda: False, timeout_sec=0.2)
        
        # Since it's still alive (test didn't crash) and we can query rxErrors, we are good.
        self.assertGreaterEqual(self.tag_engine.rxErrors, 1, "rxErrors should have incremented")

if __name__ == "__main__":
    unittest.main()
