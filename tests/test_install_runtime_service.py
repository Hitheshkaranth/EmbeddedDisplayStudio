"""
tests/test_install_runtime_service.py
Layer: Test

Pins how hmi-install picks the GUI systemd unit from the bundle it activates:

  * runtime "edsui"                  -> hmi-ui.service  (Qt-free, DRM/KMS)
  * runtime "python" / "qml" / none  -> hmi-gui.service (Qt loader, weston)

The bug these were written for: the installer always restarted hmi-ui.service.
A python bundle therefore started the Qt-free runtime, which found no
project.edsui, crash-looped, and the install rolled back after 25 s -- so no
Qt application could ever be deployed.

Unlike tests/test_install_atomicity.py, which overrides HMI_RESTART_CMD and
friends wholesale, these tests leave every HMI_*_CMD unset so the installer's
own `systemctl ...` defaults run, and put a stub `systemctl` first on PATH.
The stub logs each call, keeps a per-test enabled set, and knows which unit
files are "installed" -- so a test can assert WHICH unit was restarted,
enabled and disabled, and what the panel would boot into.

Requires a POSIX shell with flock; skipped elsewhere (Windows has neither).
Run under WSL on a Windows host.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "target" / "bin" / "hmi-install"

MISSING = [
    tool for tool in ("bash", "flock", "tar", "sha256sum", "python3")
    if shutil.which(tool) is None
]

UI = "hmi-ui.service"
QT = "hmi-gui.service"

# Stand-in for systemctl.  State lives in $STUB_DIR:
#   calls        one line per invocation ("restart hmi-gui.service")
#   units        installed unit files, one per line (`cat` succeeds for these)
#   enabled/<u>  exists while <u> is enabled
#   broken       units whose restart never produces the readiness file
# A restart of a unit not listed as broken touches $STUB_READY, which is what
# "the application came up" means to the installer.
STUB = r"""#!/bin/sh
echo "$*" >> "$STUB_DIR/calls"
verb="$1"; unit="$2"
case "$verb" in
    cat)        grep -qx "$unit" "$STUB_DIR/units" ;;
    enable)     grep -qx "$unit" "$STUB_DIR/units" || exit 1
                mkdir -p "$STUB_DIR/enabled"; : > "$STUB_DIR/enabled/$unit" ;;
    disable)    rm -f "$STUB_DIR/enabled/$unit" ;;
    is-enabled) [ -f "$STUB_DIR/enabled/$unit" ] ;;
    restart)    grep -qx "$unit" "$STUB_DIR/units" || exit 5
                grep -qx "$unit" "$STUB_DIR/broken" 2>/dev/null && exit 0
                : > "$STUB_READY" ;;
    *)          exit 0 ;;
