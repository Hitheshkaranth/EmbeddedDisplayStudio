"""
tests/native/test_conformance_tags.py
Black-box conformance test — tag map behaviour through the probe.
"""
import os
import time
import unittest

from .loader_harness import LoaderHarness


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "probe-app")


class TestConformanceTags(unittest.TestCase):
    def setUp(self):
        self.h = LoaderHarness(apps_dir=FIXTURES, exit_after_ms=15000)
        self.h.start()
        self.h.wait_for(r"PROBE ready", timeout=20)
        self.addCleanup(self.h.stop)

    def test_tags_update_and_alias(self):
        """frame {ai.pot=1.5, di.estop=false} → both spellings logged."""
        self.h.frame({"ai.pot": 1.5, "di.estop": False})
        time.sleep(0.5)
        pl = self.h.probe_lines()
        # Check each probe line individually (they accumulate, we search)
        text = "\n".join(pl)
        self.assertIn("ai.pot=1.5", text)
        self.assertIn("ai_pot=1.5", text)
        self.assertIn("Tags.ai_pot=1.5", text)
        self.assertIn("di.estop=false", text)
        self.assertIn("online=true", text)

    def test_no_duplicate_for_identical_frame(self):
        """An identical second frame produces no new ai.pot= line within 1 s."""
        self.h.frame({"ai.pot": 1.5})
        time.sleep(0.5)
        before = len([l for l in self.h.probe_lines() if "ai.pot=1.5" in l])
        self.h.frame({"ai.pot": 1.5})  # identical
        time.sleep(1)
        after = len([l for l in self.h.probe_lines() if "ai.pot=1.5" in l])
        self.assertEqual(after, before, "Identical frame produced new ai.pot= line")

    def test_null_tag_uses_fallback(self):
        """{ai.pot: null} → ai.pot=-1 (fallback), not null."""
        self.h.frame({"ai.pot": None})
        time.sleep(0.5)
        pl = self.h.probe_lines()
        text = "\n".join(pl)
        self.assertIn("ai.pot=-1", text)
        self.assertIn("ai_pot=-1", text)

    def test_undeclared_tag_drives_control(self):
        """An undeclared tag (ctl.ping) triggers the Bus.ping() control."""
        self.h.frame({"ctl.ping": 1})
        cmd = self.h.wait_command("ping", timeout=3)
        self.assertEqual(cmd["id"], "qml-ping")

    def test_online_falls_offline(self):
        """No frames for 4 s after one frame → online=false."""
        self.h.frame({"ai.pot": 1.5})
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("online=true", text)
        # Wait for watchdog (2500 ms) plus margin
        time.sleep(4)
        text2 = "\n".join(self.h.probe_lines())
        self.assertIn("online=false", text2)

    def test_garbage_frames(self):
        """9000-byte garbage, JSON array, unknown 't' → still processes good frame."""
        import socket as _sock

        # Send 9000 bytes of 'x'
        self.h._daemon.sendto(b"x" * 9000, ("127.0.0.1", self.h._rx_port))
        time.sleep(0.1)

        # Send JSON array
        self.h._daemon.sendto(b"[1,2]", ("127.0.0.1", self.h._rx_port))
        time.sleep(0.1)

        # Send unknown 't'
        self.h.frame({"t": "nope"})
        time.sleep(0.1)

        # Now send a good frame
        self.h.frame({"ai.pot": 2.5})
        time.sleep(0.5)
        text = "\n".join(self.h.probe_lines())
        self.assertIn("ai.pot=2.5", text, "Good frame not processed after garbage")


if __name__ == "__main__":
    unittest.main()