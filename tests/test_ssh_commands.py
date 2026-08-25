"""Tests for host-side SSH and SCP command construction."""

import os
import unittest
from unittest import mock

from tools.hmi_deployer import ssh
from tools.hmi_deployer.mainwindow import (
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


if __name__ == "__main__":
    unittest.main()