esac
"""


@unittest.skipIf(MISSING, f"needs a POSIX shell environment; missing: {MISSING}")
class InstallerPicksGuiService(unittest.TestCase):
    """Drives the real installer with a stub systemctl on PATH."""

    def setUp(self):
        """Build an empty panel tree and a stub systemctl with both units."""
        self.root = Path(tempfile.mkdtemp())
        self.upload_dir = self.root / "tmp" / "hmi_upload"
        self.releases = self.root / "opt" / "hmi_apps" / "releases"
        for d in (self.upload_dir, self.root / "run" / "hmi", self.releases):
            d.mkdir(parents=True, exist_ok=True)

        self.stub_dir = self.root / "stub"
        self.stub_dir.mkdir()
        stub = self.stub_dir / "systemctl"
        stub.write_text(STUB, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
        self.set_units(UI, QT)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def set_units(self, *units):
        """Declare which GUI unit files exist on the stub panel."""
        (self.stub_dir / "units").write_text(
            "".join(u + "\n" for u in units), encoding="utf-8")

    def set_broken(self, *units):
        """Declare units whose restart never signals readiness."""
        (self.stub_dir / "broken").write_text(
            "".join(u + "\n" for u in units), encoding="utf-8")

    def enable(self, unit):
        """Pre-enable a unit, as provisioning or an earlier deploy would."""
        (self.stub_dir / "enabled").mkdir(exist_ok=True)
        (self.stub_dir / "enabled" / unit).touch()

    def enabled(self):
        """The set of units the stub panel would start at boot."""
        d = self.stub_dir / "enabled"
        return {p.name for p in d.iterdir()} if d.is_dir() else set()

    def calls(self):
        """Every systemctl invocation so far, oldest first."""
        f = self.stub_dir / "calls"
        return f.read_text(encoding="utf-8").splitlines() if f.exists() else []

    def restarts(self):
        """The units restarted so far, in order."""
        return [c.split()[1] for c in self.calls() if c.startswith("restart ")]

    def clear_calls(self):
        (self.stub_dir / "calls").unlink(missing_ok=True)

    def bundle(self, runtime, name):
        """Write a valid bundle for `runtime` (None = no runtime key)."""
        d = Path(tempfile.mkdtemp())
        entry = {"edsui": "project.edsui", "python": "main.py",
                 "qml": "main.qml", None: "main.qml"}[runtime]
        manifest = {"schema": 1, "name": name, "version": "1.0.0",
                    "entry": entry}
        if runtime is not None:
            manifest["runtime"] = runtime
        # Pretty-printed on purpose: the installer's no-python fallback parse
        # has to cope with a manifest spread over lines.
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2),
                                         encoding="utf-8")
        (d / entry).write_text(
            "import PySide6\n" if entry.endswith(".py") else "{}\n",
            encoding="utf-8")
        return d

    def upload(self, bundle_dir, tar_name):
        """Tar a bundle into the upload dir with its sha256 sidecar."""
        tgz = self.upload_dir / tar_name
        subprocess.run(["tar", "-czf", str(tgz), "-C", str(bundle_dir), "."],
                       check=True)
        digest = subprocess.run(["sha256sum", tar_name], cwd=self.upload_dir,
                                capture_output=True, text=True,
                                check=True).stdout
        (self.upload_dir / (tar_name + ".sha256")).write_text(digest,
                                                          encoding="utf-8")
        return tgz

    def run_installer(self, *args):
        """Run hmi-install with the systemctl defaults live (no overrides)."""
        env = dict(os.environ)
        for key in ("HMI_RESTART_CMD", "HMI_ENABLE_CMD", "HMI_ENABLE_CHECK_CMD",
                    "HMI_DISABLE_CMD", "HMI_SKIP_GUI_WAIT", "HMI_PYTHON"):
            env.pop(key, None)
        env.update(
            HMI_ROOT=str(self.root),
            PATH=f"{self.stub_dir}{os.pathsep}{env.get('PATH', '')}",
            STUB_DIR=str(self.stub_dir),
            STUB_READY=str(self.root / "run" / "hmi" / "gui-ready"),
            HMI_GUI_READY_TIMEOUT="2",
        )
        return subprocess.run(["bash", str(INSTALLER), *args],
                              capture_output=True, text=True, env=env)

    def install(self, runtime, name):
        """Upload and install a bundle of the given runtime."""
        return self.run_installer(
            "install", str(self.upload(self.bundle(runtime, name),
                                       name + ".tar.gz")))

    def current(self):
        """Resolve `current` to the release directory it names."""
        return os.path.realpath(self.root / "opt" / "hmi_apps" / "current")

    # -- tests -----------------------------------------------------------

    def test_python_bundle_runs_under_hmi_gui(self):
        """The fix itself: a Qt app is started by the Qt loader's unit."""
        self.enable(UI)  # a Qt-free panel as provisioned
        result = self.install("python", "qt-app")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.restarts(), [QT])
        self.assertIn(f"STEP gui ok {QT} (runtime=python)", result.stdout)

    def test_python_bundle_becomes_boot_default_and_hmi_ui_does_not(self):
        """Both enabled would boot hmi-ui: its Conflicts= wins the clash."""
        self.enable(UI)
        result = self.install("python", "qt-app")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.enabled(), {QT})
        self.assertIn(f"disable {UI}", self.calls())
        self.assertIn(f"enable-boot ok {QT} will start at boot", result.stdout)

    def test_edsui_bundle_runs_under_hmi_ui_and_disables_hmi_gui(self):
        """The reverse switch, from a panel that last ran a Qt app."""
        self.enable(QT)
        result = self.install("edsui", "studio-design")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.restarts(), [UI])
        self.assertEqual(self.enabled(), {UI})
        self.assertIn(f"disable {QT}", self.calls())

    def test_missing_runtime_means_the_manifest_default_qml(self):
        """schema/manifest.py defaults runtime to qml, a Qt-loader bundle."""
        result = self.install(None, "legacy-qml")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.restarts(), [QT])

    def test_edsui_on_a_qt_free_panel_does_not_touch_the_absent_unit(self):
        """Disabling a unit with no file fails in systemd; it is skipped."""
        self.set_units(UI)
        result = self.install("edsui", "studio-design")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(f"disable {QT}", self.calls())
        self.assertEqual(self.enabled(), {UI})

    def test_failed_python_bundle_rolls_back_to_edsui_under_hmi_ui(self):
        """Rollback restarts the PREVIOUS release's unit, not the failed one's."""
        good = self.install("edsui", "studio-design")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        running = self.current()
        self.clear_calls()
        self.set_broken(QT)

        bad = self.install("python", "qt-app")

        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertIn("auto-rollback-start", bad.stdout)
        self.assertEqual(self.current(), running)
        self.assertEqual(self.restarts(), [QT, UI])
        # enable_boot never ran for the failed release, so boot still says hmi-ui.
        self.assertEqual(self.enabled(), {UI})

    def test_missing_hmi_gui_refuses_before_the_symlink_moves(self):
        """A Qt bundle on a Qt-free panel: refuse at once, change nothing."""
        self.set_units(UI)
        good = self.install("edsui", "studio-design")
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        running = self.current()
        releases_before = sorted(p.name for p in self.releases.iterdir())
        self.clear_calls()

        result = self.install("python", "qt-app")

        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn(f"STEP gui fail {QT} not installed", result.stdout)
        self.assertNotIn("swap-symlink", result.stdout)
        self.assertEqual(self.current(), running)
        self.assertEqual(sorted(p.name for p in self.releases.iterdir()),
                         releases_before)
        self.assertEqual(self.restarts(), [])
        self.assertEqual(self.enabled(), {UI})
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_manual_rollback_moves_boot_back_to_the_previous_runtime(self):
        """A verified python release was the boot default; rollback undoes it."""
        self.install("edsui", "studio-design")
        edsui_release = self.current()
        self.install("python", "qt-app")
        self.assertEqual(self.enabled(), {QT})
        self.clear_calls()

        result = self.run_installer("rollback")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.current(), edsui_release)
        self.assertEqual(self.restarts(), [UI])
        self.assertEqual(self.enabled(), {UI})

    def test_activate_follows_the_activated_release_runtime(self):
        """Activating an old edsui release switches unit and boot default."""
        self.install("edsui", "studio-design")
        edsui_name = os.path.basename(self.current())
        self.install("python", "qt-app")
        self.install("python", "qt-app-two")
        self.clear_calls()

        result = self.run_installer("activate", edsui_name)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.restarts(), [UI])
        self.assertEqual(self.enabled(), {UI})

    def test_explicit_restart_override_is_honoured_for_every_runtime(self):
        """Backward compatibility: HMI_RESTART_CMD wins, no unit check."""
        self.set_units()  # no GUI units at all: the override owns the service
        ready = self.root / "run" / "hmi" / "gui-ready"
        tgz = self.upload(self.bundle("python", "qt-app"), "qt-app.tar.gz")
        env = dict(os.environ, HMI_ROOT=str(self.root),
                   HMI_RESTART_CMD=f'touch {ready}; echo "$HMI_GUI_SERVICE" > {self.root}/svc',
                   HMI_ENABLE_CMD="true", HMI_ENABLE_CHECK_CMD="true",
                   HMI_GUI_READY_TIMEOUT="2")
        env.pop("HMI_SKIP_GUI_WAIT", None)
        result = subprocess.run(["bash", str(INSTALLER), "install", str(tgz)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / "svc").read_text().strip(), QT)

    def test_runtime_is_read_without_a_json_capable_python(self):
        """The rollback path must not depend on the interpreter's stdlib.

        HMI_PYTHON is pointed at a wrapper that fails any snippet importing
        json -- a python3-core image in miniature -- so bundle_runtime has to
        fall back to its sed parse of the (pretty-printed) manifest.
        """
        self.install("edsui", "studio-design")
        edsui_release = self.current()
        self.install("python", "qt-app")
        self.clear_calls()

        shim = self.stub_dir / "python-nojson"
        shim.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in *'import json'*) exit 1 ;; esac\n"
            "exec python3 \"$@\"\n",
            encoding="utf-8", newline="\n")
        shim.chmod(0o755)

        env = dict(os.environ)
        for key in ("HMI_RESTART_CMD", "HMI_ENABLE_CMD", "HMI_ENABLE_CHECK_CMD",
                    "HMI_DISABLE_CMD", "HMI_SKIP_GUI_WAIT"):
            env.pop(key, None)
        env.update(HMI_PYTHON=str(shim), HMI_ROOT=str(self.root),
                   PATH=f"{self.stub_dir}{os.pathsep}{env.get('PATH', '')}",
                   STUB_DIR=str(self.stub_dir),
                   STUB_READY=str(self.root / "run" / "hmi" / "gui-ready"),
                   HMI_GUI_READY_TIMEOUT="2")
        result = subprocess.run(["bash", str(INSTALLER), "rollback"],
                                capture_output=True, text=True, env=env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.current(), edsui_release)
        self.assertEqual(self.restarts(), [UI])

if __name__ == "__main__":
    unittest.main(verbosity=2)
