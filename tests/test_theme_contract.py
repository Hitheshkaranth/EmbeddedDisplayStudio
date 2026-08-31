"""A design's colour mode must reach the panel, because the app cannot set it.

Shell.qml assigns Theme.mode from its own Component.onCompleted, which Qt runs
*after* the Loader has completed the app. Anything the generated QML sets is
therefore overwritten a moment later, so the mode has to travel out-of-band --
in the manifest, which the loader reads before it builds the shell.

Before this, the shell's --theme default decided for every bundle, and a design
drawn on a light background came up with dark-mode tokens: near-white glyphs on
a near-white screen.
"""
import json
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Loaded by path: the loader's module is also called "main", and the repo root
# already has a main.py (the Studio entry point) that would win the import.
import importlib.util

_LOADER_PATH = os.path.join(os.path.dirname(__file__), "..", "gui", "hmi_loader", "main.py")
_spec = importlib.util.spec_from_file_location("hmi_loader_main", _LOADER_PATH)
hmi_loader = importlib.util.module_from_spec(_spec)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gui", "hmi_loader"))
_spec.loader.exec_module(hmi_loader)

from PySide6.QtWidgets import QApplication

from designer.model import DesignerProject
from designer.ui import DesignerWorkspace
from schema.manifest import DEFAULT_THEME, THEMES, theme_of, validate_bundle


def _bundle(root, manifest):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    entry = os.path.join(root, manifest["entry"])
    os.makedirs(os.path.dirname(entry) or root, exist_ok=True)
    open(entry, "w", encoding="utf-8").write("import QtQuick 2.15\nItem {}\n")
    return root


class ManifestThemeTests(unittest.TestCase):
    def test_both_modes_are_accepted(self):
        for mode in THEMES:
            with self.subTest(theme=mode), tempfile.TemporaryDirectory() as root:
                bundle = _bundle(os.path.join(root, "app"), {
                    "schema": 1, "name": "app", "version": "1.0.0",
                    "entry": "main.qml", "theme": mode})
                valid, issues = validate_bundle(bundle)
                self.assertTrue(valid, issues)

    def test_an_unknown_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = _bundle(os.path.join(root, "app"), {
                "schema": 1, "name": "app", "version": "1.0.0",
                "entry": "main.qml", "theme": "midnight"})
            valid, issues = validate_bundle(bundle)
            self.assertFalse(valid)
            self.assertTrue(any("theme" in issue for issue in issues), issues)

    def test_theme_is_optional_and_defaults_to_the_device_mode(self):
        self.assertEqual(theme_of({}), DEFAULT_THEME)
        self.assertEqual(theme_of({"theme": "light"}), "light")
        self.assertEqual(theme_of({"theme": "midnight"}), DEFAULT_THEME)


class LoaderThemeTests(unittest.TestCase):
    """The bundle decides; --theme still wins for desktop development."""

    def setUp(self):
        self.resolve = hmi_loader.resolve_theme

    def test_bundle_theme_is_used_when_no_flag_is_passed(self):
        self.assertEqual(self.resolve({"theme": "light"}, None), "light")

    def test_explicit_flag_overrides_the_bundle(self):
        self.assertEqual(self.resolve({"theme": "light"}, "dark"), "dark")

    def test_missing_or_junk_theme_falls_back_to_dark(self):
        self.assertEqual(self.resolve({}, None), "dark")
        self.assertEqual(self.resolve({"theme": "midnight"}, None), "dark")


class DesignerThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_project_file_round_trips_the_mode(self):
        project = DesignerProject()
        project.screen.theme = "light"
        restored = DesignerProject.from_dict(json.loads(json.dumps(project.to_dict())))
        self.assertEqual(restored.screen.theme, "light")

    def test_default_matches_the_device(self):
        self.assertEqual(DesignerProject().screen.theme, DEFAULT_THEME)

    def test_deploy_writes_the_designed_mode_into_the_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "themed-app")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "themed-app", "version": "1.0.0"})
            workspace.screen_theme.setCurrentText("light")

            workspace.deploy()

            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["theme"], "light")
            # And the panel would come up in exactly that mode.
            self.assertEqual(hmi_loader.resolve_theme(manifest, None), "light")

    def test_a_bundle_without_a_project_file_inherits_its_manifest_mode(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "existing-app")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "existing-app", "version": "1.0.0",
                                          "theme": "light"})
            self.assertEqual(workspace.project.screen.theme, "light")
            self.assertEqual(workspace.screen_theme.currentText(), "light")


if __name__ == "__main__":
    unittest.main()
