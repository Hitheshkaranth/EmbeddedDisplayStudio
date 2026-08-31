"""
tools/hmi_deployer/app.py
Layer: 3 (Host Deployer)
Purpose: Entry point, argparse, theme bootstrap.
"""
import sys
import argparse
import logging
import logging.handlers
import os

from PySide6.QtCore import Qt, QElapsedTimer, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QSplashScreen

from .mainwindow import MainWindow

# The product mark, shipped with the tool rather than fetched, so the app has
# its identity with no network and no install step. 512 px master; Qt scales it
# down for window, taskbar and dialog use.
LOGO_PATH = os.path.join(os.path.dirname(__file__), "resources", "logo.png")

# Shown while the window is built. Starting up is not instant -- the settings
# load, the last bundle is validated and its preview process is started -- and
# several seconds of nothing on screen after a double-click reads as a launch
# that failed.
SPLASH_PATH = os.path.join(os.path.dirname(__file__), "resources", "splash.png")
SPLASH_HOLD_MS = 5_000

# Where the Studio keeps its own record.
#
# Everything it says went to stderr, which exists only if something happened
# to be capturing it -- so a crash during ordinary use left nothing behind at
# all, and the only trace of one was an exception code in the Windows event
# log naming Qt rather than anything the tool was doing. A file the user can
# attach to a bug report is worth more than any amount of guessing from it.
LOG_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA")
    or os.environ.get("XDG_STATE_HOME")
    or os.path.expanduser("~/.local/state"),
    "EmbeddedDisplayStudio", "logs",
)

#: Kept small: this is for reading the tail after something went wrong, not
#: for archiving. Five files of a megabyte covers days of ordinary use.
LOG_BYTES = 1_000_000
LOG_BACKUPS = 4


def _install_log_file():
    """Add a rotating file to the root logger; return its path or "".

    Never raises. A read-only or missing application-data directory is a
    reason to run without a log, not a reason to refuse to start.
    """
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "studio.log")
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logging.getLogger().addHandler(handler)
        return path
    except OSError:
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="EmbeddedDisplay Studio - BYOA HMI deployment tool"
    )
    parser.add_argument("--bundle", type=str, help="Path to initial app bundle")
    parser.add_argument("--exit-after", type=int, default=0, help="Exit after N ms")
    parser.add_argument("--capture-bezel", type=str, help="Grab bezel to png")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    log_path = _install_log_file()
    if log_path:
        # First line in the file names the build and the target, because a
        # log that does not say which version produced it answers half a
        # question.
        from .mainwindow import APP_VERSION
        logging.getLogger("EmbeddedDisplay Studio").info(
            "Studio %s starting; log at %s", APP_VERSION, log_path
        )

    app = QApplication(sys.argv)

    # In headless release smoke runs, closing the splash can briefly leave Qt
    # with no visible top-level window even though show_studio() has just shown
    # one. The default quit-on-last-window policy then ends the event loop long
    # before the delayed bezel capture. A capture run has its own explicit
    # quit path (and MainWindow's --exit-after safety timer), so it must not be
    # governed by that transient window count.
    if args.capture_bezel:
        app.setQuitOnLastWindowClosed(False)

    # Needs to be set for Settings
    app.setOrganizationName("MIL-HMI")
    app.setApplicationName("EmbeddedDisplay Studio")

    # Application identity. Set on the QApplication so every window, dialog and
    # the OS taskbar entry inherit it; the 512 px master is what Qt downsamples
    # from for whichever size the platform asks for.
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    
    splash = None
    splash_progress = None
    splash_status = None
    pixmap = QPixmap(str(SPLASH_PATH))
    if not pixmap.isNull():
        # The original artwork was composed for a much larger launch window.
        # Keep its proportions but present it at half scale in Studio.
        pixmap = pixmap.scaled(
            max(1, pixmap.width() // 2),
            max(1, pixmap.height() // 2),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        splash = QSplashScreen(pixmap)
        # PDB-4000-style launch feedback: a thin dark track with a blue
        # gradient, plus an explicit 0--100% status line.
        progress_margin = max(24, pixmap.width() // 14)
        progress_y = pixmap.height() - max(28, pixmap.height() // 10)
        splash_progress = QProgressBar(splash)
        splash_progress.setRange(0, 100)
        splash_progress.setValue(0)
        splash_progress.setTextVisible(False)
        splash_progress.setGeometry(
            progress_margin, progress_y,
            pixmap.width() - 2 * progress_margin, 12,
        )
        splash_progress.setStyleSheet("""
            QProgressBar {
                background: #09090b;
                border: 1px solid #3f3f46;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #006fee, stop:1 #38bdf8);
                border-radius: 5px;
            }
        """)
        splash_status = QLabel("Loading 0%", splash)
        splash_status.setGeometry(
            progress_margin, progress_y - 22,
            pixmap.width() - 2 * progress_margin, 18,
        )
        splash_status.setAlignment(Qt.AlignCenter)
        splash_status.setStyleSheet(
            "color: #ecedee; background: transparent; font-size: 10px; font-weight: 700;"
        )
        splash.showMessage(
            "Starting…",
            Qt.AlignBottom | Qt.AlignHCenter,
            QColor("#f8fafc"),
        )
        splash.clearMessage()
        splash.show()
        # The window is built on this thread, so the splash only ever paints if
        # it is given the chance before that starts.
        app.processEvents()

    window = MainWindow(exit_after_ms=args.exit_after)
    
    if args.bundle:
        import os
        bundle_abs = os.path.abspath(args.bundle)
        if os.path.isdir(bundle_abs):
            window.load_bundle(bundle_abs)
        
    def grab():
        if args.capture_bezel:
            window.device_panel.grab().save(args.capture_bezel)
            if args.exit_after > 0:
                app.quit()

    # Scheduled from the same moment as the window's own exit timer, which
    # MainWindow starts on construction.
    #
    # This used to be scheduled inside show_studio, which does not run until
    # the splash has finished -- so the grab landed at exit_after + splash
    # while the close fired at exit_after, and the window was always gone four
    # seconds before the capture. --capture-bezel could not produce a file at
    # all when a splash was shown, which is every ordinary run.
    if args.capture_bezel and args.exit_after > 0:
        QTimer.singleShot(max(100, args.exit_after - 1000), grab)

    def show_studio():
        window.show()
        if splash is not None:
            splash.finish(window)
        if args.capture_bezel and args.exit_after <= 0:
            # No deadline to race: grab shortly after the window is up.
            QTimer.singleShot(1000, grab)

    if splash is None:
        QTimer.singleShot(0, show_studio)
    else:
        # The window is shown only after the splash reaches 100%, not merely
        # after a fixed delay in the background.
        splash_clock = QElapsedTimer()
        splash_clock.start()

        def advance_splash_progress():
            elapsed = splash_clock.elapsed()
            percent = min(100, round(elapsed * 100 / SPLASH_HOLD_MS))
            splash_progress.setValue(percent)
            splash_status.setText(f"Loading {percent}%")
            if percent < 100:
                QTimer.singleShot(40, advance_splash_progress)
            else:
                QTimer.singleShot(80, show_studio)

        QTimer.singleShot(0, advance_splash_progress)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
