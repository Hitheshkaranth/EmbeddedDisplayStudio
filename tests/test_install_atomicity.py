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

    def _run(self, *args):
        """Run any hmi-install subcommand against the throwaway root."""
        env = dict(
            os.environ,
            HMI_ROOT=str(self.root),
            HMI_RESTART_CMD="true",
            HMI_SKIP_GUI_WAIT="1",
        )
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            capture_output=True, text=True, env=env,
        )

    def _install_for_real(self, tgz, renders=True, enable_ok=True, enable_takes=True):
        """Install with the GUI wait and rollback path actually enabled.

        Args:
            tgz:          the bundle to install.
            renders:      whether the restart stub creates the readiness
                          sentinel, which is the only thing that distinguishes
                          an application that came up from one that did not.
            enable_ok:    whether the enable command reports success.
            enable_takes: whether the unit is actually enabled afterwards.
                          Separate from enable_ok on purpose: a stand-in
                          systemctl that answers 0 to everything is the classic
                          way this step looks done while doing nothing, and the
                          installer is expected to catch the disagreement.

        Every other test here sets HMI_SKIP_GUI_WAIT=1, which returns early
        from restart_gui -- and with it skips the readiness wait, the automatic
        rollback and enable_boot. Those four behaviours are what the platform
        is sold on, so at least one path has to run them.
        """
        ready = self.root / "run" / "hmi" / "gui-ready"
        restart = f"touch {ready}" if renders else "true"
        enable = (
            f"touch {self.enable_marker}" if enable_ok else "false"
        )
        env = dict(
            os.environ,
            HMI_ROOT=str(self.root),
            HMI_RESTART_CMD=restart,
            HMI_ENABLE_CMD=enable,
            # Stands in for `systemctl is-enabled`: the marker the enable stub
            # writes is what "the unit is enabled" means in this fixture.
            HMI_ENABLE_CHECK_CMD=(
                f"test -f {self.enable_marker}" if enable_takes else "false"
            ),
            # The real deadline is 25s. The rollback case has to wait it out,
            # and the guarantee is worth proving in seconds.
            HMI_GUI_READY_TIMEOUT="2",
        )
        env.pop("HMI_SKIP_GUI_WAIT", None)
        return subprocess.run(
            ["bash", str(INSTALLER), "install", str(tgz)],
            capture_output=True, text=True, env=env,
        )

    @property
    def enable_marker(self):
        """Written by the stub standing in for `systemctl enable`."""
        return self.root / "run" / "hmi" / "boot-enabled"

    # -- tests -----------------------------------------------------------

    def test_a_release_that_never_renders_is_rolled_back(self):
        """The promise the platform is sold on: a bad deploy cannot leave a
        machine without a UI.

        Until this test existed the branch was unreachable from the suite --
        every installer test disabled the GUI wait, and the same switch
        disables the rollback it guards.
        """
        good = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz")
        )
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        running = self._current_target()

        bad = self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "bad.tar.gz"),
            renders=False,
        )

        self.assertNotEqual(bad.returncode, 0, "a deploy that never rendered reported success")
        self.assertIn("auto-rollback-start", bad.stdout)
        self.assertEqual(
            self._current_target(), running,
            "the panel was left pointing at a release that never came up",
        )

    def test_the_release_that_failed_is_not_left_behind(self):
        """A release that never rendered is not one to keep or roll forward to."""
        self._install_for_real(self._upload(self._bundle(name="renders"), "good.tar.gz"))
        before = set(self._release_dirs())

        self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "bad.tar.gz"),
            renders=False,
        )

        self.assertEqual(
            set(self._release_dirs()), before,
            "the failed release is still on the panel after rollback",
        )

    def test_a_release_that_renders_becomes_the_boot_default(self):
        """Deploying is the only step; nothing is enabled by hand afterwards.

        enable_boot runs after the readiness check and not before, so only a
        release proven to render is made the one the panel starts at power-on.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            self.enable_marker.exists(),
            "the release renders but was never made the boot default",
        )
        self.assertIn("enable-boot ok", result.stdout)

    def test_a_release_that_never_renders_is_never_made_the_boot_default(self):
        """The worst outcome is a panel that boots into a UI that cannot start."""
        self._install_for_real(self._upload(self._bundle(name="renders"), "good.tar.gz"))
        self.enable_marker.unlink()

        self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "bad.tar.gz"),
            renders=False,
        )

        self.assertFalse(
            self.enable_marker.exists(),
            "a release that never rendered was made the panel's boot default",
        )

    def test_a_first_install_that_never_renders_still_reports_completion(self):
        """A fresh panel has nothing to roll back to, and must still say so.

        rollback_to_previous returns 1 in that case, and under `set -e` a plain
        call to it killed the script on the spot -- so the cleanup never ran and
        the terminal install-complete line was never printed. Both host tools
        parse STEP output; a deploy that stops mid-sentence reads as a crash
        rather than as the reportable failure it is.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "first.tar.gz"),
            renders=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("auto-rollback-start", result.stdout)
        self.assertIn(
            "STEP install-complete", result.stdout,
            "the installer exited without a terminal STEP line",
        )
        self.assertIn("no previous release", result.stdout)

    def test_a_first_install_that_never_renders_leaves_current_resolvable(self):
        """A dangling `current` is worse than one naming a broken release.

        The loader follows it either way, and only one of the two can be
        inspected afterwards to find out what happened.
        """
        self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "first.tar.gz"),
            renders=False,
        )
        current = self.root / "opt" / "hmi_apps" / "current"
        if current.is_symlink():
            self.assertTrue(
                os.path.exists(os.path.realpath(current)),
                "current points at a release that no longer exists",
            )

    def test_the_boot_default_failing_does_not_roll_back_the_release(self):
        """The application is running; it simply will not survive a reboot.

        Rolling that back would replace a release that came up perfectly well
        with an older one, over a problem that only appears at the next power
        cycle. So the release stays live and stays current.
        """
        good = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz")
        )
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

        result = self._install_for_real(
            self._upload(self._bundle(name="second"), "second.tar.gz"),
            enable_ok=False,
        )

        self.assertIn("enable-boot fail", result.stdout)
        self.assertNotIn("auto-rollback-start", result.stdout)
        self.assertIn(
            "second", os.path.basename(self._current_target()),
            "a release that came up fine was rolled back over autostart",
        )

    def test_the_boot_default_failing_is_not_reported_as_a_clean_deploy(self):
        """Exit 0 here is how a panel comes up blank with nothing explaining it.

        The STEP line alone was not enough: an unattended caller -- CI, or
        anything wrapping deploy_to_hmi.sh -- saw a zero between two success
        lines and had no reason to look further. The status has to carry it.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz"),
            enable_ok=False,
        )
        self.assertEqual(
            result.returncode, 4,
            "a deploy that will not survive a reboot reported itself clean:\n"
            + result.stdout + result.stderr,
        )

    def test_the_partial_outcome_is_distinct_from_a_failed_deploy(self):
        """4 and 1 have to differ, or the distinction buys nothing.

        A caller seeing 1 should consider the deploy not done; a caller seeing
        4 has a running application and one command to run on the panel.
        """
        partial = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz"),
            enable_ok=False,
        )
        failed = self._install_for_real(
            self._upload(self._bundle(name="never-renders"), "bad.tar.gz"),
            renders=False,
        )
        self.assertEqual(partial.returncode, 4)
        self.assertEqual(failed.returncode, 1)

    def test_a_partial_install_still_prunes_and_reports_completion(self):
        """The steps after enable_boot are not skipped by the new exit path.

        `enable_boot || true` used to swallow the status precisely so that
        `set -e` could not cut the run short here. Returning 4 instead has to
        keep that property: the terminal STEP line and the cleanup both run.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz"),
            enable_ok=False,
        )
        self.assertIn(
            "STEP install-complete", result.stdout,
            "the installer exited without a terminal STEP line",
        )
        self.assertIn("autostart NOT configured", result.stdout)
        self.assertEqual(
            list(self.upload.iterdir()), [],
            "the upload directory was left behind by the partial path",
        )

    def test_an_enable_command_that_lies_is_not_taken_at_its_word(self):
        """A stub systemctl answering 0 to everything is the usual false pass.

        HMI_ENABLE_CMD is documented as overridable, so its exit status says
        only that something ran. The panel that comes up blank is the one where
        the command succeeded and the unit was never linked, which is exactly
        the case a return code alone cannot see.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz"),
            enable_ok=True,
            enable_takes=False,
        )
        self.assertEqual(
            result.returncode, 4,
            "an unconfirmed autostart reported a clean deploy:\n"
            + result.stdout + result.stderr,
        )
        self.assertIn("enable-boot fail", result.stdout)
        self.assertIn("still not enabled", result.stdout)

    def test_a_confirmed_enable_says_so(self):
        """The success line distinguishes 'ran' from 'verified'.

        Without the word, the ok line reads identically whether or not anything
        checked -- which is what the failure above was hiding behind.
        """
        result = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz")
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("enable-boot ok", result.stdout)
        self.assertIn("confirmed", result.stdout)

    def test_a_lying_enable_still_leaves_the_release_live(self):
        """Same verdict as a plain enable failure: report it, do not undo it."""
        good = self._install_for_real(
            self._upload(self._bundle(name="renders"), "good.tar.gz")
        )
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

        result = self._install_for_real(
            self._upload(self._bundle(name="second"), "second.tar.gz"),
            enable_ok=True,
            enable_takes=False,
        )
        self.assertNotIn("auto-rollback-start", result.stdout)
        self.assertIn(
            "second", os.path.basename(self._current_target()),
            "a release that came up fine was rolled back over autostart",
        )

    def test_activate_reaches_a_release_rollback_cannot(self):
        """Rollback goes one release back; the board keeps more than one.

        A regression noticed two deploys late could be listed and never
        returned to, which is the whole reason retention exists.
        """
        first = self._install(self._upload(self._bundle(name="app-one"), "a.tar.gz"))
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        oldest = os.path.basename(self._current_target())

        self._install(self._upload(self._bundle(name="app-two"), "b.tar.gz"))
        self._install(self._upload(self._bundle(name="app-three"), "c.tar.gz"))
        newest = os.path.basename(self._current_target())
        self.assertNotEqual(newest, oldest)

        result = self._run("activate", oldest)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.path.basename(self._current_target()), oldest)

    def test_activation_is_itself_undoable(self):
        """The outgoing release becomes previous, so rollback returns to it."""
        self._install(self._upload(self._bundle(name="app-one"), "a.tar.gz"))
        oldest = os.path.basename(self._current_target())
        self._install(self._upload(self._bundle(name="app-two"), "b.tar.gz"))
        was_running = os.path.basename(self._current_target())

        self._run("activate", oldest)
        self.assertEqual(os.path.basename(self._current_target()), oldest)

        rolled = self._run("rollback")
        self.assertEqual(rolled.returncode, 0, rolled.stdout + rolled.stderr)
        self.assertEqual(os.path.basename(self._current_target()), was_running)

    def test_activate_refuses_a_name_that_is_a_path(self):
        """The name crosses SSH and is joined onto a directory.

        Anything with a separator or a parent reference would make this a way
        to point `current` at somewhere else on the filesystem entirely.
        """
        self._install(self._upload(self._bundle(name="app-one"), "a.tar.gz"))
        running = self._current_target()

        for hostile in ("../../etc", "a/b", "..", ".hidden"):
            with self.subTest(name=hostile):
                result = self._run("activate", hostile)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertEqual(self._current_target(), running)

    def test_activate_refuses_a_release_that_is_not_installed(self):
        """A stale picker must not be able to break the running panel."""
        self._install(self._upload(self._bundle(name="app-one"), "a.tar.gz"))
        running = self._current_target()
        result = self._run("activate", "never-installed")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertEqual(self._current_target(), running)

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
