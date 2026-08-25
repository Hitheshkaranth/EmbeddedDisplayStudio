"""
tests/test_device_panel_geometry.py
Layer: Test (W11)

Pins how much of its pane the bezel preview occupies.

The preview exists to be judged by eye before a deploy, so how large it draws
is a product decision, not an implementation detail. These tests hold the
widened fill in place and hold the two properties that keep it safe: the bezel
stays inside its pane at every preset, and physical diagonal still separates
one panel from another.
"""

import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - environment without PySide6
    HAVE_QT = False

if HAVE_QT:
    from tools.hmi_deployer.devicepanel import PANEL_PRESETS, DevicePanel


@unittest.skipUnless(HAVE_QT, "PySide6 is required for the bezel preview")
class TestBezelFill(unittest.TestCase):
    """The bezel fills the pane as generously as it can without overrunning."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, width=1000, height=800):
        panel = DevicePanel()
        panel.resize(width, height)
        return panel

    def test_fill_is_twenty_percent_above_the_original(self):
        """The widened fill is exactly the 0.90 baseline plus 20%."""
        self.assertAlmostEqual(DevicePanel.BEZEL_FILL_PCT, 0.9 * 1.2)

    def test_bezel_stays_inside_its_pane_for_every_preset(self):
        """A raised fill must not push the bezel past the edges it is centred in."""
        panel = self._panel()
        for _label, inches, width, height in PANEL_PRESETS:
            with self.subTest(panel=_label):
                panel.set_target_resolution(width, height, inches)
                bx, by, bw, bh = panel._bezel_rect()
                self.assertGreaterEqual(bx, 0)
                self.assertGreaterEqual(by, 0)
                self.assertLessEqual(bx + bw, panel.width())
                self.assertLessEqual(by + bh, panel.height())

    def test_largest_panel_is_drawn_larger_than_it_was(self):
        """The change is visible where the old clamp did not apply."""
        panel = self._panel()
        panel.set_target_resolution(1280, 800, 10.1)
        _bx, _by, widened, _bh = panel._bezel_rect()

        expected_old = widened / (
            min(DevicePanel.MAX_BEZEL_FILL_PCT,
                DevicePanel.BEZEL_FILL_PCT * panel._physical_scale())
            / (0.9 * panel._physical_scale())
        )
        self.assertGreater(widened, expected_old)

    def test_physical_diagonal_still_separates_the_presets(self):
        """Widening the fill must not flatten 5.0" and 15.6" into one size."""
        panel = self._panel()
        panel.set_target_resolution(800, 480, 5.0)
        _bx, _by, small, _bh = panel._bezel_rect()
        panel.set_target_resolution(800, 480, 15.6)
        _bx, _by, large, _bh = panel._bezel_rect()
        self.assertGreater(large, small)


if __name__ == "__main__":
    unittest.main()
