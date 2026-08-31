"""The designer and the Display Console both follow the connected panel.

The Studio probes the SOM's DRM connector on Connect and gets its real pixel
geometry back. Before this, only the preview acted on it: the designer kept
drawing against the manifest's guess, so an author laid widgets out on a
canvas the size of a screen that was not plugged in, and only discovered the
mismatch after a deploy.
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from designer.ui import DesignerWorkspace
from tools.hmi_deployer.mainwindow import MainWindow, parse_display_resolution


class DesignerFollowsTheDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _workspace(self):
        workspace = DesignerWorkspace()
        self.addCleanup(workspace.close)
        return workspace

    def test_canvas_takes_the_detected_geometry(self):
        workspace = self._workspace()
        messages = []
        workspace.message.connect(messages.append)

        self.assertTrue(workspace.apply_target_resolution(1920, 1080))

        self.assertEqual(workspace.project.screen.width, 1920)
        self.assertEqual(workspace.project.screen.height, 1080)
        self.assertEqual(workspace.screen_width.value(), 1920)
        self.assertEqual(workspace.screen_height.value(), 1080)
        self.assertTrue(any("1920 x 1080" in m for m in messages), messages)

    def test_widgets_keep_their_coordinates(self):
        """Retargeting moves the design surface, never the design."""
        workspace = self._workspace()
        workspace.add_widget("Rectangle", 40, 60)
        model = workspace.current_page.widgets[0]
        before = dict(model.geometry)

        workspace.apply_target_resolution(1920, 1080)

        self.assertEqual(workspace.current_page.widgets[0].geometry, before)

    def test_the_same_geometry_is_a_no_op(self):
        workspace = self._workspace()
        workspace.apply_target_resolution(1024, 600)
        self.assertFalse(workspace.apply_target_resolution(1024, 600))

    def test_nonsense_geometry_is_refused(self):
        workspace = self._workspace()
        width, height = workspace.project.screen.width, workspace.project.screen.height
        for bad in ((0, 600), (1024, 0), (-1, -1)):
            with self.subTest(geometry=bad):
                self.assertFalse(workspace.apply_target_resolution(*bad))
        self.assertEqual((workspace.project.screen.width, workspace.project.screen.height),
                         (width, height))


class StudioPushesTheDetectedGeometryTests(unittest.TestCase):
    """_record_detected_resolution is driven by a line of remote SSH output."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class _Combo:
        def __init__(self): self.index, self.texts = 0, {}
        def setItemText(self, i, text): self.texts[i] = text
        def setCurrentIndex(self, i): self.index = i

    class _Label:
        def __init__(self): self.text = ""
        def setText(self, text): self.text = text

    class _Designer:
        def __init__(self): self.applied = []
        def apply_target_resolution(self, w, h): self.applied.append((w, h)); return True

    def _studio(self):
        studio = MainWindow.__new__(MainWindow)
        studio.detected_resolution = None
        studio._detected_panel_index = 5
        studio.cmb_panel = self._Combo()
        studio.lbl_target_resolution = self._Label()
        studio.designer_workspace = self._Designer()
        studio.applied_sizes = []
        studio.on_panel_size_changed = lambda index: studio.applied_sizes.append(index)
        studio.log = lambda *_a, **_k: None
        return studio

    def test_a_detected_marker_reaches_preview_and_designer(self):
        studio = self._studio()

        MainWindow._record_detected_resolution(studio, "HMI_DISPLAY=1920x1080")

        self.assertEqual(studio.detected_resolution, (1920, 1080))
        self.assertEqual(studio.designer_workspace.applied, [(1920, 1080)])
        self.assertEqual(studio.applied_sizes, [5])
        self.assertEqual(studio.lbl_target_resolution.text, "1920 x 1080 px")

    def test_reconnecting_to_a_different_panel_still_retargets(self):
        """setCurrentIndex is silent when the row is already current."""
        studio = self._studio()

        MainWindow._record_detected_resolution(studio, "HMI_DISPLAY=1280x800")
        MainWindow._record_detected_resolution(studio, "HMI_DISPLAY=1024x600")

        self.assertEqual(studio.detected_resolution, (1024, 600))
        self.assertEqual(studio.designer_workspace.applied, [(1280, 800), (1024, 600)])
        # Applied both times, not just on the first, when the row did change.
        self.assertEqual(studio.applied_sizes, [5, 5])

    def test_ordinary_console_output_is_ignored(self):
        studio = self._studio()

        MainWindow._record_detected_resolution(studio, "Setting up hmi-gui...")

        self.assertIsNone(studio.detected_resolution)
        self.assertEqual(studio.designer_workspace.applied, [])

    def test_marker_parsing_rejects_impossible_geometry(self):
        self.assertIsNone(parse_display_resolution("HMI_DISPLAY=0x600"))
        self.assertIsNone(parse_display_resolution("HMI_DISPLAY=abcxdef"))
        self.assertEqual(parse_display_resolution("HMI_DISPLAY=1920x1080"), (1920, 1080))


if __name__ == "__main__":
    unittest.main()
