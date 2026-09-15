"""
tests/test_bus_liveness.py
Layer: Test (Layer 2, GUI loader)

A binding written the way the README tells application authors to write it
-- ``value: Bus.value("ai.pot", 0)`` -- must follow the tag. It did not: the
engine's ``value()`` was a Python slot, a QML binding cannot depend on what a
slot reads, and every gauge bound that way showed its first value for ever
while ``Tags.ai_pot`` beside it moved. ``expose_to_qml`` now binds ``Bus`` to
a QML shim whose ``value()`` reads ``Tags`` inside the binding itself. These
tests drive a real TagEngine with real datagrams and watch the bindings.
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
sys.path.insert(0, str(REPO_ROOT / "gui"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QCoreApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hmi_loader.tagengine import TagEngine, expose_to_qml  # noqa: E402


APP_QML = b"""
import QtQuick 2.15
Item {
    property var reading: Bus.value("ai.pot", 0)
    property string state: (Bus.value("ai.pot", 0) > 3.0) ? "fault" : "ok"
    property var underscore: Bus.value("ai_pot", 0)
    property var missing: Bus.value("ai.nope", -1)
    property var late: Bus.value("di.late", "none")
    property var viaTags: Tags.ai_pot
    property bool online: Bus.online
    property int acks: 0
    property int alarms: Bus.alarmCount
    Connections { target: Bus; function onAckReceived(id, ok, err) { acks += 1 } }
}
"""


class BusLivenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # A stand-in daemon: whatever the engine sends lands here, and frames
        # sent from here reach the engine's own ephemeral port.
        self.daemon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.daemon.bind(("127.0.0.1", 0))
        self.daemon.settimeout(0.5)
        self.engine_obj = TagEngine(["ai.pot"], rx_port=0, allow_any_port=True,
                                    daemon_host="127.0.0.1", daemon_port=self.daemon.getsockname()[1],
                                    alarm_defs=[{"tag": "ai.pot", "label": "Pot",
                                                 "critical": {"op": ">", "value": 3.0}}])
        self.qml = QQmlEngine()
        self.bus = expose_to_qml(self.qml, self.qml.rootContext(), self.engine_obj)
        self.component = QQmlComponent(self.qml)
        self.component.setData(QByteArray(APP_QML), "")
        self.item = self.component.create()
        self.assertIsNotNone(self.item, [e.toString() for e in self.component.errors()])
        # Created objects belong to the JS engine; keep this one for the test.
        QQmlEngine.setObjectOwnership(self.item, QQmlEngine.CppOwnership)
        self.seq = 0
        self.addCleanup(self.daemon.close)

    def frame(self, tags):
        self.seq += 1
        payload = {"t": "tags", "seq": self.seq, "ts": 0.0, "src": "hmi-hwd", "tags": tags}
        self.daemon.sendto(json.dumps(payload).encode(), ("127.0.0.1", self.engine_obj.rx_port))
        self.pump()

    @staticmethod
    def pump(seconds=0.1):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)

    def test_shim_is_installed_not_the_engine(self):
        self.assertIsNot(self.bus, self.engine_obj)
        self.assertIs(self.bus.parent(), self.engine_obj)

    def test_value_bindings_follow_the_tag(self):
        self.assertEqual(self.item.property("reading"), 0)
        self.assertEqual(self.item.property("state"), "ok")
        self.frame({"ai.pot": 1.5})
        self.assertEqual(self.item.property("reading"), 1.5)
        self.assertEqual(self.item.property("underscore"), 1.5)
        self.assertEqual(self.item.property("viaTags"), 1.5)
        self.frame({"ai.pot": 3.5})
        self.assertEqual(self.item.property("reading"), 3.5)
        self.assertEqual(self.item.property("state"), "fault")
        self.assertEqual(self.item.property("alarms"), 1)
        # A failed read publishes null (CONTRACT 2.4): the fallback returns.
        self.frame({"ai.pot": None})
        self.assertEqual(self.item.property("reading"), 0)
        self.assertEqual(self.item.property("state"), "ok")
        self.assertEqual(self.item.property("alarms"), 0)

    def test_missing_and_late_tags(self):
        self.assertEqual(self.item.property("missing"), -1)
        self.assertEqual(self.item.property("late"), "none")
        # A tag the manifest never declared still arrives live.
        self.frame({"ai.pot": 1.0, "di.late": True})
        self.assertEqual(self.item.property("late"), True)
        self.frame({"ai.pot": 1.0, "di.late": False})
        self.assertEqual(self.item.property("late"), False)
        self.assertEqual(self.item.property("missing"), -1)

    def test_online_and_commands_and_acks_forward(self):
        self.assertFalse(self.item.property("online"))
        self.frame({"ai.pot": 1.0})
        self.assertTrue(self.item.property("online"))
        # Drain the subscribe the engine sent at start-up.
        try:
            while True:
                self.daemon.recv(8192)
        except socket.timeout:
            pass
        self.bus.write("do.relay1", True)
        self.bus.pulse("do.relay1", 250)
        self.pump(0.05)
        commands = []
        try:
            while True:
                commands.append(json.loads(self.daemon.recv(8192)))
        except socket.timeout:
            pass
        kinds = [(c["cmd"], c["tag"]) for c in commands if c.get("cmd") in ("set", "pulse")]
        self.assertEqual(kinds, [("set", "do.relay1"), ("pulse", "do.relay1")])
        write_id = next(c["id"] for c in commands if c.get("cmd") == "set")
        self.daemon.sendto(json.dumps({"t": "ack", "id": write_id, "ok": True}).encode(),
                           ("127.0.0.1", self.engine_obj.rx_port))
        self.pump()
        self.assertEqual(self.item.property("acks"), 1)


if __name__ == "__main__":
    unittest.main()
