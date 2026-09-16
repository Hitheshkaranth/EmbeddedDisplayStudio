"""A deploy key bundle carries the panel's key and address to another user.

Export packs the private key, its .pub and the target; import installs the
key where OpenSSH accepts it and returns the connection to fill in. A
passphrase-protected key is refused (the Studio deploys in BatchMode) and a
file that is not a bundle is reported, not half-installed.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tools.hmi_deployer import deploy_key  # noqa: E402


def _keypair(directory, passphrase=""):
    path = os.path.join(directory, "id_test")
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", passphrase, "-f", path, "-C", "test"],
                   check=True, capture_output=True)
    return path


class DeployKeyBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_export_then_import_round_trips_key_and_target(self):
        key = _keypair(self.tmp)
        bundle = deploy_key.export_bundle(key, os.path.join(self.tmp, "line3"), "172.16.20.70",
                                          "root", 22, label="Line 3")
        self.assertTrue(bundle.endswith(".hmikey"))
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(set(archive.namelist()), {"bundle.json", "key/id_test", "key/id_test.pub"})
            manifest = json.loads(archive.read("bundle.json"))
        self.assertEqual(manifest["target"], {"host": "172.16.20.70", "user": "root", "port": 22})
        self.assertEqual(manifest["label"], "Line 3")

        install = os.path.join(self.tmp, "installed")
        info = deploy_key.import_bundle(bundle, install_dir=install)
        self.assertEqual(info["host"], "172.16.20.70")
        self.assertEqual(info["key"], os.path.join(install, "line3"))
        with open(key, "rb") as original, open(info["key"], "rb") as copied:
            self.assertEqual(original.read(), copied.read())
        self.assertTrue(os.path.isfile(info["key"] + ".pub"))
        if platform.system() != "Windows":
            self.assertEqual(oct(os.stat(info["key"]).st_mode & 0o777), "0o600")
        else:
            acl = subprocess.run(["icacls", info["key"]], capture_output=True, text=True).stdout
            self.assertNotIn("BUILTIN\\Users", acl)

    def test_a_passphrase_key_is_refused(self):
        key = _keypair(self.tmp, passphrase="secret")
        with self.assertRaises(deploy_key.DeployKeyError) as ctx:
            deploy_key.export_bundle(key, os.path.join(self.tmp, "x"), "10.0.0.1")
        self.assertIn("passphrase", str(ctx.exception))

    def test_missing_key_or_host_is_reported(self):
        with self.assertRaises(deploy_key.DeployKeyError):
            deploy_key.export_bundle(os.path.join(self.tmp, "nope"), os.path.join(self.tmp, "x"), "10.0.0.1")
        key = _keypair(self.tmp)
        with self.assertRaises(deploy_key.DeployKeyError):
            deploy_key.export_bundle(key, os.path.join(self.tmp, "x"), "   ")

    def test_a_file_that_is_not_a_bundle_is_rejected(self):
        junk = os.path.join(self.tmp, "junk.hmikey")
        with open(junk, "w", encoding="utf-8") as handle:
            handle.write("not a zip")
        with self.assertRaises(deploy_key.DeployKeyError):
            deploy_key.import_bundle(junk, install_dir=os.path.join(self.tmp, "i"))
        with zipfile.ZipFile(junk, "w") as archive:
            archive.writestr("bundle.json", json.dumps({"format": 99}))
        with self.assertRaises(deploy_key.DeployKeyError):
            deploy_key.import_bundle(junk, install_dir=os.path.join(self.tmp, "i"))

    def test_cli_round_trip(self):
        key = _keypair(self.tmp)
        out = os.path.join(self.tmp, "cli")
        self.assertEqual(deploy_key.main(["export", "--key", key, "--host", "10.1.1.5", "--port", "2222",
                                          "--out", out, "--no-verify"]), 0)
        self.assertTrue(os.path.isfile(out + ".hmikey"))
        self.assertEqual(deploy_key.read_bundle(out + ".hmikey")["target"]["port"], 2222)


class StudioAppliesTheKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        cls._stylesheet, cls._font = cls.app.styleSheet(), cls.app.font()
        settings = QSettings("MIL-HMI", "Deployer")
        cls._saved = {k: settings.value(k, "") for k in ("last_bundle", "host", "user", "port", "key")}

    @classmethod
    def tearDownClass(cls):
        from PySide6.QtCore import QSettings
        cls.app.setStyleSheet(cls._stylesheet)
        cls.app.setFont(cls._font)
        settings = QSettings("MIL-HMI", "Deployer")
        for key, value in cls._saved.items():
            settings.setValue(key, value)

    def test_import_fills_the_connection_fields(self):
        from tools.hmi_deployer.mainwindow import MainWindow
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), window.deleteLater(), self.app.processEvents()))
        window.apply_deploy_key({"key": "C:/k/line3", "host": "172.16.20.70", "user": "root", "port": 2200})
        self.assertEqual(window.inp_key.text(), "C:/k/line3")
        self.assertEqual(window.inp_host.text(), "172.16.20.70")
        self.assertEqual(window.inp_port.text(), "2200")
        self.assertTrue(window.btn_export_key.isEnabled())

    def test_the_studio_recognises_a_host_key_mismatch(self):
        from tools.hmi_deployer.mainwindow import MainWindow
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), window.deleteLater(), self.app.processEvents()))
        window._host_key_mismatch = False
        window._record_transport_line("Host key verification failed.")
        self.assertTrue(window._host_key_mismatch)


if __name__ == "__main__":
    unittest.main()


class HostKeyTests(unittest.TestCase):
    """The bundle carries the panel's host key and import trusts it.

    Another user's known_hosts often already holds a key for the panel's
    DHCP address from a board that had it before; without this the link is
    refused with "Host key verification failed".
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.known = os.path.join(self.tmp, "known_hosts")
        self._original = deploy_key.known_hosts_path
        deploy_key.known_hosts_path = lambda: self.known
        self.addCleanup(lambda: setattr(deploy_key, "known_hosts_path", self._original))

    def test_import_replaces_a_stale_entry_with_the_bundled_key(self):
        key = _keypair(self.tmp)
        with open(self.known, "w", encoding="utf-8") as handle:
            handle.write("10.9.9.9 ssh-ed25519 AAAAstale\n10.9.9.8 ssh-ed25519 AAAAother\n")
        bundle = deploy_key.export_bundle(key, os.path.join(self.tmp, "b"), "10.9.9.9", port=22,
                                          host_keys=["10.9.9.9 ssh-ed25519 AAAAfresh"])
        info = deploy_key.import_bundle(bundle, install_dir=os.path.join(self.tmp, "i"))
        self.assertEqual(info["host_keys_installed"], 1)
        with open(self.known, encoding="utf-8") as handle:
            lines = [line.strip() for line in handle if line.strip()]
        self.assertIn("10.9.9.9 ssh-ed25519 AAAAfresh", lines)
        self.assertNotIn("10.9.9.9 ssh-ed25519 AAAAstale", lines)
        self.assertIn("10.9.9.8 ssh-ed25519 AAAAother", lines)   # other hosts untouched

    def test_a_bundle_without_host_keys_leaves_known_hosts_alone(self):
        key = _keypair(self.tmp)
        bundle = deploy_key.export_bundle(key, os.path.join(self.tmp, "b"), "10.9.9.9", host_keys=[])
        info = deploy_key.import_bundle(bundle, install_dir=os.path.join(self.tmp, "i"))
        self.assertEqual(info["host_keys_installed"], 0)
        self.assertFalse(os.path.exists(self.known))


