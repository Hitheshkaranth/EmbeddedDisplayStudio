"""Wave 5 B4 gate -- finding, watching and provisioning the panel.

* discover(): the Studio's "Find panels" broadcasts and lists the hellos
  hmi-hwd answers with (CONTRACT 14, discovery);
* LinkWatch: a dropped link is noticed, shown, and recovered from;
* the panel's clock can be set from the Studio;
* the C daemon ships to the panel and the launcher prefers it, with the
  Python daemon as the fallback.
FROZEN (skeleton).
"""
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


class Discovery(unittest.TestCase):
    def test_hellos_are_collected_with_the_sender_address(self):
        from tools.hmi_deployer.discovery import discover
        panel = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        panel.bind(("127.0.0.1", 0))
        panel.settimeout(3.0)
        self.addCleanup(panel.close)
        port = panel.getsockname()[1]

        def answer():
            try:
                data, addr = panel.recvfrom(4096)
                if json.loads(data).get("cmd") == "discover":
                    panel.sendto(json.dumps({"t": "hello", "host": "verdin-1", "model": "Toradex Verdin iMX8M Plus",
                                             "hwd": "0.2.0", "cmd_port": 5000, "tags": 41}).encode(), addr)
            except OSError:
                pass

        threading.Thread(target=answer, daemon=True).start()
        found = discover(timeout=1.0, port=port, targets=["127.0.0.1"])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ip"], "127.0.0.1")
        self.assertEqual(found[0]["host"], "verdin-1")
        self.assertEqual(discover(timeout=0.3, port=port, targets=["127.0.0.1"]), [])

    def test_a_broadcast_target_list_covers_every_interface(self):
        from tools.hmi_deployer.discovery import broadcast_targets
        targets = broadcast_targets()
        self.assertIn("255.255.255.255", targets)


class LinkWatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_down_then_up(self):
        from tools.hmi_deployer.link_watch import LinkWatch
        up = [True]
        watch = LinkWatch(probe=lambda host, port: up[0])
        events = []
        watch.linkDown.connect(lambda: events.append("down"))
        watch.linkUp.connect(lambda: events.append("up"))
        watch.start("172.16.20.71")
        watch.check_now()
        self.assertEqual(events, [])                           # up, and nothing changed
        up[0] = False
        watch.check_now()
        watch.check_now()
        self.assertEqual(events, ["down"])                     # once, not every probe
        self.assertFalse(watch.is_up())
        up[0] = True
        watch.check_now()
        self.assertEqual(events, ["down", "up"])
        watch.stop()
        up[0] = False
        watch.check_now()
        self.assertEqual(events, ["down", "up"])               # stopped: silent


class ClockSync(unittest.TestCase):
    def test_the_command_sets_utc_and_the_rtc(self):
        from tools.hmi_deployer.ssh import clock_sync_command
        cmd = clock_sync_command(1791450632.7)
        self.assertIn("date -u -s @1791450632", cmd)
        self.assertIn("hwclock -w", cmd)


class NativeDaemonShips(unittest.TestCase):
    def test_provisioning_ships_the_c_daemon(self):
        sys.path.insert(0, os.path.join(ROOT, "deploy"))
        import provision_panel
        self.assertIn(("native/hmi-hwd/out/aarch64/hmi-hwd", "usr/bin/hmi-hwd-native"),
                      provision_panel.FILE_PAYLOAD)
        self.assertIn("native/hmi-hwd/out/aarch64/hmi-hwd", provision_panel.BINARY_SOURCES)

    @unittest.skipUnless(os.name == "posix", "runs the launcher with sh")
    def test_the_launcher_prefers_the_native_daemon(self):
        launcher = os.path.join(ROOT, "target", "bin", "hmi-hwd-launch")
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "usr", "bin"))
            os.makedirs(os.path.join(root, "etc", "hmi"))
            native = os.path.join(root, "usr", "bin", "hmi-hwd-native")
            with open(native, "w") as fh:
                fh.write("#!/bin/sh\necho native \"$@\"\n")
            os.chmod(native, os.stat(native).st_mode | stat.S_IEXEC)
            env = dict(os.environ, HMI_ROOT=root)
            out = subprocess.run(["sh", launcher, "--sim"], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("native", out.stdout)
            self.assertIn("--sim", out.stdout)
            env["HMI_HWD_PYTHON_ONLY"] = "1"                  # the fallback switch
            out = subprocess.run(["sh", launcher, "--sim"], env=env, capture_output=True, text=True, timeout=10)
            self.assertNotIn("native", out.stdout)


if __name__ == "__main__":
    unittest.main()
