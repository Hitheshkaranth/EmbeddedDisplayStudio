"""
tools/hmi_deployer/app.py
Layer: 3 (Host Deployer)
Purpose: Entry point, argparse, theme bootstrap.
"""
import sys
import argparse
import logging
import os

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .mainwindow import MainWindow

# The product mark, shipped with the tool rather than fetched, so the app has
# its identity with no network and no install step. 512 px master; Qt scales it
# down for window, taskbar and dialog use.
LOGO_PATH = os.path.join(os.path.dirname(__file__), "resources", "logo.png")

def main():
    parser = argparse.ArgumentParser(
        description="EmbeddedDisplay Studio - BYOA HMI deployment tool"
    )
    parser.add_argument("--bundle", type=str, help="Path to initial app bundle")
    parser.add_argument("--exit-after", type=int, default=0, help="Exit after N ms")
    parser.add_argument("--capture-bezel", type=str, help="Grab bezel to png")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    app = QApplication(sys.argv)

    # Needs to be set for Settings
    app.setOrganizationName("MIL-HMI")
    app.setApplicationName("EmbeddedDisplay Studio")

    # Application identity. Set on the QApplication so every window, dialog and
    # the OS taskbar entry inherit it; the 512 px master is what Qt downsamples
    # from for whichever size the platform asks for.
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    
    window = MainWindow(exit_after_ms=args.exit_after)
    
    if args.bundle:
        import os
        bundle_abs = os.path.abspath(args.bundle)
        if os.path.isdir(bundle_abs):
            window.load_bundle(bundle_abs)
        
    window.show()
    
    if args.capture_bezel:
        def grab():
            window.device_panel.grab().save(args.capture_bezel)
            if args.exit_after > 0:
                app.quit()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(max(100, args.exit_after - 1000), grab)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
