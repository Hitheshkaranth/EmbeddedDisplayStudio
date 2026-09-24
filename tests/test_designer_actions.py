"""
tests/test_designer_actions.py
Layer: Test (Designer)

A designed screen must be able to *command* the machine, not only show it:
actions on widget signals, two-way controls, thresholds that colour a widget
and raise a panel alarm, series bindings, and page navigation. These tests
pin the .edsui shape, the generated QML, the manifest, the AI parser -- and,
because string-matching QML proves little, they load a generated page into
a real QML engine against a stub Bus and click the controls.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Property, Signal, Slot  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

from designer.generators.qml_generator import QmlGenerationError, QmlGenerator  # noqa: E402
from designer.model import (  # noqa: E402
    DesignerAction, DesignerBinding, DesignerPage, DesignerProject, DesignerWidget,
    parse_threshold,
)
from designer.palette.widget_registry import default_registry  # noqa: E402
from tools.hmi_deployer.ai_generator import AIDesignGenerator, build_system_prompt  # noqa: E402


def geometry(x=0, y=0, w=120, h=40):
    return {"x": x, "y": y, "width": w, "height": h}


def by_id(item, qml_id):
    """Resolve a QML ``id`` declared in the component that created ``item``."""
    return QQmlEngine.contextForObject(item).contextProperty(qml_id)


def widget(kind, wid, properties=None, bindings=None, actions=None, **geo):
    return DesignerWidget(kind, wid, geometry(**geo), properties or {}, bindings or {},
                          actions=actions or {})


class StubBus(QObject):
    """The slots and properties the generated QML expects of ``Bus``.

    Records every call so a test can assert what a click did. Mirrors the
    API contract the runtime implements (history / historyVersion /
    activeAlarms / acknowledge) without depending on that implementation.
    """
    historyVersionChanged = Signal()
    activeAlarmsChanged = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []
        self.values = {}
        self._version = 0
        self._alarms = []

    @Slot(str, "QVariant")
    def write(self, tag, value):
        self.calls.append(("write", tag, value))

    @Slot(str, int)
    def pulse(self, tag, ms):
        self.calls.append(("pulse", tag, ms))

    @Slot(str)
    def acknowledge(self, tag):
        self.calls.append(("acknowledge", tag))

    @Slot(str, result="QVariant")
    @Slot(str, "QVariant", result="QVariant")
    def value(self, name, fallback=None):
        return self.values.get(name, fallback)

    @Slot(str, int, result="QVariantList")
    def history(self, tag, count):
        return [1.0, 2.0, 3.0][:count]

    def _get_version(self):
        return self._version

    historyVersion = Property(int, _get_version, notify=historyVersionChanged)

    def _get_alarms(self):
        return self._alarms

    activeAlarms = Property("QVariantList", _get_alarms, notify=activeAlarmsChanged)


class ThresholdParsingTests(unittest.TestCase):
    def test_operators_and_bare_number(self):
        self.assertEqual(parse_threshold("> 80"), (">", 80.0))
        self.assertEqual(parse_threshold(">=80"), (">=", 80.0))
        self.assertEqual(parse_threshold("<  10"), ("<", 10.0))
        self.assertEqual(parse_threshold("<= 1.5"), ("<=", 1.5))
        self.assertEqual(parse_threshold("== 1"), ("==", 1.0))
        self.assertEqual(parse_threshold("!= 0"), ("!=", 0.0))
        self.assertEqual(parse_threshold("80"), (">=", 80.0))

    def test_empty_and_nonsense(self):
        for text in ("", "   ", None, "abc", "> x", "nan", "inf"):
            self.assertIsNone(parse_threshold(text), text)


class ActionModelTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()

    def test_round_trip_and_stable_shape(self):
        project = DesignerProject(name="rt")
        project.pages[0].widgets = [
            widget("ShButton", "start", {"text": "Start"},
                   actions={"clicked": DesignerAction("pulse", "do.start", ms=500)}),
            widget("ShToggle", "pump", bindings={"checked": DesignerBinding("do.pump")},
                   actions={"toggled": DesignerAction("write", "do.pump")}),
            widget("ShButton", "nav", actions={"clicked": DesignerAction("navigate", page="main")}),
            widget("Text", "plain"),
        ]
        data = project.to_dict()
        widgets = data["pages"][0]["widgets"]
        self.assertEqual(widgets[0]["actions"], {"clicked": {"kind": "pulse", "tag": "do.start", "ms": 500}})
        self.assertEqual(widgets[1]["actions"], {"toggled": {"kind": "write", "tag": "do.pump"}})
        self.assertEqual(widgets[2]["actions"], {"clicked": {"kind": "navigate", "page": "main"}})
        # A widget with no actions keeps the pre-actions file shape.
        self.assertNotIn("actions", widgets[3])
        again = DesignerProject.from_dict(json.loads(json.dumps(data)))
        self.assertEqual(again.to_dict(), data)
        self.assertEqual(again.pages[0].widgets[0].actions["clicked"].ms, 500)

    def test_legacy_file_without_actions_loads(self):
        project = DesignerProject.from_dict({"version": 1, "pages": [{"widgets": [
            {"type": "ShButton", "id": "b", "geometry": geometry()}]}]})
        self.assertEqual(project.pages[0].widgets[0].actions, {})

    def test_required_tags_include_action_tags_but_not_wildcard(self):
        project = DesignerProject()
        project.pages[0].widgets = [
            widget("ShButton", "b", actions={"clicked": DesignerAction("write", "do.relay1", value=True)}),
            widget("ShGauge", "g", bindings={"value": DesignerBinding("ai.pot")}),
            widget("ShAlarmTable", "a", bindings={"alarms": DesignerBinding("*")}),
        ]
        self.assertEqual(project.required_tags(), ["ai.pot", "do.relay1"])

    def test_alarms_from_thresholds(self):
        project = DesignerProject()
        project.pages[0].widgets = [
            widget("ShGauge", "oil", {"label": "Oil"},
                   {"value": DesignerBinding("ai.oil", unit="psi", warning="> 70", critical="90")}),
            widget("ShValueTile", "v", {"title": "Volts"}, {"value": DesignerBinding("ai.pot", critical="> 3")}),
            widget("ShValueTile", "dup", {"title": "Again"}, {"value": DesignerBinding("ai.pot", warning="> 1")}),
            widget("ShValueTile", "none", {}, {"value": DesignerBinding("ai.quiet")}),
        ]
        self.assertEqual(project.alarms(), [
            {"tag": "ai.oil", "label": "Oil", "unit": "psi",
             "warning": {"op": ">", "value": 70.0}, "critical": {"op": ">=", "value": 90.0}},
            {"tag": "ai.pot", "label": "Volts", "critical": {"op": ">", "value": 3.0}},
        ])

    def test_validation_names_bad_actions(self):
        project = DesignerProject()
        project.pages[0].widgets = [
            widget("Text", "t", actions={"clicked": DesignerAction("write", "do.x")}),
            widget("ShButton", "b1", actions={"clicked": DesignerAction("write", "NotATag")}),
            widget("ShToggle", "b5", actions={"toggled": DesignerAction("write", "do.pumpA.run")}),
            widget("ShButton", "b2", actions={"clicked": DesignerAction("pulse", "do.x", ms=0)}),
            widget("ShButton", "b3", actions={"clicked": DesignerAction("navigate", page="nowhere")}),
            widget("ShButton", "b4", actions={"clicked": DesignerAction("explode", "do.x")}),
            widget("ShGauge", "g", bindings={"value": DesignerBinding("ai.x", warning="hot")}),
            widget("ShAlarmTable", "a", actions={"alarmActivated": DesignerAction("write")}),
        ]
        messages = [str(issue) for issue in project.validate(self.registry)]
        self.assertTrue(any("Text has no action signal 'clicked'" in m for m in messages), messages)
        self.assertTrue(any("b1" in m and "not a lowercase dotted tag" in m for m in messages), messages)
        # Dotted but capitalised: say so, and what it should be.
        self.assertTrue(any("b5" in m and "must be lowercase ('do.pumpa.run')" in m for m in messages), messages)
        self.assertTrue(any("b2" in m and "pulse ms" in m for m in messages), messages)
        self.assertTrue(any("b3" in m and "'nowhere'" in m for m in messages), messages)
        self.assertTrue(any("b4" in m and "unknown action kind" in m for m in messages), messages)
        self.assertTrue(any(".g." in m and "warning threshold 'hot'" in m for m in messages), messages)
        self.assertFalse(any(".a." in m for m in messages), messages)

    def test_capitalised_tags_in_a_saved_design_load_lowercase(self):
        """A design AI Design saved with "do.pumpA.run" failed validation on
        every open; the daemon would reject the capitals anyway."""
        action = DesignerAction.from_data({"kind": "write", "tag": "do.pumpA.run", "value": True})
        binding = DesignerBinding.from_data({"tag": "pumpA.pressure", "unit": "bar"})
        self.assertEqual(action.tag, "do.pumpa.run")
        self.assertEqual(binding.tag, "pumpa.pressure")
        # Only case is repaired; a tag that is wrong another way stays as
        # written, so validation can name it.
        self.assertEqual(DesignerAction.from_data({"tag": "NotATag"}).tag, "NotATag")
        self.assertEqual(DesignerBinding.from_data("*").tag, "*")

    def test_registry_declares_signals_for_controls(self):
        for kind, signals, state in (("ShButton", ("clicked",), ""), ("ShToggle", ("toggled",), "checked"),
                                     ("ShCheckbox", ("checkedChanged",), "checked"),
                                     ("ShSlider", ("valueChanged",), "value"),
                                     ("ShSelect", ("activated",), "currentIndex"),
                                     ("ShAlarmTable", ("alarmActivated",), "")):
            definition = self.registry.get(kind)
            self.assertEqual(definition.action_signals, signals, kind)
            self.assertEqual(definition.state_property, state, kind)
        self.assertEqual(self.registry.get("ShGauge").action_signals, ())


class ActionGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.generator = QmlGenerator(default_registry())

    def page(self, *widgets, pages=()):
        project = DesignerProject(name="gen")
        project.pages[0].widgets = list(widgets)
        project.pages.extend(pages)
        return project, self.generator.generate(project)

    def test_write_pulse_and_explicit_value(self):
        _, out = self.page(
            widget("ShButton", "start", actions={"clicked": DesignerAction("pulse", "do.start", ms=500)}),
            widget("ShButton", "stop", actions={"clicked": DesignerAction("write", "do.run", value=False)}),
            widget("ShButton", "mode", actions={"clicked": DesignerAction("write", "hmi.mode", value="auto")}),
        )
        qml = out["Main.qml"]
        self.assertIn('onClicked: Bus.pulse("do.start", 500)', qml)
        self.assertIn('onClicked: Bus.write("do.run", false)', qml)
        self.assertIn('onClicked: Bus.write("hmi.mode", "auto")', qml)
        self.assertNotIn("navigateRequested", qml, "single page: no host, no signal")
        self.assertNotIn("App.qml", out)

    def test_two_way_toggle_uses_binding_element(self):
        _, out = self.page(widget("ShToggle", "pump", bindings={"checked": DesignerBinding("do.pump")},
                                  actions={"toggled": DesignerAction("write", "do.pump")}))
        qml = out["Main.qml"]
        self.assertIn('Binding on checked { value: Bus.value("do.pump", false) }', qml)
        self.assertIn('onToggled: Bus.write("do.pump", checked)', qml)
        self.assertNotIn('checked: Bus.value', qml)

    def test_read_only_toggle_keeps_plain_binding(self):
        _, out = self.page(widget("ShToggle", "pump", bindings={"checked": DesignerBinding("do.pump")}))
        self.assertIn('checked: Bus.value("do.pump", 0)', out["Main.qml"])

    def test_state_controls_send_their_own_state(self):
        _, out = self.page(
            widget("ShSlider", "sp", actions={"valueChanged": DesignerAction("write", "mb.setpoint")}),
            widget("ShCheckbox", "en", actions={"checkedChanged": DesignerAction("write", "do.enable")}),
            widget("ShSelect", "mode", bindings={"currentIndex": DesignerBinding("hmi.mode")},
                   actions={"activated": DesignerAction("write", "hmi.mode")}),
        )
        qml = out["Main.qml"]
        self.assertIn('onValueChanged: Bus.write("mb.setpoint", value)', qml)
        self.assertIn('onCheckedChanged: Bus.write("do.enable", checked)', qml)
        self.assertIn('onActivated: Bus.write("hmi.mode", index)', qml)
        self.assertIn('Binding on currentIndex { value: Bus.value("hmi.mode", 0) }', qml)

    def test_thresholds_drive_state_and_marks(self):
        _, out = self.page(
            widget("ShValueTile", "v", {"title": "Volts", "state": "idle"},
                   {"value": DesignerBinding("ai.pot", format="{:.2f}", multiplier=11, unit="V",
                                             warning="> 2.5", critical="> 3")}),
            widget("ShGauge", "g", bindings={"value": DesignerBinding("ai.oil", unit="psi", warning="> 70", critical="90")}),
            widget("ShAnnunciator", "lf", {"text": "LOW FUEL"},
                   {"lit": DesignerBinding("ai.fuel", critical="< 15")}),
            widget("ShNumDisplay", "nd", bindings={"value": DesignerBinding("ai.t", warning="< 5", critical="> 90")}),
        )
        qml = out["Main.qml"]
        self.assertIn('state: ((Bus.value("ai.pot", 0) * 11) > 3.0) ? "fault" : '
                      '((Bus.value("ai.pot", 0) * 11) > 2.5) ? "warn" : "ok"', qml)
        self.assertIn('value: "{:.2f}".arg((Bus.value("ai.pot", 0) * 11))', qml)
        self.assertNotIn('state: "idle"', qml, "the threshold expression replaces the inspector value")
        self.assertIn('unit: "V"', qml)
        self.assertIn("thresholdWarning: 70.0", qml)
        self.assertIn("thresholdFault: 90.0", qml)
        self.assertIn('unit: "psi"', qml)
        self.assertIn('severity: (Bus.value("ai.fuel", 0) < 15.0) ? "warning" : "advisory"', qml)
        self.assertIn('lit: (Bus.value("ai.fuel", 0) < 15.0)', qml)
        self.assertEqual(qml.count("\n        lit:"), 1, "the raw lit binding must not be emitted twice")
        self.assertIn("warningLow: 5.0", qml)
        self.assertIn("faultHigh: 90.0", qml)

    def test_series_bindings_use_runtime_history_and_alarms(self):
        _, out = self.page(
            widget("ShTrendChart", "t", {"maxPoints": 50}, {"data": DesignerBinding("ai.pot")}),
            widget("ShAlarmTable", "a", bindings={"alarms": DesignerBinding("*")},
                   actions={"alarmActivated": DesignerAction("write")}),
        )
        qml = out["Main.qml"]
        self.assertIn('data: (Bus.historyVersion, Bus.history("ai.pot", 50))', qml)
        self.assertIn("alarms: Bus.activeAlarms", qml)
        self.assertIn("onAlarmActivated: Bus.acknowledge(alarm.tag)", qml)
        self.assertNotIn('Bus.value("*"', qml)

    def test_multi_page_host_and_navigation(self):
        settings = DesignerPage("settings", "Settings", [
            widget("ShButton", "back", actions={"clicked": DesignerAction("navigate", page="main")})])
        _, out = self.page(widget("ShButton", "go", actions={"clicked": DesignerAction("navigate", page="settings")}),
                           pages=[settings])
        self.assertEqual(list(out), ["App.qml", "Main.qml", "Settings.qml"])
        self.assertIn('onClicked: root.navigateRequested("settings")', out["Main.qml"])
        self.assertIn('onClicked: root.navigateRequested("main")', out["Settings.qml"])
        for name in ("Main.qml", "Settings.qml"):
            self.assertIn("signal navigateRequested(string pageId)", out[name])
        host = out["App.qml"]
        self.assertIn('readonly property var pages: ({"main": "Main.qml", "settings": "Settings.qml"})', host)
        self.assertIn('property string currentPage: "main"', host)
        self.assertIn("onLoaded: item.navigateRequested.connect(app.navigate)", host)

    def test_invalid_action_refuses_generation(self):
        project = DesignerProject()
        project.pages[0].widgets = [widget("ShButton", "b", actions={"clicked": DesignerAction("write", "bad tag")})]
        with self.assertRaises(QmlGenerationError):
            self.generator.generate(project)


class GeneratedQmlRuntimeTests(unittest.TestCase):
    """Load generated pages into a QML engine and operate them."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def load(self, project):
        generator = QmlGenerator(default_registry())
        root_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: None)
        paths = generator.write(project, os.path.join(root_dir, "generated"), root_dir)
        engine = QQmlEngine()
        engine.addImportPath(str(REPO_ROOT / "ui" / "qml"))
        bus = StubBus()
        engine.rootContext().setContextProperty("Bus", bus)
        engine.rootContext().setContextProperty("Tags", QObject())
        component = QQmlComponent(engine, paths[0])
        item = component.create()
        errors = [e.toString() for e in component.errors()]
        self.assertEqual(errors, [], errors)
        self.assertIsNotNone(item)
        # Keep the engine alive for the test's duration.
        self._keep = (engine, bus, component, item)
        return item, bus

    def test_clicks_reach_the_bus(self):
        project = DesignerProject(name="rt")
        project.pages[0].widgets = [
            widget("ShButton", "start", {"text": "Start"},
                   actions={"clicked": DesignerAction("pulse", "do.start", ms=500)}),
            widget("ShButton", "stop", {"text": "Stop"},
                   actions={"clicked": DesignerAction("write", "do.run", value=False)}),
            widget("ShToggle", "pump", bindings={"checked": DesignerBinding("do.pump")},
                   actions={"toggled": DesignerAction("write", "do.pump")}),
            widget("ShTrendChart", "t", {"maxPoints": 2}, {"data": DesignerBinding("ai.pot")}),
            widget("ShAlarmTable", "a", bindings={"alarms": DesignerBinding("*")},
                   actions={"alarmActivated": DesignerAction("write")}),
            widget("ShValueTile", "v", {"title": "Volts"},
                   {"value": DesignerBinding("ai.pot", warning="> 2.5", critical="> 3")}),
        ]
        item, bus = self.load(project)
        start, stop, pump = by_id(item, "start"), by_id(item, "stop"), by_id(item, "pump")
        start.clicked.emit()
        stop.clicked.emit()
        self.assertEqual(bus.calls, [("pulse", "do.start", 500), ("write", "do.run", False)])
        bus.calls.clear()
        # The toggle writes its own state, and the tag value re-applies
        # through the Binding element afterwards (two-way).
        self.assertFalse(pump.property("checked"))
        pump.toggle()
        self.assertEqual(bus.calls, [("write", "do.pump", True)])
        self.assertTrue(pump.property("checked"))
        chart = by_id(item, "t")
        self.assertEqual(list(chart.property("data")), [1.0, 2.0])
        table = by_id(item, "a")
        table.alarmActivated.emit({"tag": "ai.pot"})
        self.assertEqual(bus.calls[-1], ("acknowledge", "ai.pot"))
        tile = by_id(item, "v")
        self.assertEqual(tile.property("state"), "ok")

    def test_navigation_swaps_pages_in_the_host(self):
        project = DesignerProject(name="nav")
        project.pages[0].widgets = [widget("ShButton", "go", {"text": "Settings"},
                                           actions={"clicked": DesignerAction("navigate", page="settings")})]
        project.pages.append(DesignerPage("settings", "Settings", [
            widget("ShButton", "back", {"text": "Back"}, actions={"clicked": DesignerAction("navigate", page="main")})]))
        host, _ = self.load(project)
        self.assertEqual(host.property("currentPage"), "main")
        loader = by_id(host, "pageLoader")
        page = loader.property("item")
        self.assertIsNotNone(page)
        by_id(page, "go").clicked.emit()
        self.assertEqual(host.property("currentPage"), "settings")
        # The loader swaps synchronously for a local file.
        page = loader.property("item")
        self.assertIsNotNone(by_id(page, "back"))
        by_id(page, "back").clicked.emit()
        self.assertEqual(host.property("currentPage"), "main")


class WorkspaceManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_writes_alarms_and_action_tags_to_manifest(self):
        from designer.ui import DesignerWorkspace
        from schema.manifest import validate_bundle
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "acts")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "acts", "version": "1.0.0"})
            workspace.project.pages[0].widgets = [
                widget("ShButton", "start", {"text": "Start"},
                       actions={"clicked": DesignerAction("write", "do.run", value=True)}),
                widget("ShGauge", "oil", {"label": "Oil"},
                       {"value": DesignerBinding("ai.oil", unit="psi", warning="> 70", critical="> 90")}),
            ]
            workspace._load_page()
            self.assertTrue(workspace.generate())
            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["tags_required"], ["ai.oil", "do.run"])
            self.assertEqual(manifest["alarms"], [{"tag": "ai.oil", "label": "Oil", "unit": "psi",
                                                   "warning": {"op": ">", "value": 70.0},
                                                   "critical": {"op": ">", "value": 90.0}}])
            valid, issues = validate_bundle(bundle)
            self.assertTrue(valid, issues)
            # Removing the thresholds removes the key again.
            workspace.project.pages[0].widgets[1].bindings["value"] = DesignerBinding("ai.oil")
            self.assertTrue(workspace.generate())
            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                self.assertNotIn("alarms", json.load(handle))

    def test_action_editor_round_trips_through_undo(self):
        from designer.ui import DesignerWorkspace
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        workspace.add_widget("ShButton")
        button = workspace.project.pages[0].widgets[0]
        workspace._load_page(select=[button.id])
        self.assertEqual(workspace.actions.signal.currentText(), "clicked")
        workspace.actions.kind.setCurrentText("pulse")
        workspace.actions.tag.setCurrentText("do.start")
        workspace.actions.ms.setValue(300)
        workspace.actions._apply()
        self.assertEqual(button.actions["clicked"], DesignerAction("pulse", "do.start", ms=300))
        workspace.undo_stack.undo()
        self.assertEqual(button.actions, {})
        workspace.undo_stack.redo()
        self.assertEqual(button.actions["clicked"].ms, 300)
        workspace.actions._remove()
        self.assertEqual(button.actions, {})


