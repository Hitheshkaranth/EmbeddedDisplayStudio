"""The Connect button reports the state of the link, not just its purpose.

The button read "Connect" while an attempt was in flight, after one had
succeeded, and after one had timed out. Connecting to a panel that is not
answering takes the full SSH timeout to fail, so for that whole minute the
only sign anything was happening was a line in the console -- and the button
stayed live, so pressing it again queued a second attempt behind the first.

The display readout had the matching fault: it kept whatever geometry the last
successful probe reported, so a failed connection to a different board showed
that board's resolution as though it were current.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from tools.hmi_deployer.mainwindow import MainWindow
from ui.python.shadcn import qss


class ConnectButtonStates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _studio(self):
        """A MainWindow with only the parts _set_link_state touches."""
        studio = MainWindow.__new__(MainWindow)
        studio.btn_test = QPushButton("Connect")
        # The real one renders a themed pixmap; the icon is not what is asserted.
        studio._themed_icon = lambda *_a, **_k: None
        return studio

    def test_an_attempt_in_flight_says_so_and_cannot_be_pressed_again(self):
        studio = self._studio()

        MainWindow._set_link_state(studio, "connecting")

        self.assertEqual(studio.btn_test.text(), "Connecting...")
        self.assertFalse(
            studio.btn_test.isEnabled(),
            "a second attempt could be queued behind the first",
        )
        self.assertEqual(studio.btn_test.property("linkState"), "connecting")

    def test_an_established_link_says_connected_and_stays_pressable(self):
        studio = self._studio()

        MainWindow._set_link_state(studio, "connected")

        self.assertEqual(studio.btn_test.text(), "Connected")
        self.assertTrue(studio.btn_test.isEnabled())
        self.assertEqual(studio.btn_test.property("linkState"), "connected")

    def test_a_failed_attempt_offers_the_retry_rather_than_the_first_try(self):
        studio = self._studio()

        MainWindow._set_link_state(studio, "fault")

        self.assertEqual(studio.btn_test.text(), "Reconnect")
        self.assertTrue(studio.btn_test.isEnabled())
        self.assertEqual(studio.btn_test.property("linkState"), "fault")

    def test_an_unknown_state_falls_back_to_idle(self):
        """Never leave the button describing the attempt before last."""
        studio = self._studio()
        MainWindow._set_link_state(studio, "connected")

        MainWindow._set_link_state(studio, "nonsense")

        self.assertEqual(studio.btn_test.text(), "Connect")
        self.assertTrue(studio.btn_test.isEnabled())

    def test_every_state_the_button_can_hold_is_styled(self):
        """A renamed property would drop the colour without failing anything.

        The states are only visible because the stylesheet colours them, and
        nothing else would notice if a rule went missing.
        """
        for theme in ("dark", "light"):
            sheet = qss(theme)
            for state in ("connecting", "connected", "fault"):
                with self.subTest(theme=theme, state=state):
                    self.assertIn(
                        f'QPushButton#connectButton[linkState="{state}"]', sheet
                    )


if __name__ == "__main__":
    unittest.main()
