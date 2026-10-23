"""Source samples remain meaningful when Tag Lab simulates image designs."""
import unittest
import json
import socket
import threading
import time
from daemon import tagsim
from tools.hmi_deployer.taglab import design_simulation_frame


class GroundedSimulationTests(unittest.TestCase):
    def project(self):
        return {"pages": [{"widgets": [
            {"type": "Text", "properties": {"text": "78.2 C", "_simulationSample": 78.2,
                "_simulationDecimals": 1}, "bindings": {"text": {"tag": "sim.temperature", "sim": "number"}}},
            {"type": "Text", "properties": {"text": "0 rpm", "_simulationSample": 0,
                "_simulationDecimals": 0}, "bindings": {"text": {"tag": "sim.speed", "sim": "number"}}},
            {"type": "ShButton", "properties": {"_simulationDefaults": {"sim.heater": True}},
                "actions": {"clicked": {"kind": "toggle", "tag": "sim.heater"}}}]}]}

    def test_source_values_at_zero_then_dynamic_numbers_stable_boolean(self):
        project = self.project()
        initial = design_simulation_frame(project, 0)
        later = design_simulation_frame(project, tagsim.PROCESS_PERIOD_S / 4)
        self.assertEqual(initial, {"sim.temperature": 78.2, "sim.speed": 0, "sim.heater": True})
        self.assertNotEqual(initial["sim.temperature"], later["sim.temperature"])
        self.assertNotEqual(initial["sim.speed"], later["sim.speed"])
        self.assertIs(later["sim.heater"], True)

    def test_action_default_does_not_invent_physical_tag(self):
        project = self.project()
        button = project["pages"][0]["widgets"][-1]
        button["properties"]["_simulationDefaults"] = {"plant.heater": True, "sim.unreferenced": True}
        button["actions"]["clicked"]["tag"] = "plant.heater"
        self.assertNotIn("plant.heater", tagsim.plan(project))
        self.assertNotIn("sim.unreferenced", tagsim.plan(project))

    def test_simulated_boolean_write_roundtrip(self):
        signals = tagsim.plan(self.project())
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        worker = threading.Thread(target=tagsim.serve,
            args=(signals, port, 30, "127.0.0.1", 1.0), daemon=True)
        worker.start()
        time.sleep(.1)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.sendto(json.dumps({"cmd": "set", "id": "test", "tag": "sim.heater", "value": False}).encode(), ("127.0.0.1", port))
                ack = json.loads(client.recvfrom(8192)[0])
                self.assertTrue(ack["ok"])
                client.sendto(b'{"cmd":"subscribe"}', ("127.0.0.1", port))
                frame = json.loads(client.recvfrom(8192)[0])
                self.assertIs(frame["tags"]["sim.heater"], False)
        finally:
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