class AiActionsTests(unittest.TestCase):
    def test_prompt_teaches_actions_and_thresholds(self):
        prompt = build_system_prompt(default_registry())
        for needle in ('"actions"', '"kind": "write"', '"kind": "pulse"', '"kind": "navigate"',
                       '"warning": "> 2.5"', "ShToggle toggled", "ShButton clicked"):
            self.assertIn(needle, prompt)

    def test_model_output_keeps_actions(self):
        generator = AIDesignGenerator(default_registry())
        widgets = generator._convert_widgets([
            {"type": "Button", "id": "startBtn", "geometry": geometry(),
             "properties": {"text": "Start"},
             "actions": {"clicked": {"kind": "pulse", "tag": "do.start", "ms": 300},
                         "bogus": "not a dict or tag"}},
            {"type": "ShToggle", "id": "pump", "geometry": geometry(),
             "bindings": {"checked": {"tag": "do.pump"}},
             "actions": {"toggled": {"kind": "write", "tag": "do.pump"}, "broken": 42}},
        ])
        self.assertEqual(widgets[0].actions["clicked"], DesignerAction("pulse", "do.start", ms=300))
        # A signal the widget does not have can never fire; kept, it made
        # validation refuse the whole design at deploy.
        self.assertNotIn("bogus", widgets[0].actions)
        self.assertEqual(widgets[1].actions, {"toggled": DesignerAction("write", "do.pump")})


if __name__ == "__main__":
    unittest.main()
