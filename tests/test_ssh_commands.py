"""Tests for host-side SSH and SCP command construction."""

import os
import unittest
from unittest import mock

from tools.hmi_deployer import ssh
from tools.hmi_deployer.mainwindow import (
    MEMORY_PROFILE_COMMAND,
    format_bytes,
    format_kib,
    parse_display_resolution,
    parse_memory_profile_line,
)


class TestOpenSshResolution(unittest.TestCase):
    """Keep Windows command lookup away from PATH wrapper scripts."""

    def test_windows_prefers_system_openssh_executable(self):
        """A standard Windows OpenSSH install is selected by absolute path."""
        with (
            mock.patch.object(ssh.os, "name", "nt"),
            mock.patch.dict(ssh.os.environ, {"SystemRoot": r"C:\Windows"}),
            mock.patch.object(ssh.os.path, "isfile", return_value=True),
        ):
            command = ssh.build_ssh_cmd("panel", "root", 22, "", "true")

        self.assertEqual(
            command[0],
            os.path.join(r"C:\Windows", "System32", "OpenSSH", "ssh.exe"),
        )

    def test_non_windows_retains_path_lookup(self):
        """Linux targets keep using the OpenSSH client supplied by PATH."""
        with mock.patch.object(ssh.os, "name", "posix"):
            command = ssh.build_scp_cmd("panel", "root", 22, "", "src", "dest")

        self.assertEqual(command[0], "scp")


class TestDisplayResolutionParsing(unittest.TestCase):
    """Validate the machine-readable display response from a remote SOM."""

    def test_parses_valid_remote_marker(self):
        """A detected DRM or framebuffer mode becomes pixel dimensions."""
        self.assertEqual(parse_display_resolution("HMI_DISPLAY=1024x768"), (1024, 768))

    def test_ignores_non_marker_and_invalid_dimensions(self):
        """Normal SSH output must not accidentally change the preview size."""
        self.assertIsNone(parse_display_resolution("SSH OK"))
        self.assertIsNone(parse_display_resolution("HMI_DISPLAY=0x768"))


class TestReleaseListing(unittest.TestCase):
    """The release picker is only as good as its reading of `hmi-install list`."""

    def test_markers_are_read_off_the_installer_listing(self):
        """`[current]` and `[previous]` are the installer's stable vocabulary."""
        self.assertEqual(
            ssh.parse_release_line("  app-20260303T000000Z [current]"),
            ssh.Release("app-20260303T000000Z", True, False),
        )
        self.assertEqual(
            ssh.parse_release_line("  app-20260202T000000Z [previous]"),
            ssh.Release("app-20260202T000000Z", False, True),
        )
        self.assertEqual(
            ssh.parse_release_line("  app-20260101T000000Z"),
            ssh.Release("app-20260101T000000Z", False, False),
        )

    def test_one_release_can_be_both(self):
        """After a rollback the same release is current and previous."""
        release = ssh.parse_release_line("  app-1 [current] [previous]")
        self.assertTrue(release.is_current and release.is_previous)

    def test_everything_that_is_not_a_release_row_is_ignored(self):
        """STEP lines and installer logs share the stream with the listing."""
        for line in ("STEP list ok ", "[hmi-install] INFO: cleaned upload", "", "no-indent"):
            with self.subTest(line=line):
                self.assertIsNone(ssh.parse_release_line(line))

    def test_a_release_name_reaching_the_shell_is_quoted(self):
        """The name comes back from the panel, but it is still shell input."""
        command = ssh.build_activate_command("rel a; rm -rf /")
        self.assertIn("'rel a; rm -rf /'", command)
        self.assertTrue(command.startswith("hmi-install activate "))


class TestPanelLogs(unittest.TestCase):
    """A follow that hangs in a pager is indistinguishable from a dead panel."""

    def test_the_journal_is_never_paged(self):
        """journalctl pages when it sees a terminal, and ssh gives it one."""
        self.assertIn("--no-pager", ssh.build_logs_command())

    def test_both_panel_services_are_followed(self):
        """A fault in either unit is what the operator is looking for."""
        command = ssh.build_logs_command()
        for unit in ssh.LOG_UNITS:
            self.assertIn(f"-u {unit}", command)

    def test_history_then_follow(self):
        """Opening the tab on a quiet panel must not show an empty view."""
        self.assertIn("-n 50", ssh.build_logs_command(lines=50))
        self.assertTrue(ssh.build_logs_command(follow=True).endswith("-f"))
        self.assertFalse(ssh.build_logs_command(follow=False).endswith("-f"))


class TestMemoryProfileParsing(unittest.TestCase):
    """Validate streamed SOM memory-profile fields and their display formats."""

    def test_profile_field_parses(self):
        """The profile marker retains its field name and value."""
        self.assertEqual(
            parse_memory_profile_line("HMI_PROFILE_FREE_KB=2014716"),
            ("FREE_KB", "2014716"),
        )

    def test_non_profile_output_is_ignored(self):
        """Console text must not alter the profile model."""
        self.assertIsNone(parse_memory_profile_line("hmi-gui now: active"))

    def test_size_formatting_is_compact(self):
        """Large target measurements remain readable inside cards and bars."""
        self.assertEqual(format_kib(1024 * 1024), "1.00 GiB")
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MiB")

    def test_cheap_fields_are_emitted_before_the_compression_step(self):
        """Storage and RAM must not queue behind a multi-minute tar.

        Recompressing a 300 MiB release takes about three minutes. While it sat
        ahead of these fields the profile tab showed zeroes for all of them for
        the whole run, which is indistinguishable from a refresh that failed.
        """
        compression = MEMORY_PROFILE_COMMAND.index("tar -C")
        for field in (
            "HMI_PROFILE_RELEASE=",
            "HMI_PROFILE_APP_KB=",
            "HMI_PROFILE_RELEASES_KB=",
            "HMI_PROFILE_ROOT_KB=",
            "HMI_PROFILE_USED_KB=",
            "HMI_PROFILE_FREE_KB=",
            "HMI_PROFILE_RAM_AVAILABLE_KB=",
        ):
            self.assertLess(
                MEMORY_PROFILE_COMMAND.index(field),
                compression,
                f"{field} is reported only after the compression measurement",
            )

    def test_compressed_size_is_still_reported_on_both_paths(self):
        """Splitting the command must not lose the field on either branch."""
        self.assertEqual(MEMORY_PROFILE_COMMAND.count("HMI_PROFILE_COMPRESSED_BYTES="), 2)
        self.assertGreater(
            MEMORY_PROFILE_COMMAND.index("HMI_PROFILE_STAGE="),
            MEMORY_PROFILE_COMMAND.index("HMI_PROFILE_RAM_AVAILABLE_KB="),
        )


if __name__ == "__main__":
    unittest.main()
