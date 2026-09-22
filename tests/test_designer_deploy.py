"""Designer Deploy must hand a complete, installable bundle to the Studio."""
import json
import os
import tarfile
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from designer.ui import DesignerWorkspace
from designer.ui import designer_workspace
from schema.manifest import validate_bundle
from tools.hmi_deployer.deployer import package_bundle
from tools.hmi_deployer.mainwindow import MainWindow


class DesignerDeployTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_deploy_generates_valid_package_and_emits_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "designer-app")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "designer-app", "version": "1.2.3"})
            for definition in workspace.registry.definitions():
                workspace.add_widget(definition.type)

            requested = []
            workspace.deployRequested.connect(requested.append)
            workspace.deploy()

            self.assertEqual(requested, [os.path.abspath(bundle)])
            valid, issues = validate_bundle(bundle)
            self.assertTrue(valid, issues)
            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["name"], "designer-app")
            self.assertEqual(workspace.project.name, "designer-app")
            # The panel runs the design file (hmi-ui); the generated QML stays
            # on the desktop for the Studio's own preview.
            self.assertEqual(manifest["runtime"], "edsui")
            self.assertEqual(manifest["entry"], "project.edsui")
            self.assertTrue(os.path.isfile(os.path.join(bundle, *manifest["entry"].split("/"))))
            self.assertTrue(os.path.isfile(os.path.join(bundle, *manifest["preview"].split("/"))))

            output = os.path.join(root, "package")
            os.makedirs(output)
            archive, checksum = package_bundle(bundle, output)
            self.assertTrue(os.path.isfile(checksum))
            with tarfile.open(archive, "r:gz") as packaged:
                names = set(packaged.getnames())
            self.assertIn("manifest.json", names)
            self.assertIn("project.edsui", names)
            # No QML travels to a Qt-free panel.
            self.assertNotIn(manifest["preview"], names)
            self.assertFalse([n for n in names if n.startswith("generated/")], names)

    def test_project_name_is_used_for_design_deployment(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "old-bundle-folder")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "original-name", "version": "1.0.0"})
            workspace.project.name = "operator-panel"

            workspace.deploy()

            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
            self.assertEqual(manifest["name"], "operator-panel")
            with open(os.path.join(bundle, "project.edsui"), encoding="utf-8") as handle:
                saved_project = json.load(handle)
            self.assertEqual(saved_project["name"], "operator-panel")

    def test_project_name_editor_controls_deployment_name(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "opened-bundle")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "opened-name", "version": "1.0.0"})
            workspace.project_name.setText("new-design")
            workspace._project_name_edited()

            workspace.deploy()

            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["name"], "new-design")

    def test_visible_deploy_confirms_name_before_generating(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = os.path.join(root, "opened-bundle")
            os.makedirs(bundle)
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.set_bundle(bundle, {"name": "opened-name", "version": "1.0.0"})
            workspace.isVisible = lambda: True
            original = designer_workspace.QInputDialog.getText
            designer_workspace.QInputDialog.getText = staticmethod(
                lambda *args, **kwargs: ("confirmed-new-name", True))
            try:
                workspace.deploy()
            finally:
                designer_workspace.QInputDialog.getText = original

            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["name"], "confirmed-new-name")

    def test_preview_provisions_bundle_for_ai_design_without_open_bundle(self):
        """AI Design -> Designer -> Preview must not demand an opened bundle."""
        from designer.model import DesignerPage, DesignerProject, DesignerWidget
        with tempfile.TemporaryDirectory() as root:
            workspace = DesignerWorkspace()
            self.addCleanup(workspace.close)
            workspace.projects_root = os.path.join(root, "projects")
            self.assertEqual(workspace.bundle_dir, "")
            handed_over = DesignerProject(
                name="AI Design (partial)",
                pages=[DesignerPage(id="main", name="Main", widgets=[
                    DesignerWidget("ShButton", "button1",
                                   {"x": 10, "y": 10, "width": 120, "height": 40},
                                   {"text": "Start"})])])
            workspace.load_project(handed_over)
            self.assertEqual(workspace.project.name, "ai-design-partial")

            requested = []
            workspace.previewRequested.connect(requested.append)
            self.assertTrue(workspace.preview())

            bundle = os.path.join(workspace.projects_root, "ai-design-partial")
            self.assertEqual(requested, [os.path.abspath(bundle)])
            self.assertTrue(os.path.isfile(os.path.join(bundle, "project.edsui")))
            valid, issues = validate_bundle(bundle)
            self.assertTrue(valid, issues)
            with open(os.path.join(bundle, "manifest.json"), encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["name"], "ai-design-partial")

            # A second, unrelated design must not land on top of the first.
            other = DesignerWorkspace()
            self.addCleanup(other.close)
            other.projects_root = workspace.projects_root
            other.load_project(DesignerProject(name="AI Design (partial)"))
            self.assertTrue(other.ensure_bundle())
            self.assertEqual(os.path.basename(other.bundle_dir), "ai-design-partial-2")

    def test_studio_handler_loads_then_starts_existing_deploy_pipeline(self):
        calls = []

        class _Button:
            def isEnabled(self):
                return True

        class _Studio:
            btn_deploy = _Button()

            def load_bundle(self, path):
                calls.append(("load", path))

            def on_deploy(self):
                calls.append(("deploy",))

        MainWindow._deploy_designed_bundle(_Studio(), "C:/designer-app")
        self.assertEqual(calls, [("load", "C:/designer-app"), ("deploy",)])


if __name__ == "__main__":
    unittest.main()
