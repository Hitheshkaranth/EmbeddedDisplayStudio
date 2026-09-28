"""Wave 1 skeleton: the CONTRACT 13 model changes that every worker builds on.
Green on the skeleton; must stay green."""
import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from designer.model import DesignerAction, DesignerBinding, DesignerProject  # noqa: E402
from designer.model.project import ACTION_KINDS  # noqa: E402


class OldDesignsUnchanged(unittest.TestCase):
    def test_saved_designs_roundtrip_byte_for_byte(self):
        for path in (REPO_ROOT / "tests" / "hmi_ui" / "fixtures" / "engine-dashboard" / "project.edsui",
                     REPO_ROOT / "designer" / "templates" / "automotive_cluster_demo.edsui"):
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                again = DesignerProject.from_dict(data).to_dict()
                self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(
                    DesignerProject.from_dict(again).to_dict(), sort_keys=True))
                for page, page2 in zip(data["pages"], again["pages"]):
                    for w, w2 in zip(page["widgets"], page2["widgets"]):
                        for prop, b in (w.get("bindings") or {}).items():
                            if isinstance(b, dict):
                                self.assertEqual(set(w2["bindings"][prop]), set(b) | {
                                    "tag", "format", "multiplier", "offset", "unit", "warning", "critical"})

    def test_classic_binding_keys(self):
        self.assertEqual(list(DesignerBinding("a.b").to_dict()),
                         ["tag", "format", "multiplier", "offset", "unit", "warning", "critical"])

    def test_classic_action_shapes(self):
        self.assertEqual(DesignerAction("write", "a.b").to_dict(), {"kind": "write", "tag": "a.b"})
        self.assertEqual(DesignerAction("pulse", "a.b", ms=100).to_dict(), {"kind": "pulse", "tag": "a.b", "ms": 100})
        self.assertEqual(DesignerAction("navigate", page="p2").to_dict(), {"kind": "navigate", "page": "p2"})

    def test_screen_without_idle(self):
        self.assertEqual(set(DesignerProject().to_dict()["screen"]), {"width", "height", "background", "theme"})


class NewShapes(unittest.TestCase):
    def test_action_list_roundtrip(self):
        raw = [{"kind": "write", "tag": "a.x", "value": 1},
               {"kind": "increment", "tag": "s.set", "step": 2.0, "max": 10.0, "confirm": "Sure?"},
               {"kind": "back"},
               {"kind": "ack", "tag": "*"},
               {"kind": "shelve", "tag": "a.t", "ms": 1000}]
        action = DesignerAction.from_data(raw)
        self.assertEqual(action.kind, "write")
        self.assertEqual([a.kind for a in action.all()], ["write", "increment", "back", "ack", "shelve"])
        self.assertEqual(action.to_dict(), raw)
        self.assertEqual(DesignerAction.from_data({"kind": "shelve", "tag": "a.t"}).ms, 600000)
        with self.assertRaises(ValueError):
            DesignerAction.from_data([])

    def test_binding_fields_roundtrip(self):
        raw = {"tag": "", "format": "", "multiplier": 1.0, "offset": 0.0, "unit": "", "warning": "",
               "critical": "", "decimals": 2, "expr": "a.b * 2",
               "rules": [{"if": "> 1", "prop": "title", "value": "X"}], "alarm": {"priority": 2}}
        self.assertEqual(DesignerBinding.from_data(raw).to_dict(), raw)

    def test_project_roundtrip(self):
        raw = {"version": 1, "name": "n", "screen": {"width": 800, "height": 480, "background": "#101418",
                                                     "theme": "dark", "idle": {"dimAfterS": 60}},
               "pages": [{"id": "main", "name": "Main", "widgets": [
                   {"type": "ShButton", "id": "b", "geometry": {"x": 0, "y": 0, "width": 100, "height": 40},
                    "properties": {}, "bindings": {}, "children": [], "locked": False, "z": 0,
                    "actions": {"clicked": [{"kind": "toggle", "tag": "d.run"}, {"kind": "back"}]}}]}]}
        self.assertEqual(DesignerProject.from_dict(raw).to_dict(), raw)

    def test_kinds(self):
        self.assertEqual(ACTION_KINDS, ("write", "pulse", "navigate", "back", "toggle", "increment",
                                        "decrement", "ack", "shelve"))


class LivePreviewQml(unittest.TestCase):
    def test_every_kind_generates_a_handler(self):
        from designer.generators import QmlGenerator
        from designer.palette.widget_registry import default_registry
        project = DesignerProject.from_dict({"version": 1, "pages": [
            {"id": "main", "widgets": [
                {"type": "ShButton", "id": "b", "geometry": {"x": 0, "y": 0, "width": 100, "height": 40},
                 "actions": {"clicked": [{"kind": k, "tag": "a.b"} if k not in ("navigate", "back")
                                         else ({"kind": "navigate", "page": "p2"} if k == "navigate" else {"kind": "back"})
                                         for k in ACTION_KINDS]}}]},
            {"id": "p2", "name": "Two", "widgets": []}]})
        text = "\n".join(QmlGenerator(default_registry()).generate(project).values()) \
            if isinstance(QmlGenerator(default_registry()).generate(project), dict) \
            else str(QmlGenerator(default_registry()).generate(project))
        self.assertIn("onClicked: {", text)
        self.assertIn("!Bus.value(", text)
        self.assertIn("Bus.acknowledge(", text)


if __name__ == "__main__":
    unittest.main()