class VerifyKeyTests(unittest.TestCase):
    """verify_key names the failure class a user can act on."""

    def _fake_ssh(self, stdout="", stderr="", returncode=255):
        class _Result:
            pass
        result = _Result()
        result.stdout, result.stderr, result.returncode = stdout, stderr, returncode
        original_run, original_which = deploy_key.subprocess.run, deploy_key.shutil.which
        deploy_key.subprocess.run = lambda *a, **k: result
        deploy_key.shutil.which = lambda name: "ssh"
        self.addCleanup(lambda: setattr(deploy_key.subprocess, "run", original_run))
        self.addCleanup(lambda: setattr(deploy_key.shutil, "which", original_which))

    def test_success_and_each_failure_class(self):
        cases = [
            ({"stdout": "HMI-KEY-OK\n", "returncode": 0}, "ok"),
            ({"stderr": "Host key verification failed."}, "host-key"),
            ({"stderr": "root@10.0.0.1: Permission denied (publickey)."}, "refused"),
            ({"stderr": "Permissions 0644 for 'k' are too open."}, "permissions"),
            ({"stderr": "ssh: connect to host 10.0.0.1 port 22: Connection timed out"}, "unreachable"),
            ({"stderr": "something else entirely"}, "unknown"),
        ]
        for kwargs, expected in cases:
            with self.subTest(expected=expected):
                self._fake_ssh(**kwargs)
                ok, reason = deploy_key.verify_key("k", "10.0.0.1")
                self.assertEqual(ok, expected == "ok")
                self.assertTrue(reason == "ok" if expected == "ok" else reason.startswith(expected + ":"), reason)

    def test_missing_ssh_client_is_named(self):
        original = deploy_key.shutil.which
        deploy_key.shutil.which = lambda name: None
        self.addCleanup(lambda: setattr(deploy_key.shutil, "which", original))
        ok, reason = deploy_key.verify_key("k", "10.0.0.1")
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("no-ssh:"))

