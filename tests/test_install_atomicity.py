"""
tests/test_install_atomicity.py
Layer: Test (W11)

Pins the promises CONTRACT section 6 makes about hmi-install, none of which
had a test:

  * a release id is unique, so installing twice never reuses a directory
  * the release the panel is running is never deleted by a new install
  * `previous` points at the release that was current before the install
  * a hostile archive is refused before any of it is written to disk
  * a failed upload leaves nothing behind on the tmpfs

The bug these were written for: hmi-install derived the release directory from
the uploaded filename, and deploy_to_hmi.sh names its tarball
<name>-<version>.tar.gz. Redeploying the same version therefore resolved to the
directory `current` already pointed at, and the installer's "remove a stale
staging dir" step deleted the running release before save_previous recorded
that same directory as the rollback target. A failed deploy then rolled back
onto the release it had just destroyed -- so the headline guarantee, "a bad
deploy cannot leave a machine without a UI", did not hold for the single most
common developer action.

Requires a POSIX shell with flock; skipped elsewhere (Windows has neither).
"""

import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "target" / "bin" / "hmi-install"

MISSING = [
    tool for tool in ("bash", "flock", "tar", "sha256sum", "python3")
    if shutil.which(tool) is None
]


@unittest.skipIf(MISSING, f"needs a POSIX shell environment; missing: {MISSING}")
class InstallerAtomicity(unittest.TestCase):
    """Drives the real installer against a throwaway HMI_ROOT."""

    def setUp(self):
        """Build an empty target tree that looks like a provisioned panel."""
        self.root = Path(tempfile.mkdtemp())
        self.upload = self.root / "tmp" / "hmi_upload"
        self.releases = self.root / "opt" / "hmi_apps" / "releases"
        for d in (self.upload, self.root / "run" / "hmi", self.releases):
            d.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _bundle(self, name="line-controller", version="1.0.0", marker="first"):
        """Write a valid bundle directory and return its path.

        Args:
            name:    manifest app name.
            version: manifest version -- deliberately reused across installs.
            marker:  content written into main.qml so the two releases are
                     distinguishable on disk.
        """
        d = Path(tempfile.mkdtemp())
        (d / "manifest.json").write_text(json.dumps({
            "schema": 1, "name": name, "version": version,
            "entry": "main.qml",
            "screen": {"width": 1280, "height": 800},
            "tags_required": [], "qt": ">=6.5",
        }), encoding="utf-8")
        (d / "main.qml").write_text(f"// {marker}\nimport QtQuick\n", encoding="utf-8")
        return d

    def _upload(self, bundle_dir, tar_name):
        """Tar a bundle into the upload dir with its sha256 sidecar.

        Args:
            bundle_dir: directory to pack.
            tar_name:   filename to use -- the point of several tests is that
                        the same name can be uploaded twice.
        """
        tgz = self.upload / tar_name
        subprocess.run(["tar", "-czf", str(tgz), "-C", str(bundle_dir), "."], check=True)
        digest = subprocess.run(
            ["sha256sum", tar_name], cwd=self.upload,
            capture_output=True, text=True, check=True,
        ).stdout
        (self.upload / (tar_name + ".sha256")).write_text(digest, encoding="utf-8")
        return tgz

    def _install(self, tgz):
        """Run `hmi-install install <tgz>` against the throwaway root.

        Returns:
            The CompletedProcess, so callers can assert on status and STEP lines.
        """
        env = dict(
            os.environ,
            HMI_ROOT=str(self.root),
            HMI_RESTART_CMD="true",     # no systemd on a test host
            HMI_SKIP_GUI_WAIT="1",      # no GUI to recreate the ready file
        )
        return subprocess.run(
            ["bash", str(INSTALLER), "install", str(tgz)],
            capture_output=True, text=True, env=env,
        )

    def _current_target(self):
        """Resolve the `current` symlink to the release directory it names."""
        return os.path.realpath(self.root / "opt" / "hmi_apps" / "current")

    def _release_dirs(self):
        """Return the release directory names, excluding staging leftovers."""
        return sorted(
            p.name for p in self.releases.iterdir()
            if p.is_dir() and not p.name.startswith(".stage.")
        )

    # -- tests -----------------------------------------------------------

    def test_same_version_twice_keeps_the_running_release(self):
        """
        The regression. Two installs of the identical name+version must produce
        two distinct releases, and the first must still exist afterwards --
        because `previous` points at it and rollback has to be able to return.
        """
        first = self._install(self._upload(self._bundle(marker="first"), "app-1.0.0.tar.gz"))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        first_release = self._current_target()

        second = self._install(self._upload(self._bundle(marker="second"), "app-1.0.0.tar.gz"))
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_release = self._current_target()

        self.assertNotEqual(
            first_release, second_release,
            "Both installs resolved to the same release directory: the release "
            "id is not unique, so the second install overwrote the first.",
        )
        self.assertTrue(
            os.path.isdir(first_release),
            "The first release was deleted by the second install -- the panel's "
            "running code was removed out from under it.",
        )
        self.assertEqual(
            len(self._release_dirs()), 2,
            f"Expected two distinct releases, found {self._release_dirs()}",
        )

    def test_previous_points_at_the_release_that_was_current(self):
        """Rollback is only meaningful if `previous` names a different release
        that still exists on disk."""
        self._install(self._upload(self._bundle(marker="first"), "app-1.0.0.tar.gz"))
        first_release = self._current_target()
        self._install(self._upload(self._bundle(marker="second"), "app-1.0.0.tar.gz"))

        previous = os.path.realpath(self.root / "opt" / "hmi_apps" / "previous")
        self.assertEqual(previous, first_release)
        self.assertNotEqual(previous, self._current_target())
        self.assertTrue(os.path.isdir(previous))

    def test_release_id_follows_the_contract(self):
        """CONTRACT section 3: <name>-<UTC yyyymmddTHHMMSSZ>, not the tarball
        name. The uploaded file is deliberately given an unrelated name."""
        self._install(self._upload(self._bundle(name="line-controller"),
                                   "something-else-entirely.tar.gz"))
        releases = self._release_dirs()
        self.assertEqual(len(releases), 1)
        self.assertRegex(releases[0], r"^line-controller-\d{8}T\d{6}Z(\.\d+)?$")

    def test_traversal_bundle_is_refused_before_extraction(self):
        """
        A member escaping the bundle root must be rejected by the prescan, with
        nothing written. The old check ran after extraction and walked the
        staging directory, where an escaped member by definition is not.
        """
        d = Path(tempfile.mkdtemp())
        (d / "manifest.json").write_text(json.dumps({
            "schema": 1, "name": "evil", "version": "1.0.0", "entry": "main.qml",
        }), encoding="utf-8")
        (d / "main.qml").write_text("import QtQuick\n", encoding="utf-8")

        tgz = self.upload / "evil.tar.gz"
        with tarfile.open(tgz, "w:gz") as tar:
            tar.add(d / "manifest.json", arcname="manifest.json")
            tar.add(d / "main.qml", arcname="main.qml")
            escaped = tarfile.TarInfo("../../../../etc/hmi-install-was-here")
            payload = b"pwned\n"
            escaped.size = len(payload)
            import io
            tar.addfile(escaped, io.BytesIO(payload))

        digest = subprocess.run(
            ["sha256sum", "evil.tar.gz"], cwd=self.upload,
            capture_output=True, text=True, check=True,
        ).stdout
        (self.upload / "evil.tar.gz.sha256").write_text(digest, encoding="utf-8")

        result = self._install(tgz)
        self.assertNotEqual(result.returncode, 0, "Traversal bundle was accepted")
        self.assertIn("STEP prescan fail", result.stdout)
        self.assertEqual(
            self._release_dirs(), [],
            "A rejected bundle still created a release directory",
        )

    def test_upload_dir_is_emptied_even_when_the_install_fails(self):
        """
        UPLOAD_DIR is a tmpfs. Before the EXIT trap existed, every validation
        failure left its tarball there, so repeated failed deploys consumed RAM
        on a running machine.
        """
        d = Path(tempfile.mkdtemp())
        (d / "manifest.json").write_text('{"schema": 99}', encoding="utf-8")
        tgz = self._upload(d, "bad.tar.gz")

        result = self._install(tgz)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            list(self.upload.iterdir()), [],
            "Upload directory still holds files after a failed install",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
