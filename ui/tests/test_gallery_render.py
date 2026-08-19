"""
ui/tests/test_gallery_render.py
Layer: Shared design system
Purpose: Unit tests for gallery.py, asserting offscreen rendering and correct background colours.
Implements CONTRACT section 7.1.
"""

import os
import sys
import unittest
import tempfile
import subprocess
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Use Qt from PySide6
from PySide6.QtGui import QImage, QColor, QGuiApplication

from ui.python.shadcn import color

class TestGalleryRender(unittest.TestCase):
    """
    Test suite for ui/gallery.py
    """
    
    @classmethod
    def setUpClass(cls) -> None:
        """
        Setup QGuiApplication needed for QImage if not exists.
        """
        cls.app = QGuiApplication.instance() or QGuiApplication(sys.argv)
        
    def run_gallery(self, theme: str, out_path: str) -> None:
        """
        Runs the gallery script offscreen and saves a screenshot.
        
        Args:
            theme: "light" or "dark"
            out_path: Path to save the PNG
        """
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        
        script = Path(__file__).parent.parent / "gallery.py"
        cmd = [
            sys.executable, str(script),
            "--theme", theme,
            "--screenshot", out_path,
            "--exit-after", "1500"
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        
        if result.returncode != 0:
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            
        self.assertEqual(result.returncode, 0, f"Gallery failed with code {result.returncode}. Stderr: {result.stderr}")
        self.assertTrue(os.path.exists(out_path), f"Screenshot not created at {out_path}")
        
        # Check stderr for QML warnings
        # Ignore font-related warnings as we are running headless and may not have the fonts
        warnings = [line for line in result.stderr.splitlines() if "file:///" in line or "qrc:/" in line or "Warning:" in line]
        if warnings:
            print("QML Warnings detected:")
            for w in warnings:
                print(w)
            # The prompt requires ZERO warnings
            self.assertEqual(len(warnings), 0, "QML warnings found during gallery render")

    def check_image(self, img_path: str, expected_bg_hex: str) -> None:
        """
        Loads the image, asserts it is not blank, and checks the top-left pixel
        matches the expected background colour.
        
        Args:
            img_path: Path to the PNG
            expected_bg_hex: Expected hex colour (e.g. '#ffffff')
        """
        img = QImage(img_path)
        self.assertFalse(img.isNull(), "Failed to load QImage")
        
        # Check that it's not a uniform image (i.e. not blank)
        top_left_pixel = img.pixelColor(0, 0)
        expected_color = QColor(expected_bg_hex)
        
        # Report pixel values
        print(f"Measured Top-Left Pixel: {top_left_pixel.name()}, Expected: {expected_color.name()}")
        
        self.assertEqual(
            top_left_pixel.name(), 
            expected_color.name(), 
            f"Background mismatch. Got {top_left_pixel.name()}, expected {expected_color.name()}"
        )
        
        # Sample another pixel in the center to ensure it's not totally uniform
        is_uniform = True
        for y in range(0, img.height(), 100):
            for x in range(0, img.width(), 100):
                if img.pixelColor(x, y).name() != top_left_pixel.name():
                    is_uniform = False
                    break
            if not is_uniform:
                break
                
        self.assertFalse(is_uniform, "Image is completely uniform (blank)")
        
    def test_gallery_light_theme(self) -> None:
        """
        Test rendering the gallery in light theme.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "light.png")
            self.run_gallery("light", out_path)
            expected_bg = color("background", "light")
            self.check_image(out_path, expected_bg)
            
    def test_gallery_dark_theme(self) -> None:
        """
        Test rendering the gallery in dark theme.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "dark.png")
            self.run_gallery("dark", out_path)
            expected_bg = color("background", "dark")
            self.check_image(out_path, expected_bg)

if __name__ == "__main__":
    unittest.main(verbosity=2)
