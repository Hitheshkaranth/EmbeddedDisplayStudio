"""Wave 5 B3 gate -- connections for the agents, the agent panel, and a
deterministic Modbus map.

* ConnectionStore: one list of model endpoints shared by AI Design and the
  Code agent; it writes the opencode provider entry itself (with a backup).
* The agent panel shows how long the agent has been working.
* Reads under the daemon folder are approved without asking.
* generate_map / apply_map: every bound value gets a register of the right
  kind and type; names become enum registers.
* The Python daemon gains "enum" and --modbus-live, like the C one.
FROZEN (skeleton).
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_layout_cab import PLAN as CAB_PLAN, _reply  # noqa: E402


class Connections(unittest.TestCase):
    def setUp(self):
        from PySide6.QtCore import QSettings
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.settings = QSettings(os.path.join(self.dir.name, "s.ini"), QSettings.IniFormat)

    def test_the_store_round_trips_and_picks_defaults(self):
        from tools.hmi_deployer.connections import Connection, ConnectionStore
        store = ConnectionStore(self.settings)
        self.assertEqual(store.list(), [])
        store.add(Connection(name="spark", kind="vllm", base_url="http://spark-ba51:8080",
                             api_key="k", model="ornith-1.5-35b-a3b", thinking=False))
        store.add(Connection(name="local", kind="ollama", base_url="http://127.0.0.1:11434", model="qwen3"))
        store.set_default("agent", "spark")
        again = ConnectionStore(self.settings)
        self.assertEqual([c.name for c in again.list()], ["spark", "local"])
        self.assertEqual(again.get("spark").api_key, "k")
        self.assertEqual(again.default_for("agent").name, "spark")
        self.assertEqual(again.default_for("design").name, "spark")   # first one when unset
        again.remove("local")
        self.assertEqual([c.name for c in ConnectionStore(self.settings).list()], ["spark"])
        with self.assertRaises(ValueError):
            again.add(Connection(name="spark", kind="vllm", base_url="http://x", model="m"))

    def test_an_opencode_entry_and_a_config_written_with_a_backup(self):
        from tools.hmi_deployer.connections import Connection, opencode_provider_entry, write_opencode_config
        conn = Connection(name="spark", kind="vllm", base_url="http://spark-ba51:8080", api_key="k",
                          model="ornith-1.5-35b-a3b", thinking=False)
        key, entry = opencode_provider_entry(conn)
        self.assertEqual(key, "studio-spark")
        self.assertEqual(entry["options"]["baseURL"], "http://spark-ba51:8080/v1")
        self.assertEqual(entry["options"]["apiKey"], "k")
        model = entry["models"]["ornith-1.5-35b-a3b"]
        self.assertEqual(model["options"]["chat_template_kwargs"], {"enable_thinking": False})
        path = os.path.join(self.dir.name, "opencode.jsonc")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{\n  // mine\n  "model": "other/x",\n  "provider": {"other": {"npm": "x"}}\n}\n')
        ref = write_opencode_config([conn], path)
        self.assertEqual(ref, "studio-spark/ornith-1.5-35b-a3b")
        backups = [f for f in os.listdir(self.dir.name) if f.startswith("opencode.jsonc.before-")]
        self.assertEqual(len(backups), 1)
        from designer.layout.intake import loads_lenient
        with open(path, encoding="utf-8") as fh:
            data = loads_lenient(fh.read())
        self.assertIn("other", data["provider"])                # the user's own entries stay
        self.assertIn("studio-spark", data["provider"])
        self.assertEqual(data["model"], "other/x")              # the default is not taken over


class AgentPanelTime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_elapsed_time_while_busy_and_the_total_after(self):
        from designer.ide.agent_panel import AgentPanel
        from test_ide_agent_panel import ScriptedBackend
        clock = [1000.0]
        panel = AgentPanel(ScriptedBackend(), clock=lambda: clock[0])
        self.addCleanup(panel.deleteLater)
        panel._set_busy(True)
        clock[0] += 65
        panel._tick_elapsed()
        self.assertEqual(panel.elapsed_label.text(), "01:05")
        clock[0] += 249
        panel._set_busy(False)
        self.assertEqual(panel.elapsed_label.text(), "done in 5m 14s")

    def test_reads_under_the_daemon_folder_are_approved(self):
        from designer.ide.agent_panel import auto_permission
        daemon = os.path.join(ROOT, "daemon")
        self.assertEqual(auto_permission({"type": "external_directory", "pattern": os.path.join(daemon, "*")},
                                         daemon), "always")
        self.assertIsNone(auto_permission({"type": "external_directory", "pattern": "C:/Windows/*"}, daemon))
        self.assertIsNone(auto_permission({"type": "edit", "pattern": os.path.join(daemon, "hwd.json")}, daemon))


def _cab_project():
    from tools.hmi_deployer.ai_generator import AIDesignGenerator
    return AIDesignGenerator().generate(_reply(CAB_PLAN), 1024, 768)


class ModbusMap(unittest.TestCase):
    def test_every_bound_value_gets_a_register_of_the_right_kind(self):
        from designer.ide.modbus_map import apply_map, generate_map
        project = _cab_project()
        mapping = generate_map(project, host="172.16.20.50")
        mb = mapping["modbus"]
        self.assertEqual(mb["host"], "172.16.20.50")
        tags = mb["tags"]
        rebind = mapping["rebind"]
        self.assertEqual(rebind["train.speed"], "mb.train.speed")
        speed = tags["mb.train.speed"]
        self.assertEqual((speed["kind"], speed["type"]), ("input", "float32"))
        doors = tags[rebind["train.doors_left"]]
        self.assertEqual(doors["kind"], "discrete")
        nxt = tags[rebind["train.next_station"]]
        self.assertEqual((nxt["kind"], nxt["type"]), ("input", "uint16"))
        self.assertIn("Indiranagar", nxt["enum"])               # the station line's names
        used = {}
        for name, t in tags.items():                            # no two tags share a register
            span = 2 if t["type"] in ("int32", "uint32", "float32") else 1
            for a in range(t["address"], t["address"] + span):
                key = (t["kind"] in ("coil", "discrete"), t["kind"], a)
                self.assertNotIn(key, used, name)
                used[key] = name
        count = apply_map(project, mapping)
        self.assertGreaterEqual(count, 10)
        tags_now = {b.tag for p in project.pages for w in p.walk() for b in w.bindings.values()}
        self.assertTrue(all(t.startswith("mb.") for t in tags_now if t != "*"))

    def test_the_config_is_written_from_the_template(self):
        from designer.ide.modbus_map import generate_map, write_hwd
        project = _cab_project()
        with tempfile.TemporaryDirectory() as d:
            path = write_hwd(d, generate_map(project, host="10.0.0.5"))
            with open(path, encoding="utf-8") as fh:
                cfg = json.load(fh)
            self.assertEqual(cfg["modbus"]["host"], "10.0.0.5")
            self.assertIn("daemon", cfg)
            self.assertIn("gpio", cfg)


class PythonDaemonEnum(unittest.TestCase):
    def test_enum_registers_and_modbus_live(self):
        sys.path.insert(0, os.path.join(ROOT, "daemon"))
        import hmi_hwd
        self.assertIn("--modbus-live", hmi_hwd.cli_flags())
        tcfg = {"kind": "input", "address": 0, "type": "uint16", "enum": ["A", "B", "C"]}
        self.assertEqual(hmi_hwd.modbus_publish_value(tcfg, 2), "C")
        self.assertEqual(hmi_hwd.modbus_publish_value(tcfg, 7), 7)
        self.assertEqual(hmi_hwd.modbus_raw_for_write(tcfg, "B"), 1)
        with self.assertRaises(ValueError):
            hmi_hwd.modbus_raw_for_write(tcfg, "Z")


if __name__ == "__main__":
    unittest.main()
