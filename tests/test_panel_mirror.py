"""The panel mirror rides out the runtime's restart after a deploy.

tools/hmi_deployer/panel_mirror.py: a miss is retried on the next tick; only
MAX_MISSES in a row stop the mirror, with one `failed`.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tools.hmi_deployer.panel_mirror import PanelMirror  # noqa: E402


class MirrorRetryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.mirror = PanelMirror()
        self.failures, self.frames = [], []
        self.mirror.failed.connect(self.failures.append)
        self.mirror.frame.connect(self.frames.append)
        # Running, without a worker reaching for a real panel.
        self.mirror._conn = ("panel", "root", 22, "")
        self.mirror._timer.start()
        self.addCleanup(self.mirror._timer.stop)

    def test_a_few_misses_after_a_deploy_do_not_stop_it(self):
        for _ in range(PanelMirror.MAX_MISSES - 1):
            self.mirror._on_failed("hmi-ui is not running")
        self.assertTrue(self.mirror.is_running())
        self.assertEqual(self.failures, [])

    def test_a_frame_resets_the_count(self):
        for _ in range(PanelMirror.MAX_MISSES - 1):
            self.mirror._on_failed("restarting")
        self.mirror._on_frame(QImage(4, 4, QImage.Format_RGB32))
        for _ in range(PanelMirror.MAX_MISSES - 1):
            self.mirror._on_failed("restarting")
        self.assertTrue(self.mirror.is_running())
        self.assertEqual(len(self.frames), 1)

    def test_a_panel_that_stays_away_stops_it_once(self):
        for _ in range(PanelMirror.MAX_MISSES):
            self.mirror._on_failed("hmi-ui is not running")
        self.assertFalse(self.mirror.is_running())
        self.assertEqual(self.failures, ["hmi-ui is not running"])


if __name__ == "__main__":
    unittest.main()
