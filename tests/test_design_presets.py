"""Tests for the design presets mechanism (W5).

Verifies template loading, validation, preset matching, prompt sections,
the system-prompt integration, and the CLI.
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

from designer.model.project import DesignerProject  # noqa: E402
from designer.generators import QmlGenerator  # noqa: E402
from designer.palette.widget_registry import default_registry  # noqa: E402
from tools.hmi_deployer.ai_generator import build_system_prompt  # noqa: E402
from tools.hmi_deployer.design_presets import (  # noqa: E402
    DesignPreset,
    get_preset,
    load_template,
    match_preset,
    prompt_section,
    presets,
)


class TestTemplatesLoadAndValidate(unittest.TestCase):
    """Both templates load and validate with zero issues."""

    @classmethod
    def setUpClass(cls):
        cls.registry = default_registry()

    def test_cluster_loads(self):
        project = DesignerProject.load(
            "designer/templates/automotive_cluster.edsui"
        )
        self.assertIsNotNone(project)
        self.assertEqual(project.screen.width, 1280)
        self.assertEqual(project.screen.height, 800)
        self.assertEqual(project.screen.background, "#0b0f16")
        self.assertEqual(project.screen.theme, "dark")

    def test_cluster_validates(self):
        project = DesignerProject.load(
            "designer/templates/automotive_cluster.edsui"
        )
        issues = project.validate(self.registry)
        self.assertEqual(len(issues), 0, [str(i) for i in issues])

    def test_ev_loads(self):
        project = DesignerProject.load(
            "designer/templates/ev_infotainment.edsui"
        )
        self.assertIsNotNone(project)
        self.assertEqual(project.screen.width, 1280)
        self.assertEqual(project.screen.height, 800)

    def test_ev_validates(self):
        project = DesignerProject.load(
            "designer/templates/ev_infotainment.edsui"
        )
        issues = project.validate(self.registry)
        self.assertEqual(len(issues), 0, [str(i) for i in issues])

    def test_all_ids_valid_qml(self):
        """Every widget id must match the QML identifier regex."""
        import re
        id_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        for path in (
            "designer/templates/automotive_cluster.edsui",
            "designer/templates/ev_infotainment.edsui",
        ):
            project = DesignerProject.load(path)
            for widget in project.all_widgets():
                self.assertTrue(
                    id_re.fullmatch(widget.id),
                    f"{path}: id {widget.id!r} is not a valid QML id",
                )

    def test_all_ids_unique(self):
        """Widget ids must be unique within each template."""
        for path in (
            "designer/templates/automotive_cluster.edsui",
            "designer/templates/ev_infotainment.edsui",
        ):
            project = DesignerProject.load(path)
            ids = [w.id for w in project.all_widgets()]
            self.assertEqual(len(ids), len(set(ids)), f"duplicate ids in {path}")


class TestQmlGeneration(unittest.TestCase):
    """Templates generate QML and the cluster output contains expected ids."""

    @classmethod
    def setUpClass(cls):
        cls.registry = default_registry()

    def test_cluster_generates_qml(self):
        project = load_template(get_preset("automotive-cluster"))
        output = QmlGenerator(self.registry).generate(project)
        self.assertIn("Main.qml", output)
        content = "\n".join(output.values())
        self.assertIn("ShClusterGauge", content)
        self.assertIn("Bus.value", content)
        self.assertIn("mb.rpm", content)

    def test_cluster_has_tacho(self):
        project = load_template(get_preset("automotive-cluster"))
        page = project.pages[0]
        tacho = next((w for w in page.widgets if w.id == "tacho"), None)
        self.assertIsNotNone(tacho)
        self.assertEqual(tacho.type, "ShClusterGauge")

    def test_cluster_has_drive_mode(self):
        project = load_template(get_preset("automotive-cluster"))
        page = project.pages[0]
        dm = next((w for w in page.widgets if w.id == "driveMode"), None)
        self.assertIsNotNone(dm)
        self.assertEqual(dm.type, "ShDriveMode")

    def test_cluster_has_fuel_binding(self):
        """The generated QML must contain Bus.value with the fuel tag."""
        project = load_template(get_preset("automotive-cluster"))
        output = QmlGenerator(self.registry).generate(project)
        content = "\n".join(output.values())
        self.assertIn('Bus.value("mb.fuel_pct"', content)

    def test_ev_generates_qml(self):
        project = load_template(get_preset("ev-infotainment"))
        output = QmlGenerator(self.registry).generate(project)
        self.assertIn("Main.qml", output)


class TestPresetMatching(unittest.TestCase):
    """Keyword-based preset matching from brief text."""

    def test_cluster_matches_car_dashboard(self):
        preset = match_preset("Car dashboard with speedometer")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "automotive-cluster")

    def test_cluster_matches_automotive(self):
        preset = match_preset("automotive cluster display")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "automotive-cluster")

    def test_cluster_matches_instrument_cluster(self):
        preset = match_preset("instrument cluster with fuel gauge and rpm")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "automotive-cluster")

    def test_ev_matches_battery_soc(self):
        preset = match_preset("EV battery SOC and tyre pressure")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "ev-infotainment")

    def test_ev_matches_infotainment(self):
        preset = match_preset("EV infotainment with charging stats")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "ev-infotainment")

    def test_ev_matches_tpms(self):
        preset = match_preset("tpms tyre pressure monitoring carplay")
        self.assertIsNotNone(preset)
        self.assertEqual(preset.id, "ev-infotainment")

    def test_no_match_pump_control(self):
        preset = match_preset("pump control screen")
        self.assertIsNone(preset)

    def test_no_match_empty(self):
        preset = match_preset("")
        self.assertIsNone(preset)

    def test_no_match_unrelated(self):
        preset = match_preset("alarm management interface")
        self.assertIsNone(preset)


class TestPromptSection(unittest.TestCase):
    """prompt_section output: length, format, JSON validity."""

    def test_cluster_prompt_under_limit(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        self.assertLess(len(section), 6000, f"prompt section too long: {len(section)}")

    def test_ev_prompt_under_limit(self):
        preset = get_preset("ev-infotainment")
        section = prompt_section(preset, 1280, 800)
        self.assertLess(len(section), 6000, f"prompt section too long: {len(section)}")

    def test_cluster_contains_heading(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        self.assertIn("Design preset: Automotive cluster", section)

    def test_cluster_contains_exemplar(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        self.assertIn("Exemplar (a section of a finished design at 1280x800):", section)

    def test_cluster_has_one_json_fence(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        fences = [i for i, line in enumerate(section.split("\n")) if "```json" in line]
        self.assertEqual(len(fences), 1)

    def test_cluster_json_parses(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        # Extract the JSON between the fence markers.
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        self.assertIsInstance(data, dict)

    def test_cluster_json_has_widgets(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        widgets = data["pages"][0]["widgets"]
        self.assertIsInstance(widgets, list)
        self.assertGreater(len(widgets), 0)

    def test_cluster_widgets_under_eight(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        widgets = data["pages"][0]["widgets"]
        self.assertLessEqual(len(widgets), 8)

    def test_cluster_geometries_inside_screen(self):
        preset = get_preset("automotive-cluster")
        section = prompt_section(preset, 1280, 800)
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        widgets = data["pages"][0]["widgets"]
        for w in widgets:
            geo = w["geometry"]
            self.assertGreaterEqual(geo.get("x", 0), 0)
            self.assertGreaterEqual(geo.get("y", 0), 0)
            self.assertLessEqual(
                geo.get("x", 0) + geo.get("width", 0), 1280
            )
            self.assertLessEqual(
                geo.get("y", 0) + geo.get("height", 0), 800
            )

    def test_ev_prompt_under_limit(self):
        preset = get_preset("ev-infotainment")
        section = prompt_section(preset, 1280, 800)
        self.assertLess(len(section), 6000)

    def test_ev_json_parses(self):
        preset = get_preset("ev-infotainment")
        section = prompt_section(preset, 1280, 800)
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        self.assertIsInstance(data, dict)

    def test_ev_geometries_inside_screen(self):
        preset = get_preset("ev-infotainment")
        section = prompt_section(preset, 1280, 800)
        start = section.index("```json\n") + 8
        end = section.index("\n```", start)
        data = json.loads(section[start:end])
        widgets = data["pages"][0]["widgets"]
        for w in widgets:
            geo = w["geometry"]
            self.assertGreaterEqual(geo.get("x", 0), 0)
            self.assertGreaterEqual(geo.get("y", 0), 0)
            self.assertLessEqual(geo.get("x", 0) + geo.get("width", 0), 1280)
            self.assertLessEqual(geo.get("y", 0) + geo.get("height", 0), 800)


class TestBuildSystemPrompt(unittest.TestCase):
    """build_system_prompt integration with presets."""

    def test_no_brief_no_preset_append(self):
        """Without brief, output must not contain 'Design preset:'."""
        prompt = build_system_prompt(default_registry(), 1024, 600)
        self.assertNotIn("Design preset:", prompt)

    def test_with_brief_includes_preset(self):
        """With brief, output must contain 'Design preset:' for a match."""
        prompt = build_system_prompt(default_registry(), 1024, 600, brief="vehicle cluster")
        self.assertIn("Design preset:", prompt)

    def test_no_brief_unchanged_screen_size(self):
        """Without brief, screen size is still reflected."""
        prompt = build_system_prompt(default_registry(), 1024, 600)
        self.assertIn("1024x600", prompt)

    def test_ev_brief_includes_preset(self):
        prompt = build_system_prompt(
            default_registry(), 1024, 600, brief="EV battery SOC and tyre pressure"
        )
        self.assertIn("Design preset:", prompt)


class TestCLI(unittest.TestCase):
    """The CLI --list and --write commands."""

    def test_cli_list(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "tools.hmi_deployer.design_presets", "--list"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(result.returncode, 0)
        lines = [l for l in result.stdout.strip().split("\n") if l]
        self.assertEqual(len(lines), 2)
        ids_seen = set()
        for line in lines:
            parts = line.split("\t")
            self.assertGreaterEqual(len(parts), 3, f"Not enough columns: {line!r}")
            ids_seen.add(parts[0])
        self.assertIn("automotive-cluster", ids_seen)
        self.assertIn("ev-infotainment", ids_seen)

    def test_cli_write_cluster(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable, "-m", "tools.hmi_deployer.design_presets",
                    "--write", "automotive-cluster", tmpdir,
                ],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            files = os.listdir(tmpdir)
            self.assertIn("Main.qml", files)
            app_qml = os.path.join(tmpdir, "Main.qml")
            with open(app_qml, "r") as f:
                content = f.read()
            self.assertIn("ShClusterGauge", content)


class TestPresetData(unittest.TestCase):
    """Basic data integrity for preset definitions."""

    def test_presets_returns_two(self):
        all_presets = presets()
        self.assertEqual(len(all_presets), 2)

    def test_get_preset_valid_id(self):
        p = get_preset("automotive-cluster")
        self.assertIsInstance(p, DesignPreset)
        self.assertEqual(p.id, "automotive-cluster")

    def test_get_preset_ev(self):
        p = get_preset("ev-infotainment")
        self.assertIsInstance(p, DesignPreset)
        self.assertEqual(p.id, "ev-infotainment")

    def test_get_preset_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_preset("nonexistent")

    def test_style_under_1200_chars(self):
        for p in presets():
            self.assertLess(len(p.style), 1200, f"{p.id} style too long: {len(p.style)}")

    def test_keywords_are_lowercase(self):
        for p in presets():
            for kw in p.keywords:
                self.assertEqual(kw, kw.lower(), f"{kw!r} in {p.id} is not lowercase")

    def test_all_preset_ids_unique(self):
        ids = [p.id for p in presets()]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()