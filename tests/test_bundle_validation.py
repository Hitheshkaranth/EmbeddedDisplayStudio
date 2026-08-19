"""
tests/test_bundle_validation.py
Layer: Test (W11)
Pins CONTRACT 4 behaviour: ensures deployer GUI, deploy CLI, and target installer agree.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tools.hmi_deployer import deployer

class TestBundleValidation(unittest.TestCase):
    """
    Tests that all three CONTRACT 4 implementations agree on bundle validity.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        
        # Determine if we can run shell implementations
        self.has_bash = shutil.which("bash") is not None
        self.has_flock = shutil.which("flock") is not None
        self.has_python3 = shutil.which("python3") is not None
        
        self.missing_shell_tools = []
        if not self.has_bash:
            self.missing_shell_tools.append("bash")
        if not self.has_flock:
            self.missing_shell_tools.append("flock")
        if not self.has_python3:
            self.missing_shell_tools.append("python3")
            
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.deploy_sh = os.path.join(self.repo_root, "deploy", "deploy_to_hmi.sh")
        self.install_sh = os.path.join(self.repo_root, "target", "bin", "hmi-install")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_bundle(self, name: str, manifest_data: dict, create_entry: bool = True) -> str:
        bundle_path = os.path.join(self.temp_dir.name, name)
        os.makedirs(bundle_path)
        
        if manifest_data is not None:
            with open(os.path.join(bundle_path, "manifest.json"), "w", encoding="utf-8") as f:
                if isinstance(manifest_data, dict):
                    json.dump(manifest_data, f)
                else:
                    f.write(manifest_data) # For malformed JSON testing
                    
        if create_entry and isinstance(manifest_data, dict) and "entry" in manifest_data:
            entry_path = os.path.join(bundle_path, manifest_data["entry"])
            os.makedirs(os.path.dirname(entry_path), exist_ok=True)
            with open(entry_path, "w", encoding="utf-8") as f:
                f.write("import QtQuick\n")
                
        return bundle_path

    def _validate_deployer(self, path: str) -> bool:
        ok, _ = deployer.validate_bundle(path)
        return ok

    def _validate_deploy_sh(self, path: str) -> bool:
        """
        Runs the host CLI's client-side validation over `path`.

        Invoked through the script's PUBLIC interface (--dry-run), not by
        sourcing it. Sourcing executes the script's argument parsing, which
        exits with "Flag --host (-H) is required" before any function is
        callable - so a source-based harness reports every bundle as invalid
        and silently turns each rejection assertion into a false pass.

        --dry-run performs validation and packaging but opens no connection,
        so the unreachable host address is never contacted.

        Returns:
            True when the CLI accepts the bundle (exit status 0).
        """
        cmd = ["bash", self.deploy_sh, "--dry-run", "-H", "192.0.2.10", "-b", path]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return proc.returncode == 0

    def _validate_install_sh(self, path: str) -> bool:
        """
        Runs the target installer's validation over `path`.

        Same reasoning as _validate_deploy_sh: hmi-install cannot be sourced
        (it acquires its flock and dispatches a subcommand at load time), so we
        drive the real `install` path against a throwaway HMI_ROOT. The GUI
        restart and health wait are stubbed out via the script's documented
        test hooks, leaving exactly the bundle-validation behaviour under test.

        Returns:
            True when the installer accepts the bundle (exit status 0).
        """
        root = tempfile.mkdtemp()
        upload = os.path.join(root, "tmp", "hmi_upload")
        os.makedirs(upload, exist_ok=True)
        os.makedirs(os.path.join(root, "run", "hmi"), exist_ok=True)
        os.makedirs(os.path.join(root, "opt", "hmi_apps", "releases"), exist_ok=True)

        tgz = os.path.join(upload, "bundle.tar.gz")
        subprocess.run(["tar", "-czf", tgz, "-C", path, "."],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        # The installer verifies a sha256 sidecar before it will touch a bundle.
        subprocess.run(["bash", "-c", f"cd '{upload}' && sha256sum bundle.tar.gz > bundle.tar.gz.sha256"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

        env = dict(os.environ,
                   HMI_ROOT=root,              # relocate every path off the real rootfs
                   HMI_RESTART_CMD="true",     # no systemd on a test host
                   HMI_SKIP_GUI_WAIT="1")      # no GUI to recreate the ready file
        proc = subprocess.run(["bash", self.install_sh, "install", tgz],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        shutil.rmtree(root, ignore_errors=True)
        return proc.returncode == 0

    def _assert_all(self, path: str, should_be_valid: bool):
        # 1. deployer.py (always runs)
        self.assertEqual(self._validate_deployer(path), should_be_valid, "deployer.py failed")
        
        # 2. shell scripts (conditionally skipped)
        if self.missing_shell_tools:
            return
            
        self.assertEqual(self._validate_deploy_sh(path), should_be_valid, "deploy_to_hmi.sh failed")
        self.assertEqual(self._validate_install_sh(path), should_be_valid, "hmi-install failed")

    def test_valid_bundle(self):
        manifest = {
            "schema": 1,
            "name": "line-controller",
            "version": "1.4.0",
            "entry": "main.qml",
            "screen": {"width": 1280, "height": 800},
            "tags_required": ["ai.pot", "di.estop"],
            "qt": ">=6.5"
        }
        b = self._create_bundle("valid", manifest)
        self._assert_all(b, True)
        
        if self.missing_shell_tools:
            self.skipTest(f"Shell implementations skipped, missing: {', '.join(self.missing_shell_tools)}")

    def test_missing_manifest(self):
        b = self._create_bundle("missing_manifest", None)
        self._assert_all(b, False)

    def test_malformed_json(self):
        b = self._create_bundle("malformed_json", "{ schema: 1, ")
        self._assert_all(b, False)

    def test_missing_entry_file(self):
        manifest = {
            "schema": 1, "name": "app", "version": "1.0",
            "entry": "main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("missing_entry", manifest, create_entry=False)
        self._assert_all(b, False)

    def test_entry_containing_parent_dir(self):
        manifest = {
            "schema": 1, "name": "app", "version": "1.0",
            "entry": "../main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("parent_dir", manifest)
        self._assert_all(b, False)

    def test_wrong_schema(self):
        manifest = {
            "schema": 2, "name": "app", "version": "1.0",
            "entry": "main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("wrong_schema", manifest)
        self._assert_all(b, False)

    def test_illegal_name(self):
        manifest = {
            "schema": 1, "name": "Invalid Name!", "version": "1.0",
            "entry": "main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("illegal_name", manifest)
        self._assert_all(b, False)

    def test_dotted_and_underscored_name_accepted_everywhere(self):
        """
        Pins the exact CONTRACT 4 name pattern across all validators.

        "my.app" is legal under ^[a-z0-9][a-z0-9._-]{0,63}$. Three different
        regexes were in use here: the installer forbade dots, the host CLI
        forbade dots and underscores, while the GUI and deployer allowed both.
        The result was a bundle that installed through one tool and was refused
        by another - the worst kind of disagreement, because it only appears
        once someone switches tools.
        """
        manifest = {
            "schema": 1, "name": "my.app_v2-b", "version": "1.0.0",
            "entry": "main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("dotted_name", manifest)
        self._assert_all(b, True)

    def test_uppercase_name_rejected_everywhere(self):
        """
        The other half of the pattern disagreement: the installer used to accept
        uppercase names that every other validator rejected, so a bundle could
        reach the panel that no host-side tool would ever have produced.
        """
        manifest = {
            "schema": 1, "name": "MyApp", "version": "1.0.0",
            "entry": "main.qml", "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5"
        }
        b = self._create_bundle("uppercase_name", manifest)
        self._assert_all(b, False)

if __name__ == "__main__":
    unittest.main()
