"""
tools/hmi_deployer/mainwindow.py
Layer: 3 (Host Deployer)
Purpose: Main application window, layout, actions, and state machine.
"""
import os
import json
import time
import re
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QSplitter, QGroupBox, QFormLayout, QLineEdit, QProgressBar,
    QPlainTextEdit, QFileDialog, QMessageBox, QTabWidget, QLabel, QFrame,
    QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QSettings, QTimer, QSize
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from .devicepanel import DevicePanel, PANEL_PRESETS
from .deployer import (
    DependencyWorker, PackageWorker, validate_bundle, detect_bundle,
    detect_qt_binding, write_manifest,
)
from .telemetry import TelemetrySimulator, TelemetryRelay
from .ssh import (
    LOG_UNITS, SshWorker, UploadWorker, build_activate_command,
    build_dep_check_command, build_dep_install_command, build_logs_command,
    build_release_list_command, build_ssh_cmd, build_upload_cmd,
    parse_release_line,
)
from .scaffold import create_bundle
from .taglab import TagLabSender

try:
    from ui.python.shadcn import apply, icon, qml_import_path
except ImportError:
    # Dummy mock if not running correctly
    def apply(app, theme): pass
    def icon(name, size=18, color=None): from PySide6.QtGui import QIcon; return QIcon()
    def qml_import_path(): return ""

# Product version, shown hard right in the footer. Single source of truth.
APP_VERSION = "0.0.4"

# Exact, machine-readable marker emitted by DISPLAY_PROBE_COMMAND over SSH.
DISPLAY_RESOLUTION_RE = re.compile(r"^HMI_DISPLAY=(\d{1,5})x(\d{1,5})$")

# Prefer the connected DRM mode. Some embedded BSPs expose only a framebuffer,
# so virtual_size is kept as a fallback. The final ':' makes an unavailable
# display probe non-fatal to Connect / Test.
DISPLAY_PROBE_COMMAND = (
    "for connector in /sys/class/drm/card*-*; do "
    "if [ -f \"$connector/status\" ] && "
    "[ \"$(cat \"$connector/status\")\" = connected ] && "
    "[ -s \"$connector/modes\" ]; then "
    "mode=\"$(head -n 1 \"$connector/modes\")\"; "
    "echo \"HMI_DISPLAY=$mode\"; exit 0; fi; done; "
    "if [ -r /sys/class/graphics/fb0/virtual_size ]; then "
    "size=\"$(tr ',' 'x' < /sys/class/graphics/fb0/virtual_size)\"; "
    "echo \"HMI_DISPLAY=$size\"; fi; :"
)

# Profile records are deliberately line-oriented so the existing SSH worker can
# stream them into the UI without a second protocol or a temporary remote file.
MEMORY_PROFILE_PREFIX = "HMI_PROFILE_"

# Shown in place of a measurement the SOM has not reported yet.
PROFILE_PENDING_TEXT = "Measuring…"

# Opening height of the Studio window, in device-independent pixels. The window
# is a preview pane beside a tool pane and both are tall: the panel bezel plus
# its caption on one side, three stacked cards on the other.
DEFAULT_WINDOW_HEIGHT = 1000

# All size values except COMPRESSED_BYTES are KiB. The compressed measurement
# is streamed through tar|wc rather than written to /tmp, preserving the
# installer's tmpfs-space guarantee even for a large application.
#
# Field order is load-bearing. Recompressing the active release is the one
# expensive step here -- three minutes for a 300 MiB bundle -- and it used to
# sit in the middle, which meant storage, filesystem and RAM were all held
# behind it. The panel showed three fields and zeroes for everything else until
# the tar finished, which reads as a refresh that did not refresh. Every cheap
# field is now emitted first and streams in immediately; only the compressed
# figure waits, and it announces itself through STAGE while it works.
MEMORY_PROFILE_COMMAND = (
    "current=$(readlink -f /opt/hmi_apps/current 2>/dev/null || true); "
    "if [ -n \"$current\" ] && [ -d \"$current\" ]; then "
    "echo \"HMI_PROFILE_RELEASE=${current##*/}\"; "
    "echo \"HMI_PROFILE_DEPLOY_PATH=$current\"; "
    "app_kb=$(du -sk \"$current\" 2>/dev/null | awk '{print $1}'); "
    "echo \"HMI_PROFILE_APP_KB=${app_kb:-0}\"; "
    "else echo \"HMI_PROFILE_RELEASE=No active deployment\"; "
    "echo \"HMI_PROFILE_DEPLOY_PATH=/opt/hmi_apps/current\"; "
    "echo \"HMI_PROFILE_APP_KB=0\"; fi; "
    "releases_kb=$(du -sk /opt/hmi_apps/releases 2>/dev/null | awk '{print $1}'); "
    "echo \"HMI_PROFILE_RELEASES_KB=${releases_kb:-0}\"; "
    "set -- $(df -kP / 2>/dev/null | awk 'NR == 2 {print $2, $3, $4}'); "
    "echo \"HMI_PROFILE_ROOT_KB=${1:-0}\"; "
    "echo \"HMI_PROFILE_USED_KB=${2:-0}\"; "
    "echo \"HMI_PROFILE_FREE_KB=${3:-0}\"; "
    "ram_kb=$(awk '/MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null); "
    "echo \"HMI_PROFILE_RAM_AVAILABLE_KB=${ram_kb:-0}\"; "
    "if [ -n \"$current\" ] && [ -d \"$current\" ]; then "
    "echo \"HMI_PROFILE_STAGE=Calculating compressed package size…\"; "
    "compressed_bytes=$(tar -C \"$current\" -czf - . 2>/dev/null | wc -c); "
    "echo \"HMI_PROFILE_COMPRESSED_BYTES=${compressed_bytes:-0}\"; "
    "else echo \"HMI_PROFILE_COMPRESSED_BYTES=0\"; fi; :"
)


def parse_display_resolution(line: str):
    """Parse a resolution marker emitted by the remote SOM.

    Args:
        line: One line of combined SSH stdout/stderr.

    Returns:
        A ``(width, height)`` pixel tuple for a valid marker, otherwise None.
    """
    match = DISPLAY_RESOLUTION_RE.fullmatch(line.strip())
    if match is None:
        return None
    width, height = (int(value) for value in match.groups())
    return (width, height) if width > 0 and height > 0 else None


def parse_memory_profile_line(line: str):
    """Parse one machine-readable memory-profile field from SSH output.

    Args:
        line: One line of remote stdout/stderr.

    Returns:
        A ``(field, value)`` tuple without the profile prefix, or None when
        the line is ordinary console output.
    """
    line = line.strip()
    if not line.startswith(MEMORY_PROFILE_PREFIX):
        return None
    field, separator, value = line[len(MEMORY_PROFILE_PREFIX):].partition("=")
    return (field, value) if separator and field else None


def format_kib(value):
    """Format a non-negative KiB value for a compact status label."""
    value = max(0, int(value))
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.2f} GiB"
    if value >= 1024:
        return f"{value / 1024:.1f} MiB"
    return f"{value} KiB"


def format_bytes(value):
    """Format a non-negative byte count for a compact status label."""
    value = max(0, int(value))
    if value >= 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024 * 1024):.2f} GiB"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"

# ---- SSH step budgets -------------------------------------------------------
# One timeout cannot serve every step of a deploy: the commands differ in cost
# by three orders of magnitude. Each is a watchdog, not an expectation.

# Commands that answer immediately (mkdir, a checksum file, rollback, restart).
SSH_SHORT_TIMEOUT_S = 30

# A connection survey invokes systemd and hmi-install status on the SOM. Those
# are normally quick, but a busy target may need longer than a filesystem mkdir.
SSH_TEST_TIMEOUT_S = 60

# Recompressing a release is streamed on the SOM and is intentionally allowed
# more time than a simple SSH status operation. A 314 MiB release measured at
# 179s against the previous 180s budget -- close enough to the watchdog that an
# ordinary bundle would be cut off mid-measurement and report a failure that
# was really a deadline.
MEMORY_PROFILE_TIMEOUT_S = 420

# A journal follow has no natural end: it runs until the user stops it or
# the panel goes away. The watchdog is a backstop against a session that has
# silently died, not an expectation of how long anyone watches logs.
LOG_FOLLOW_TIMEOUT_S = 24 * 60 * 60

# How much journal history to fetch before following.
LOG_HISTORY_LINES = 200

# Lines kept in memory. A panel that logs steadily for a day would grow the
# view without bound; this keeps the most recent window instead.
LOG_BUFFER_LINES = 5000

# Fallback for callers that do not say what they are running.
DEFAULT_SSH_TIMEOUT_S = 60

# `hmi-install install` waits up to GUI_READY_TIMEOUT (25 s) for the panel to
# render, and on failure rolls back and restarts again before it exits. On an
# idle panel the whole thing measures 14 s; the allowance is for a panel that
# is busy running the application it is about to replace, where every step --
# extraction, two systemctl calls, the readiness wait, the rollback path --
# competes with it for the same cores.
INSTALL_TIMEOUT_S = 300

# Bundle upload: a fixed allowance plus time proportional to the payload. The
# floor rate is deliberately pessimistic (256 KiB/s) so a slow or congested
# field link is not mistaken for a hang.
SCP_BASE_TIMEOUT_S = 60
SCP_MIN_BYTES_PER_S = 256 * 1024

# Installing packages on the panel is a download over the field link, from an
# index that may be far away, onto a board that unpacks wheels slowly. It is
# nothing like the other commands and gets its own allowance.
DEP_INSTALL_TIMEOUT_S = 900

# Asked of the panel when an install is cut off before it reported a result.
#
# `hmi-install` rolls a release that will not render back on its own, but only
# if it survives long enough to do it: our watchdog killing the ssh, or the link
# dropping, takes the installer with it and can leave `current` pointing at a
# release that never came up. The panel is the only authority on what actually
# happened, so it is asked -- and it undoes the swap itself if the GUI is not
# running.
INSTALL_RECOVERY_COMMAND = (
    'echo "HMI_CURRENT=$(basename "$(readlink -f /opt/hmi_apps/current)")"; '
    'if hmi-install status 2>/dev/null | grep -qE "^gui:[[:space:]]+ready"; '
    'then echo "HMI_RECOVER=ok"; else echo "HMI_RECOVER=rollback"; '
    "hmi-install rollback; fi"
)

# ---- Deploy progress model --------------------------------------------------
# Percentages are apportioned by how long each phase actually takes, not by how
# many phases there are: on any real bundle the upload dominates everything
# else, so a bar that gave each step equal weight would sit at 40% for minutes
# and then sprint. Upload progress is exact (bytes sent); the install phase is
# advanced by the installer's own STEP lines.
PROGRESS_PACKAGED = 6
PROGRESS_UPLOAD_START = 8
PROGRESS_UPLOAD_END = 72
PROGRESS_INSTALL_START = 75

# Installer STEP tags in the order hmi-install emits them, mapped to the bar.
# Tags absent from a given run (a first install emits no prune) simply never
# fire; the bar is monotonic because each tag sets an absolute value.
INSTALL_STEP_PROGRESS = {
    "install-start": 76,
    "validate-path": 78,
    "verify-sha256": 82,
    "extract": 88,
    "validate-manifest": 90,
    "save-previous": 91,
    "swap-symlink": 93,
    "restart-gui": 96,
    "enable-boot": 98,
    "prune": 99,
    "install-complete": 100,
}

# What each STEP tag is doing, for the stage caption under the bar.
INSTALL_STEP_LABEL = {
    "install-start": "Starting install on the panel",
    "validate-path": "Checking the uploaded bundle",
    "verify-sha256": "Verifying checksum",
    "extract": "Extracting release",
    "validate-manifest": "Validating manifest on the target",
    "save-previous": "Recording the current release for rollback",
    "swap-symlink": "Switching the panel to the new release",
    "restart-gui": "Restarting the UI and waiting for it to render",
    "enable-boot": "Setting it as the boot default",
    "prune": "Pruning old releases",
    "install-complete": "Deployment complete",
}


class MainWindow(QMainWindow):
    def __init__(self, exit_after_ms=0):
        super().__init__()
        self.setWindowTitle("EmbeddedDisplay Studio")
        self._open_at_a_size_that_fits()
        self.exit_after_ms = exit_after_ms

        self.settings = QSettings("MIL-HMI", "Deployer")
        self.bundle_dir = self.settings.value("last_bundle", "")
        # Dark is the product default: the tool sits beside a panel that
        # runs Theme.mode="dark", and matching it keeps the preview and the
        # chrome reading as one surface. The toggle still switches both.
        self.theme = "dark"

        self.simulator = None
        self.relay = None
        # Tag Lab sender – mutually exclusive with simulator and relay.
        self.taglab_sender: TagLabSender = None
        # Manifest of the loaded bundle; the panel picker's Custom entry reads it.
        self.current_manifest = None
        # Pixel geometry read from the connected SOM. A resolution cannot tell
        # us the physical diagonal, so inches remain a user-selected preview value.
        self.detected_resolution = None
        # Most recent profile fields streamed from the connected SOM.
        self.memory_profile = {}
        self._profile_values = {}
        self._profile_bars = {}
        self._profile_bar_values = {}
        # Releases the panel reported, and the live journal follow.
        self._releases = []
        self._log_worker = None
        self._log_lines = []
        self.ssh_worker = None
        # Every SSH/SCP worker still running. A deploy chains four of them, and
        # a QThread destroyed while running takes the process down with it.
        self._ssh_workers = []
        # When the current bundle upload began, for the throughput line.
        self._upload_started = 0.0
        # Set once a deploy has failed, so later steps cannot paint over it.
        self._deploy_failed = False
        self._last_install_step = ""
        # Bumped by every deploy. A callback carrying an older number belongs
        # to a deployment that is over, and must not touch the bar, the
        # console, or the temporary files of the one running now.
        self._deploy_generation = getattr(self, "_deploy_generation", 0) + 1
        # Last line any SSH/SCP step printed, so a failure can name its cause.
        self._last_transport_line = ""

        self.setup_ui()
        self.apply_theme()

        # closeEvent covers the user shutting the window, but not every way the
        # application can end: app.quit(), the last window closing, or a signal
        # all skip it. Any of those leaves the telemetry relay's QThread alive
        # into interpreter shutdown, and Qt aborts the process when a running
        # QThread is destroyed -- which surfaces as a crash on exit, right after
        # a deploy, because a deploy is what starts the relay.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_transport)

        self._restore_detected_resolution()

        if self.bundle_dir and os.path.isdir(self.bundle_dir):
            self.load_bundle(self.bundle_dir)

        if self.exit_after_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(self.exit_after_ms, self.close)

    # What the Connect button says the link is doing. The button used to read
    # "Connect" throughout: while a connection was being attempted, after one
    # succeeded, and after one timed out. A connect to an unreachable panel
    # takes its full timeout to fail, so for that whole minute the only
    # feedback was a console line, and pressing the button again queued a
    # second attempt behind the first.
    #
    # text, icon, enabled
    LINK_STATES = {
        "idle": ("Connect", "plug-connected", True),
        "connecting": ("Connecting...", "loader-2", False),
        "connected": ("Connected", "plug-connected", True),
        "fault": ("Reconnect", "plug-off", True),
    }

    def _set_link_state(self, state: str) -> None:
        """Show on the Connect button whether the link is trying or established.

        Args:
            state: one of LINK_STATES. An unknown state falls back to "idle"
                rather than leaving the button describing the previous attempt.

        Side effects: rewrites the button's text, icon, enabled state and its
        `linkState` property, which the stylesheet colours.
        """
        text, icon_name, enabled = self.LINK_STATES.get(state, self.LINK_STATES["idle"])
        self.btn_test.setText(text)
        self.btn_test.setEnabled(enabled)
        self._themed_icon(self.btn_test, icon_name)
        # Qt does not restyle on a property change by itself.
        self.btn_test.setProperty("linkState", state)
        self.btn_test.style().unpolish(self.btn_test)
        self.btn_test.style().polish(self.btn_test)

    def _themed_icon(self, widget, name: str) -> None:
        """
        Give a widget an icon that follows the theme.

        Args:
            widget: anything with setIcon.
            name: the Tabler icon name.

        Icons are rendered to pixmaps at the colour they are asked for, so a
        stylesheet swap cannot reach them the way it reaches every other
        widget. Remembering which icon each widget wears is what lets them all
        be re-rendered when the theme changes -- without it, toggling to dark
        left a row of black glyphs on a black bar.
        """
        if not hasattr(self, "_icon_names"):
            self._icon_names = {}
        self._icon_names[widget] = name
        widget.setIcon(icon(name))

    def _restyle_icons(self) -> None:
        """Re-render every themed icon in the colour of the current theme."""
        for widget, name in getattr(self, "_icon_names", {}).items():
            try:
                widget.setIcon(icon(name))
            except RuntimeError:
                # The widget was destroyed; it will not be asked again.
                pass
        for widget, name in getattr(self, "_label_icon_names", {}).items():
            try:
                widget.setPixmap(icon(name).pixmap(17, 17))
            except RuntimeError:
                pass
        for widget, name in getattr(self, "_page_icon_names", {}).items():
            try:
                widget.setPixmap(icon(name).pixmap(24, 24))
            except RuntimeError:
                pass
        for (tab_bar, index), name in getattr(self, "_tab_icon_names", {}).items():
            try:
                tab_bar.setTabIcon(index, icon(name))
            except RuntimeError:
                pass

    def _themed_label_icon(self, widget, name: str) -> None:
        """Give a QLabel a small Tabler icon that follows theme changes."""
        if not hasattr(self, "_label_icon_names"):
            self._label_icon_names = {}
        self._label_icon_names[widget] = name
        widget.setPixmap(icon(name).pixmap(17, 17))

    def _themed_tab_icon(self, tab_bar, index: int, name: str) -> None:
        """Attach a tab icon that is re-rendered with the active theme."""
        if not hasattr(self, "_tab_icon_names"):
            self._tab_icon_names = {}
        self._tab_icon_names[(tab_bar, index)] = name
        tab_bar.setTabIcon(index, icon(name))

    def _section_heading(self, title: str, icon_name: str) -> QHBoxLayout:
        """Build a compact icon-and-title header for a console module."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(8)
        mark = QLabel()
        mark.setObjectName("sectionIcon")
        mark.setFixedSize(20, 20)
        mark.setAlignment(Qt.AlignCenter)
        self._themed_label_icon(mark, icon_name)
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        row.addWidget(mark)
        row.addWidget(label)
        row.addStretch()
        return row

    def _open_at_a_size_that_fits(self) -> None:
        """Open at the preferred size, or the screen's, whichever is smaller.

        The preferred size is a desktop-sized window. Display scaling shrinks
        the desktop in the units Qt lays out in -- a 1920x1080 screen is
        1280x720 at 150% -- so a fixed opening size puts part of the window,
        and the controls on it, past the edge of the screen. Margins leave room
        for the taskbar and the frame.
        """
        width, height = 1280, DEFAULT_WINDOW_HEIGHT
        screen = QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, max(640, available.width() - 40))
            height = min(height, max(480, available.height() - 60))
        self.resize(width, height)

    def _scrollable(self, page):
        """Wrap a workspace page so it scrolls instead of growing the window.

        A page's own minimum height was the window's minimum height: Display
        Console alone asked for 998 px, which with the chrome forced a floor of
        1214 px. On a 1920x1080 screen at 150% scaling the desktop is 1280x720
        in the units Qt lays out in, so the window could not fit on the screen
        at all and its contents were pushed over each other.

        Scrolling is the honest answer at any scale: the cards keep their
        readable size and the pane shows as many as fit.
        """
        area = QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # The pages paint their own cards on the workspace ground; a viewport
        # with its own background would draw a lighter rectangle behind them.
        area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget "
                           "{ background: transparent; }")
        return area

    def _page_heading(self, title: str, icon_name: str) -> QHBoxLayout:
        """Build the title row that opens a workspace page.

        Args:
            title: The page name, which is the tab's name and nothing more.
            icon_name: The Tabler icon the page's tab wears, so the heading and
                the tab it belongs to carry the same mark.

        Returns:
            A row holding the icon and the page title.

        Each page states its own name beside its own icon; without it, a page
        reached from the tab bar had no heading of its own and the only thing
        naming it was the tab the user had already left behind.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        mark = QLabel()
        mark.setObjectName("pageTitleIcon")
        mark.setFixedSize(26, 26)
        mark.setAlignment(Qt.AlignCenter)
        self._themed_page_icon(mark, icon_name)
        label = QLabel(title)
        label.setObjectName("consolePageTitle")
        row.addWidget(mark)
        row.addWidget(label)
        row.addStretch()
        return row

    def _themed_page_icon(self, widget, name: str) -> None:
        """Give a page heading its icon at title scale, following the theme."""
        if not hasattr(self, "_page_icon_names"):
            self._page_icon_names = {}
        self._page_icon_names[widget] = name
        widget.setPixmap(icon(name).pixmap(24, 24))

    def apply_theme(self):
        """
        Pushes the current theme's stylesheet onto the QApplication.

        Logs what it applied: a silently-missing stylesheet looks identical to a
        light theme, which is exactly the kind of failure that wastes an hour.
        """
        import logging
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        apply(app, self.theme)
        # apply() is what tells the icon renderer which palette is on screen,
        # so the re-render has to follow it, not precede it.
        self._restyle_icons()
        if hasattr(self, "designer_workspace"):
            self.designer_workspace.apply_theme(self.theme)
        logging.getLogger("EmbeddedDisplay Studio").info(
            "theme=%s stylesheet=%d chars", self.theme, len(app.styleSheet() or "")
        )

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 14, 18, 12)
        main_layout.setSpacing(12)

        # Top Bar
        top_bar = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton, QLabel, QTabBar
        from PySide6.QtGui import QPixmap

        # Use the supplied product mark exactly as shipped with Studio.
        logo_path = os.path.join(os.path.dirname(__file__), "resources", "logo_128.png")
        self.lbl_logo = QLabel()
        self.lbl_logo.setObjectName("studioMark")
        self.lbl_logo.setAlignment(Qt.AlignCenter)
        self.lbl_logo.setPixmap(
            QPixmap(logo_path).scaled(36, 36, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.lbl_logo.setFixedSize(46, 46)

        # Wordmark beside the logo, in the design system's heading style.
        title_wrap = QWidget()
        title_layout = QVBoxLayout(title_wrap)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(0)
        self.lbl_title = QLabel("EmbeddedDisplay Studio")
        self.lbl_title.setObjectName("productTitle")
        self.lbl_subtitle = QLabel("HMI DEPLOYMENT & VALIDATION CONSOLE")
        self.lbl_subtitle.setObjectName("productSubtitle")

        # A QLabel never offers to be narrower than its text, and these two are
        # the widest things in the command strip: together they put a 389 px
        # floor under the window. On a 1920x1080 screen at 150% scaling the
        # desktop is 1280x720 in the units Qt lays out in, so a floor built
        # from text the window title already carries is not one worth keeping.
        # Ignored lets them give way first; nothing else in the row can.
        for label in (self.lbl_title, self.lbl_subtitle):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
        title_layout.addWidget(self.lbl_title)
        title_layout.addWidget(self.lbl_subtitle)

        self.lbl_connection = QLabel("●  DISCONNECTED")
        self.lbl_connection.setObjectName("connectionBadge")
        # Reports state; it is not operated. It gives way before any control
        # does, and its colour still reads when the word is clipped.
        self.lbl_connection.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lbl_connection.setMinimumWidth(0)

        # The target is operated from a compact command strip: Target IP ->
        # Port -> Connect -> live link state. This keeps the common path in
        # the same immediate visual hierarchy as the reference console.
        self.inp_host = QLineEdit(self.settings.value("host", "192.168.1.100"))
        self.inp_host.setObjectName("targetHostInput")
        self.inp_host.setMinimumWidth(150)
        self.inp_host.setPlaceholderText("10.66.48.44")
        self.inp_port = QLineEdit(str(self.settings.value("port", "22")))
        self.inp_port.setObjectName("targetPortInput")
        self.inp_port.setFixedWidth(68)
        self.inp_port.setPlaceholderText("22")
        self.btn_test = QPushButton("Connect")
        self.btn_test.setObjectName("connectButton")
        self._themed_icon(self.btn_test, "plug-connected")
        self.btn_test.clicked.connect(self.on_test_conn)

        self.btn_open = QPushButton("Open Bundle...")
        self.btn_open.setObjectName("topBarAction")
        self.btn_open.setProperty("variant", "outline")
        self._themed_icon(self.btn_open, "folder-open")
        self.btn_open.clicked.connect(self.on_open_bundle)

        self.btn_new = QPushButton("New App...")
        self.btn_new.setObjectName("topBarAction")
        self.btn_new.setProperty("variant", "secondary")
        self._themed_icon(self.btn_new, "plus")
        self.btn_new.clicked.connect(self.on_new_app)

        self.btn_theme = QPushButton("")
        self.btn_theme.setProperty("variant", "ghost")
        self._themed_icon(self.btn_theme, "sun" if self.theme == "dark" else "moon")
        self.btn_theme.clicked.connect(self.on_toggle_theme)

        top_bar.addWidget(self.lbl_logo)
        top_bar.addSpacing(8)
        top_bar.addWidget(title_wrap)
        top_bar.addSpacing(24)
        top_bar.addWidget(self.btn_open)
        top_bar.addWidget(self.btn_new)
        top_bar.addStretch()
        target_label = QLabel("TARGET IP")
        target_label.setObjectName("connectionFieldLabel")
        port_label = QLabel("PORT")
        port_label.setObjectName("connectionFieldLabel")
        for caption in (target_label, port_label):
            caption.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            caption.setMinimumWidth(0)
        top_bar.addWidget(target_label)
        top_bar.addWidget(self.inp_host)
        top_bar.addSpacing(8)
        top_bar.addWidget(port_label)
        top_bar.addWidget(self.inp_port)
        top_bar.addSpacing(6)
        top_bar.addWidget(self.btn_test)
        top_bar.addSpacing(8)
        top_bar.addWidget(self.lbl_connection)
        top_bar.addSpacing(8)
        top_bar.addWidget(self.btn_theme)

        main_layout.addLayout(top_bar)

        # A dedicated navigation rail belongs below the product header.  The
        # content widget keeps its QTabWidget state machine, but its tab bar is
        # deliberately surfaced here so navigation reads across the whole
        # Studio rather than as part of only the right-hand pane.
        self.primary_nav = QTabBar()
        self.primary_nav.setObjectName("primaryNav")
        self.primary_nav.setDrawBase(False)
        self.primary_nav.setExpanding(False)
        self.primary_nav.setElideMode(Qt.ElideNone)
        self.primary_nav.setIconSize(QSize(16, 16))
        self.primary_nav.setFixedHeight(44)
        main_layout.addWidget(self.primary_nav)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        self._workspace_splitter = splitter
        main_layout.addWidget(splitter, 1)

        # Left: Device Panel, with a caption strip directly beneath the bezel
        # reporting the emulated geometry and letting the user pick a panel.
        from PySide6.QtWidgets import QComboBox

        panel_wrap = QWidget()
        self._preview_panel_wrap = panel_wrap
        panel_wrap.setObjectName("previewPanel")
        panel_layout = QVBoxLayout(panel_wrap)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(10)

        self.device_panel = DevicePanel()
        # A native preview that cannot run explains itself here rather than
        # leaving the bezel silently showing the placeholder card.
        self.device_panel.previewMessage.connect(self.log)
        panel_layout.addWidget(self.device_panel, 1)

        caption = QHBoxLayout()
        caption.setContentsMargins(4, 0, 4, 0)

        # Live resolution readout for whatever the preview is currently emulating.
        self.lbl_resolution = QLabel(self.device_panel.resolution_text())
        self.lbl_resolution.setObjectName("panelResolution")

        # Panel picker. Selecting a diagonal re-lays out the preview at that
        # resolution, so an app can be checked against a 7" 1024x600 panel
        # without editing its manifest first.
        self.cmb_panel = QComboBox()
        for label, _inches, _w, _h in PANEL_PRESETS:
            self.cmb_panel.addItem(label)
        self._detected_panel_index = self.cmb_panel.count()
        self.cmb_panel.addItem("Connected target (run Connect / Test)")
        self._custom_panel_index = self.cmb_panel.count()
        self.cmb_panel.addItem("Custom (from manifest)")
        self.cmb_panel.setCurrentIndex(3)          # 10.1" 1280x800, the common default
        self.cmb_panel.currentIndexChanged.connect(self.on_panel_size_changed)

        display_label = QLabel("DISPLAY PROFILE")
        display_label.setObjectName("eyebrowLabel")
        caption.addWidget(display_label)
        caption.addWidget(self.cmb_panel)
        caption.addStretch()
        caption.addWidget(self.lbl_resolution)
        panel_layout.addLayout(caption)

        # The wrapper inherits the panel's floor so the splitter cannot collapse it.
        panel_wrap.setMinimumWidth(self.device_panel.minimumWidth())
        splitter.addWidget(panel_wrap)
        splitter.setCollapsible(0, False)

        # Right: Tools tab widget
        # The Deploy tab holds the original target/deployment/console content.
        # The Tag Lab tab holds the Tag Lab panel.
        self._right_tabs = QTabWidget()
        self._right_tabs.setObjectName("workspaceTabs")
        self._right_tabs.setAccessibleName("Deployer tool tabs")

        # Native visual authoring is additive: raw QML bundles still load and
        # deploy exactly as before, while .edsui projects use the same preview,
        # Tag Lab and deployment contracts after generation.
        from designer.ui import DesignerWorkspace
        self.designer_workspace = DesignerWorkspace()
        self.designer_workspace.message.connect(self.log)
        self.designer_workspace.previewRequested.connect(self._preview_designed_bundle)
        self.designer_workspace.deployRequested.connect(self._deploy_designed_bundle)
        self._right_tabs.addTab(self.designer_workspace, "Designer")

        # ── Deploy tab ────────────────────────────────────────────────────
        deploy_page = QWidget()
        deploy_page.setObjectName("deployConsolePage")
        right_layout = QVBoxLayout(deploy_page)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)

        page_subtitle = QLabel("Configure the target, validate the bundle, and manage the active panel release.")
        page_subtitle.setObjectName("consolePageSubtitle")
        page_subtitle.setWordWrap(True)
        right_layout.addLayout(self._page_heading("Display Console", "device-desktop"))
        right_layout.addWidget(page_subtitle)

        # Advanced SSH details stay near deployment without competing with the
        # inline connection strip above.
        conn_box = QGroupBox()
        conn_box.setProperty("class", "consoleSectionPanel")
        conn_layout = QVBoxLayout(conn_box)
        conn_layout.setContentsMargins(14, 14, 14, 14)
        conn_layout.setSpacing(8)
        conn_layout.addLayout(self._section_heading("Target Details", "server"))
        conn_body = QFrame()
        conn_body.setProperty("class", "consoleSectionBody")
        conn_form = QFormLayout(conn_body)
        conn_form.setContentsMargins(14, 12, 14, 12)
        self.inp_user = QLineEdit(self.settings.value("user", "root"))
        self.inp_user.setObjectName("targetDetailInput")
        self.inp_key = QLineEdit(self.settings.value("key", ""))
        self.inp_key.setObjectName("targetDetailInput")
        self.inp_key.setPlaceholderText("Leave empty for default agent")

        conn_form.addRow("User:", self.inp_user)
        conn_form.addRow("Key:", self.inp_key)

        self.lbl_target_resolution = QLabel("Not detected")
        self.lbl_target_resolution.setObjectName("targetResolution")
        conn_form.addRow("Display:", self.lbl_target_resolution)
        conn_layout.addWidget(conn_body)

        right_layout.addWidget(conn_box)

        # Deployment Actions
        deploy_box = QGroupBox()
        deploy_box.setProperty("class", "consoleSectionPanel")
        deploy_layout = QVBoxLayout(deploy_box)
        deploy_layout.setContentsMargins(14, 14, 14, 14)
        deploy_layout.setSpacing(8)
        deploy_layout.addLayout(self._section_heading("Deployment", "upload"))
        deploy_body = QFrame()
        deploy_body.setProperty("class", "consoleSectionBody")
        deploy_body_layout = QVBoxLayout(deploy_body)
        deploy_body_layout.setContentsMargins(14, 12, 14, 12)
        deploy_body_layout.setSpacing(8)

        from PySide6.QtWidgets import QLabel
        self.val_label = QLabel("No bundle loaded.")
        self.val_label.setWordWrap(True)
        deploy_body_layout.addWidget(self.val_label)

        self.btn_deploy = QPushButton("Deploy to Target")
        self.btn_deploy.setObjectName("primaryAction")
        self.btn_deploy.setProperty("variant", "default")
        self.btn_deploy.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_deploy, "upload")
        self.btn_deploy.clicked.connect(self.on_deploy)
        self.btn_deploy.setEnabled(False)
        self.btn_deploy.setFixedHeight(28)
        deploy_body_layout.addWidget(self.btn_deploy)

        # Deployment progress. A deploy spends most of its wall clock inside
        # one silent scp, so without this the tool looks frozen for minutes on
        # a large bundle -- which has been reported as a hang more than once.
        # Keep this slot in the layout at all times.  Progress was previously
        # added as two hidden widgets, so making them visible after Deploy was
        # pressed increased the Deployment card (and the whole window) height.
        # The fixed shell reserves their exact footprint while it is empty.
        self.progress_slot = QWidget()
        self.progress_slot.setObjectName("deploymentProgressSlot")
        self.progress_slot.setFixedHeight(46)
        progress_layout = QVBoxLayout(self.progress_slot)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)

        self.progress = QProgressBar()
        self.progress.setObjectName("deploymentProgressBar")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        # The percentage belongs in the stage line; the bar follows the
        # PDB-4000 splash treatment and stays a clean visual indicator.
        self.progress.setTextVisible(False)
        self.progress.setFormat("%p%")
        self.progress.setFixedHeight(12)
        # Keep the full deployment status treatment on screen from startup.
        # Besides making the card's expected height clear, this prevents Qt
        # from recalculating its parent layout when deployment begins.
        self.progress.setVisible(True)
        progress_layout.addWidget(self.progress)

        self.lbl_stage = QLabel("Ready to deploy")
        self.lbl_stage.setWordWrap(False)
        self.lbl_stage.setFixedHeight(24)
        self.lbl_stage.setStyleSheet("color: #a1a1aa;")
        self.lbl_stage.setVisible(True)
        progress_layout.addWidget(self.lbl_stage)
        deploy_body_layout.addWidget(self.progress_slot)

        h_layout = QHBoxLayout()
        self.btn_rollback = QPushButton("Rollback")
        self.btn_rollback.setProperty("variant", "destructive")
        self.btn_rollback.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_rollback, "history")
        self.btn_rollback.clicked.connect(self.on_rollback)
        self.btn_rollback.setFixedHeight(28)

        self.btn_restart = QPushButton("Restart GUI")
        self.btn_restart.setProperty("variant", "outline")
        self.btn_restart.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_restart, "refresh")
        self.btn_restart.clicked.connect(self.on_restart)
        self.btn_restart.setFixedHeight(28)

        h_layout.addWidget(self.btn_rollback)
        h_layout.addWidget(self.btn_restart)
        deploy_body_layout.addLayout(h_layout)
        deploy_layout.addWidget(deploy_body)

        right_layout.addWidget(deploy_box)

        # Installed releases.
        #
        # The panel retains KEEP_RELEASES beyond current and previous, but
        # Rollback reaches exactly one back. A regression noticed two deploys
        # late could be listed and never returned to.
        releases_box = QGroupBox()
        releases_box.setProperty("class", "consoleSectionPanel")
        releases_layout = QVBoxLayout(releases_box)
        releases_layout.setContentsMargins(14, 14, 14, 14)
        releases_layout.setSpacing(8)
        releases_layout.addLayout(self._section_heading("Installed Releases", "history"))
        releases_body = QFrame()
        releases_body.setProperty("class", "consoleSectionBody")
        releases_body_layout = QVBoxLayout(releases_body)
        releases_body_layout.setContentsMargins(14, 12, 14, 12)
        releases_body_layout.setSpacing(8)

        self.cmb_releases = QComboBox()
        self.cmb_releases.setAccessibleName("Installed releases on the panel")
        self.cmb_releases.setToolTip(
            "Releases the panel still holds. Activating one re-points the "
            "panel at it and restarts the GUI; the release running now becomes "
            "the rollback target."
        )
        self.cmb_releases.addItem("Connect to list releases")
        self.cmb_releases.setEnabled(False)
        releases_body_layout.addWidget(self.cmb_releases)

        releases_actions = QHBoxLayout()
        releases_actions.setSpacing(8)
        self.btn_refresh_releases = QPushButton("Refresh")
        self.btn_refresh_releases.setProperty("variant", "outline")
        self.btn_refresh_releases.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_refresh_releases, "refresh")
        self.btn_refresh_releases.clicked.connect(self.refresh_releases)
        self.btn_refresh_releases.setFixedHeight(28)

        self.btn_activate = QPushButton("Activate Release")
        self.btn_activate.setProperty("variant", "secondary")
        self.btn_activate.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_activate, "upload")
        self.btn_activate.clicked.connect(self.on_activate_release)
        self.btn_activate.setFixedHeight(28)
        self.btn_activate.setEnabled(False)

        releases_actions.addWidget(self.btn_refresh_releases)
        releases_actions.addWidget(self.btn_activate)
        releases_body_layout.addLayout(releases_actions)
        releases_layout.addWidget(releases_body)
        right_layout.addWidget(releases_box)

        # Console Output
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(150)
        console_box = QGroupBox()
        console_box.setProperty("class", "consoleSectionPanel")
        console_layout = QVBoxLayout(console_box)
        console_layout.setContentsMargins(14, 14, 14, 14)
        console_layout.setSpacing(8)
        console_layout.addLayout(self._section_heading("Console Output", "terminal-2"))
        console_body = QFrame()
        console_body.setProperty("class", "consoleSectionBody")
        console_body_layout = QVBoxLayout(console_body)
        console_body_layout.setContentsMargins(12, 12, 12, 12)
        console_body_layout.addWidget(self.console, 1)
        console_layout.addWidget(console_body, 1)
        right_layout.addWidget(console_box, 1)

        self._right_tabs.addTab(self._scrollable(deploy_page), "Display Console")

        # ── Tag Lab tab ────────────────────────────────────────────────────
        # Imported here (deferred) so the tab is only instantiated after
        # PySide6 is confirmed available. TagLabPanel guards its own imports.
        from .taglab_panel import TagLabPanel
        self.taglab_panel = TagLabPanel()
        self._themed_page_icon(self.taglab_panel.title_icon, "activity")
        self.taglab_panel.sendingStarted.connect(self._on_taglab_start)
        self.taglab_panel.sendingStopped.connect(self._on_taglab_stop)
        self._right_tabs.addTab(self._scrollable(self.taglab_panel), "Tag Lab")

        # ── Panel Logs tab ────────────────────────────────────────────────
        # The deploy console shows what this tool did. It says nothing about
        # what the panel does afterwards, and an application that dies an hour
        # later leaves no trace here -- the journal on the board is the only
        # record, and until now reading it meant leaving the window for a
        # terminal.
        logs_page = QWidget()
        logs_layout = QVBoxLayout(logs_page)
        logs_layout.setContentsMargins(12, 12, 12, 12)
        logs_layout.setSpacing(12)
        logs_layout.addLayout(self._page_heading("Panel Logs", "terminal-2"))
        logs_subtitle = QLabel(
            "Live journal from the panel's own services: the loader hosting "
            "your application, and the hardware daemon."
        )
        logs_subtitle.setObjectName("consolePageSubtitle")
        logs_subtitle.setWordWrap(True)
        logs_layout.addWidget(logs_subtitle)

        logs_box = QGroupBox()
        logs_box.setProperty("class", "consoleSectionPanel")
        logs_outer = QVBoxLayout(logs_box)
        logs_outer.setContentsMargins(14, 14, 14, 14)
        logs_outer.setSpacing(8)
        logs_outer.addLayout(self._section_heading("Journal", "terminal-2"))

        logs_controls = QHBoxLayout()
        logs_controls.setSpacing(8)
        self.btn_logs_follow = QPushButton("Start Following")
        self.btn_logs_follow.setProperty("variant", "default")
        self.btn_logs_follow.setProperty("deploymentAction", True)
        self._themed_icon(self.btn_logs_follow, "activity")
        self.btn_logs_follow.setFixedHeight(28)
        self.btn_logs_follow.clicked.connect(self.on_toggle_logs)

        self.inp_log_filter = QLineEdit()
        self.inp_log_filter.setPlaceholderText("Filter (substring, case-insensitive)")
        self.inp_log_filter.setObjectName("targetDetailInput")
        self.inp_log_filter.textChanged.connect(self._render_logs)

        self.btn_logs_clear = QPushButton("Clear")
        self.btn_logs_clear.setProperty("variant", "outline")
        self.btn_logs_clear.setProperty("deploymentAction", True)
        self.btn_logs_clear.setFixedHeight(28)
        self.btn_logs_clear.clicked.connect(self.on_clear_logs)

        logs_controls.addWidget(self.btn_logs_follow)
        logs_controls.addWidget(self.inp_log_filter, 1)
        logs_controls.addWidget(self.btn_logs_clear)
        logs_outer.addLayout(logs_controls)

        logs_body = QFrame()
        logs_body.setProperty("class", "consoleSectionBody")
        logs_body_layout = QVBoxLayout(logs_body)
        logs_body_layout.setContentsMargins(12, 12, 12, 12)
        self.logs_view = QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        self.logs_view.setMinimumHeight(200)
        self.logs_view.setPlaceholderText(
            "Not following. Connect to the panel and press Start Following."
        )
        logs_body_layout.addWidget(self.logs_view, 1)
        logs_outer.addWidget(logs_body, 1)
        logs_layout.addWidget(logs_box, 1)
        self._right_tabs.addTab(self._scrollable(logs_page), "Panel Logs")

        # The profile uses the same cards, labels, and outline button treatment
        # as Deploy so target diagnostics feel like part of one application.
        profile_page = QWidget()
        profile_layout = QVBoxLayout(profile_page)
        profile_layout.setContentsMargins(12, 12, 12, 12)
        profile_layout.setSpacing(12)

        # The page names itself the way Display Console and Tag Lab do: the tab's
        # own title and the tab's own icon, with the explanatory line demoted to
        # the subtitle it always was.
        profile_heading = self._page_heading("System Profile", "cpu")
        self.btn_refresh_profile = QPushButton("Refresh profile")
        self.btn_refresh_profile.setProperty("variant", "outline")
        self.btn_refresh_profile.setProperty("busy", "false")
        self._themed_icon(self.btn_refresh_profile, "refresh")
        self.btn_refresh_profile.clicked.connect(self.refresh_memory_profile)
        profile_heading.addWidget(self.btn_refresh_profile)
        profile_layout.addLayout(profile_heading)

        profile_copy = QLabel(
            "Live storage and memory snapshot from the connected SOM."
        )
        profile_copy.setObjectName("consolePageSubtitle")
        profile_copy.setWordWrap(True)
        profile_layout.addWidget(profile_copy)

        active_box = QGroupBox()
        active_box.setProperty("class", "consoleSectionPanel")
        active_outer = QVBoxLayout(active_box)
        active_outer.setContentsMargins(14, 14, 14, 14)
        active_outer.setSpacing(8)
        active_outer.addLayout(self._section_heading("Current Deployment", "device-desktop"))
        active_body = QFrame()
        active_body.setProperty("class", "consoleSectionBody")
        active_layout = QFormLayout(active_body)
        active_layout.setContentsMargins(14, 12, 14, 12)
        self._add_profile_value(active_layout, "Package:", "RELEASE", "Not queried")
        self._add_profile_value(active_layout, "Deployed at:", "DEPLOY_PATH", "Not queried")
        self._add_profile_value(active_layout, "Current application:", "APP_KB", "Not queried")
        self._add_profile_value(
            active_layout,
            "Compressed package:",
            "COMPRESSED_BYTES",
            "Not queried",
        )
        active_outer.addWidget(active_body)
        profile_layout.addWidget(active_box)

        storage_box = QGroupBox()
        storage_box.setProperty("class", "consoleSectionPanel")
        storage_outer = QVBoxLayout(storage_box)
        storage_outer.setContentsMargins(14, 14, 14, 14)
        storage_outer.setSpacing(8)
        storage_outer.addLayout(self._section_heading("Storage Distribution", "server"))
        storage_body = QFrame()
        storage_body.setProperty("class", "consoleSectionBody")
        storage_layout = QVBoxLayout(storage_body)
        storage_layout.setContentsMargins(14, 12, 14, 12)
        self._add_profile_bar(storage_layout, "OS image capacity", "ROOT_KB")
        self._add_profile_bar(storage_layout, "Other system files", "SYSTEM_KB")
        self._add_profile_bar(storage_layout, "Application storage", "RELEASES_KB")
        self._add_profile_bar(storage_layout, "Free system storage", "FREE_KB")
        self._add_profile_bar(
            storage_layout,
            "Compressed current package",
            "COMPRESSED_BYTES",
        )
        storage_outer.addWidget(storage_body)
        profile_layout.addWidget(storage_box)

        resources_box = QGroupBox()
        resources_box.setProperty("class", "consoleSectionPanel")
        resources_outer = QVBoxLayout(resources_box)
        resources_outer.setContentsMargins(14, 14, 14, 14)
        resources_outer.setSpacing(8)
        resources_outer.addLayout(self._section_heading("System Resources", "cpu"))
        resources_body = QFrame()
        resources_body.setProperty("class", "consoleSectionBody")
        resources_layout = QFormLayout(resources_body)
        resources_layout.setContentsMargins(14, 12, 14, 12)
        self._add_profile_value(resources_layout, "Available RAM:", "RAM_AVAILABLE_KB", "Not queried")
        self._add_profile_value(resources_layout, "Root filesystem:", "ROOT_SUMMARY", "Not queried")
        self._add_profile_value(resources_layout, "Profile status:", "STATUS", "Connect to refresh")
        resources_outer.addWidget(resources_body)
        profile_layout.addWidget(resources_box)
        profile_layout.addStretch()
        # Identity is compared against whatever the tab holds, which is now
        # the scroll area rather than the page itself.
        self._profile_page = self._scrollable(profile_page)
        self._right_tabs.addTab(self._profile_page, "System Profile")
        # Selecting the tab is the request for the measurement.
        self._right_tabs.currentChanged.connect(self._on_tab_changed)

        tab_icons = ("device-imac", "device-desktop", "activity", "terminal-2", "cpu")
        for index in range(self._right_tabs.count()):
            self.primary_nav.addTab(self._right_tabs.tabText(index))
            self._themed_tab_icon(self.primary_nav, index, tab_icons[index])
        self._right_tabs.tabBar().hide()
        self.primary_nav.currentChanged.connect(self._right_tabs.setCurrentIndex)
        self._right_tabs.currentChanged.connect(self.primary_nav.setCurrentIndex)

        splitter.addWidget(self._right_tabs)
        splitter.setSizes([800, 400])
        self._on_tab_changed(self._right_tabs.currentIndex())

        # Footer: attribution on the left, version hard right. Kept to the muted
        # token so it reads as chrome and never competes with the panel preview.
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 8, 2, 0)

        self.lbl_footer = QLabel("FLYVI TECHNOLOGIES  •  EMBEDDED DISPLAY ENGINEERING")
        self.lbl_footer.setObjectName("footerText")

        self.lbl_version = QLabel(APP_VERSION)
        self.lbl_version.setObjectName("footerVersion")

        # The footer is a signature. It put a 612 px floor under the window on
        # its own, which is a lot of screen to reserve for something nobody
        # clicks.
        self.lbl_footer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.lbl_version.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        for chrome in (self.lbl_footer, self.lbl_version):
            chrome.setMinimumWidth(0)

        footer.addWidget(self.lbl_footer)
        footer.addStretch()
        footer.addWidget(self.lbl_version)
        main_layout.addLayout(footer)

        self._style_footer()

    def _style_footer(self):
        """
        Applies the muted footer styling.

        Done in code rather than the global stylesheet because the footer must
        follow the light/dark toggle, and the two generated stylesheets do not
        know about these two object names.
        """
        muted = "#94a3b8" if self.theme == "dark" else "#64748b"
        for widget in (self.lbl_footer, self.lbl_version):
            widget.setStyleSheet(f"color: {muted}; font-size: 12px;")

        if hasattr(self, "lbl_connection"):
            self.lbl_connection.style().unpolish(self.lbl_connection)
            self.lbl_connection.style().polish(self.lbl_connection)

    def _add_profile_value(self, layout, label, key, initial):
        """Add one selectable text value to a memory-profile form.

        Args:
            layout: Form layout receiving the new row.
            label: User-facing row label.
            key: Machine-readable profile field name.
            initial: Text shown before the first remote refresh.

        Side effects: creates and stores a QLabel in ``_profile_values``.
        """
        value = QLabel(initial)
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._profile_values[key] = value
        layout.addRow(label, value)

    def _add_profile_bar(self, layout, label, key):
        """Add one shadcn-styled horizontal capacity bar to the profile tab.

        Args:
            layout: Vertical layout receiving the label and progress bar.
            label: User-facing resource name.
            key: Machine-readable profile field represented by this bar.

        Side effects: creates and stores a QProgressBar in ``_profile_bars``.
        """
        # The measurement is stated beside the resource name, not painted
        # inside the bar. A bar is two-toned by definition -- filled chunk on
        # an empty track -- and no single text colour reads on both: dark text
        # vanished into a full chunk in light mode, light text vanished into
        # the empty track. Outside the bar it is legible at any percentage in
        # either theme, and the bar is left to do the one thing a bar is for.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 2)
        header.addWidget(QLabel(label))
        header.addStretch()
        value = QLabel("Not queried")
        value.setObjectName("profileBarValue")
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._profile_bar_values[key] = value
        header.addWidget(value)
        layout.addLayout(header)

        bar = QProgressBar()
        bar.setObjectName("profileCapacityBar")
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        self._profile_bars[key] = bar
        layout.addWidget(bar)

    def on_panel_size_changed(self, index):
        """
        Applies the selected panel geometry to the preview.

        Args:
            index: row in cmb_panel. The connected-target row uses geometry
                detected over SSH; Custom falls back to the manifest screen.
        """
        if 0 <= index < len(PANEL_PRESETS):
            _label, inches, width, height = PANEL_PRESETS[index]
        elif index == self._detected_panel_index and self.detected_resolution:
            width, height = self.detected_resolution
            inches = 0.0
        else:
            screen = (self.current_manifest or {}).get("screen", {})
            width = int(screen.get("width", 1280))
            height = int(screen.get("height", 800))
            # A manifest states a resolution but not the glass it runs on, so
            # the diagonal from whichever preset was last chosen is kept.
            inches = 0.0
        self.device_panel.set_target_resolution(width, height, inches)
        self.lbl_resolution.setText(self.device_panel.resolution_text())

    def _record_detected_resolution(self, line):
        """Apply a display resolution marker emitted by the connected SOM.

        Args:
            line: One remote output line. Lines that do not contain a valid
                HMI_DISPLAY marker are ignored.

        Side effects: updates the target readout, picker, preview, and console.
        """
        resolution = parse_display_resolution(line)
        if resolution is None:
            return

        width, height = resolution
        # Remembered across runs. Without this the Studio opened on its default
        # 10.1" 1280x800 every time and only learned the truth when Connect was
        # pressed -- so a 1024x768 panel was designed for, previewed and judged
        # at 16:10 until then, and the difference was read as the panel being
        # wrong rather than the Studio guessing.
        self.settings.setValue("panel_width", width)
        self.settings.setValue("panel_height", height)
        self._apply_detected_resolution(width, height, live=True)
        self.log(f"Connected SOM display detected: {width} x {height} px")

    def _apply_detected_resolution(self, width, height, live):
        """Point the readout, the picker, the preview and the canvas at a panel.

        Args:
            width, height: the panel's pixel geometry.
            live: True when a probe just reported it, False when it is being
                restored from the last session -- which the labels say, because
                a remembered geometry presented as a live one is how the wrong
                board gets designed for.
        """
        display_text = f"{width} x {height} px"
        self.detected_resolution = (width, height)
        self.lbl_target_resolution.setText(
            display_text if live else f"{display_text} (last seen)")
        self.cmb_panel.setItemText(
            self._detected_panel_index,
            f"Connected target — {display_text}" if live
            else f"Last connected target — {display_text}",
        )
        # setCurrentIndex emits nothing when the row is already current, so a
        # reconnect to a panel of a different size would leave the preview on
        # the previous geometry. Apply it directly instead of relying on the
        # signal.
        self.cmb_panel.setCurrentIndex(self._detected_panel_index)
        self.on_panel_size_changed(self._detected_panel_index)
        # The designer draws against the same glass the preview emulates, so it
        # follows the detected geometry rather than the manifest's guess.
        if hasattr(self, "designer_workspace"):
            self.designer_workspace.apply_target_resolution(width, height)

    def _restore_detected_resolution(self):
        """Open on the geometry of the panel this Studio last spoke to."""
        try:
            width = int(self.settings.value("panel_width", 0) or 0)
            height = int(self.settings.value("panel_height", 0) or 0)
        except (TypeError, ValueError):
            return
        if width > 0 and height > 0:
            self._apply_detected_resolution(width, height, live=False)

    def _profile_number(self, key):
        """Return one non-negative integer field from the current SOM profile."""
        try:
            return max(0, int(self.memory_profile.get(key, "0")))
        except (TypeError, ValueError):
            return 0

    def _set_profile_bar(self, key, amount, total, text, pending=False):
        """Render one memory-profile bar relative to its relevant capacity.

        Args:
            key: Bar key registered by _add_profile_bar.
            amount: Numerator in KiB or bytes, depending on the bar.
            total: Matching denominator. Zero produces an unavailable bar.
            text: Human-readable measurement shown inside the bar.
            pending: True while the fields behind this bar are still in flight,
                which is reported as such rather than drawn as an empty bar.
        """
        bar = self._profile_bars[key]
        value = self._profile_bar_values[key]
        if pending:
            bar.setValue(0)
            value.setText(PROFILE_PENDING_TEXT)
            return
        if total <= 0:
            bar.setValue(0)
            value.setText(text)
            return
        percent = min(100, round(amount * 100 / total))
        bar.setValue(percent)
        value.setText(f"{text}  ({percent}%)")

    def _profile_pending(self, *keys):
        """True when any of these fields has not arrived from the SOM yet.

        A field that is still in flight is not a field worth zero. Rendering an
        absent measurement as "0 KiB" made a running refresh look like a
        finished one that had found an empty board.
        """
        return any(key not in self.memory_profile for key in keys)

    def _render_memory_profile(self):
        """Render all visible profile cards and capacity bars from stored fields."""
        root_kb = self._profile_number("ROOT_KB")
        used_kb = self._profile_number("USED_KB")
        free_kb = self._profile_number("FREE_KB")
        releases_kb = self._profile_number("RELEASES_KB")
        app_kb = self._profile_number("APP_KB")
        compressed_bytes = self._profile_number("COMPRESSED_BYTES")
        system_kb = max(0, used_kb - releases_kb)

        pending = PROFILE_PENDING_TEXT

        self._profile_values["RELEASE"].setText(
            pending if self._profile_pending("RELEASE")
            else self.memory_profile["RELEASE"]
        )
        self._profile_values["DEPLOY_PATH"].setText(
            pending if self._profile_pending("DEPLOY_PATH")
            else self.memory_profile["DEPLOY_PATH"]
        )
        self._profile_values["APP_KB"].setText(
            pending if self._profile_pending("APP_KB") else format_kib(app_kb)
        )

        compressed_pending = self._profile_pending("COMPRESSED_BYTES")
        compressed_text = pending if compressed_pending else format_bytes(compressed_bytes)
        card_text = compressed_text
        if not compressed_pending and compressed_bytes:
            card_text += " (recomputed from active release)"
        self._profile_values["COMPRESSED_BYTES"].setText(card_text)

        self._profile_values["RAM_AVAILABLE_KB"].setText(
            pending if self._profile_pending("RAM_AVAILABLE_KB")
            else format_kib(self._profile_number("RAM_AVAILABLE_KB"))
        )
        self._profile_values["ROOT_SUMMARY"].setText(
            pending if self._profile_pending("ROOT_KB", "FREE_KB")
            else f"{format_kib(root_kb)} total · {format_kib(free_kb)} free"
        )

        self._set_profile_bar(
            "ROOT_KB", root_kb, root_kb, format_kib(root_kb),
            pending=self._profile_pending("ROOT_KB"),
        )
        self._set_profile_bar(
            "SYSTEM_KB", system_kb, root_kb, f"{format_kib(system_kb)} used",
            pending=self._profile_pending("ROOT_KB", "USED_KB", "RELEASES_KB"),
        )
        self._set_profile_bar(
            "RELEASES_KB", releases_kb, root_kb, f"{format_kib(releases_kb)} retained",
            pending=self._profile_pending("ROOT_KB", "RELEASES_KB"),
        )
        self._set_profile_bar(
            "FREE_KB", free_kb, root_kb, format_kib(free_kb),
            pending=self._profile_pending("ROOT_KB", "FREE_KB"),
        )
        self._set_profile_bar(
            "COMPRESSED_BYTES",
            compressed_bytes,
            app_kb * 1024,
            compressed_text,
            pending=compressed_pending,
        )

    def _record_memory_profile_line(self, line):
        """Consume a streamed profile field from the SOM and refresh the tab.

        Args:
            line: One remote output line from MEMORY_PROFILE_COMMAND.

        Side effects: updates in-memory profile fields and the visible tab.
        """
        parsed = parse_memory_profile_line(line)
        if parsed is None:
            return
        key, value = parsed
        self.memory_profile[key] = value
        if key == "STAGE":
            self._profile_values["STATUS"].setText(value)
            return
        if key == "COMPRESSED_BYTES":
            # The stage banner belongs to the measurement that was running. It
            # is the last field the SOM sends, so its arrival -- not the SSH
            # process exiting some seconds later -- is what ends the stage. Left
            # to the exit code alone, "Calculating compressed package size…"
            # stayed on screen over a completed profile, and stayed there for
            # good whenever the command was cut short by its watchdog.
            self._profile_values["STATUS"].setText("Current SOM snapshot")
        self._render_memory_profile()

    def _on_tab_changed(self, _index: int) -> None:
        """Adapt the shell to the selected workspace and lazily profile."""
        # Designer owns a resolution-accurate bezel around its canvas. Hide
        # the separate runtime preview there so the editor gets the full
        # workspace; every operational tab retains the established preview.
        in_designer = self._right_tabs.currentWidget() is self.designer_workspace
        self._preview_panel_wrap.setVisible(not in_designer)
        if self._right_tabs.currentWidget() is self._profile_page and not self.memory_profile:
            self.refresh_memory_profile()

    def _set_refresh_busy(self, busy: bool) -> None:
        """Show, and hold, the engaged state on the Refresh profile button.

        Args:
            busy: True from the click until the remote profile command exits.

        Qt does not re-evaluate a stylesheet when a property changes, so the
        unpolish/polish pair is what actually puts the new state on screen.
        """
        button = self.btn_refresh_profile
        button.setProperty("busy", "true" if busy else "false")
        button.setEnabled(not busy)
        button.setText("Refreshing…" if busy else "Refresh profile")
        button.style().unpolish(button)
        button.style().polish(button)

    def refresh_memory_profile(self):
        """Read the active release and capacity profile from the connected SOM.

        The SSH command runs off the UI thread, so recompressing a large active
        release cannot freeze the Studio window.
        """
        self.save_settings()
        self.memory_profile = {}
        # Clear the previous snapshot off the screen at the moment of the click.
        # Leaving the last run's numbers up until the first line arrives made a
        # refresh indistinguishable from nothing having happened.
        self._render_memory_profile()
        self._profile_values["STATUS"].setText("Refreshing from connected SOM…")
        self._set_refresh_busy(True)
        self.log("Refreshing current SOM memory profile...")
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(),
            self.inp_user.text().strip(),
            self.ssh_port(),
            self.inp_key.text().strip(),
            MEMORY_PROFILE_COMMAND,
        )

        def on_finished(code):
            self._set_refresh_busy(False)
            if code == 0:
                self._profile_values["STATUS"].setText("Current SOM snapshot")
            else:
                self._profile_values["STATUS"].setText(
                    "Profile incomplete — see Console Output"
                )

        self.run_ssh_worker(
            cmd,
            "Memory Profile",
            callback=on_finished,
            timeout_s=MEMORY_PROFILE_TIMEOUT_S,
            line_hook=self._record_memory_profile_line,
        )

    def on_toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self._icon_names[self.btn_theme] = "sun" if self.theme == "dark" else "moon"
        self.apply_theme()
        self._style_footer()

        # Keep the preview in step with the chrome (CONTRACT 11.2). This must go
        # through the panel: a bare engine.evaluate("Theme.mode = ...") has no
        # QML imports in scope and fails silently.
        self.device_panel.set_preview_theme(self.theme)

    def on_open_bundle(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select App Bundle Directory", self.bundle_dir)
        if dir_path:
            self.load_bundle(dir_path)

    def on_new_app(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Directory to Scaffold", "")
        if dir_path:
            target = os.path.join(dir_path, "new-app")
            try:
                create_bundle(target)
                self.load_bundle(target)
                QMessageBox.information(self, "Success", f"App scaffolded at {target}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to scaffold: {e}")

    def load_bundle(self, dir_path):
        # An existing Qt application will not have a manifest - it was never
        # written for this platform. Rather than refusing it, infer one and ask.
        # This is the difference between a tool that only accepts bundles it
        # produced and one that can adopt an app somebody already has.
        if not os.path.isfile(os.path.join(dir_path, "manifest.json")):
            proposed = detect_bundle(dir_path)
            if not proposed:
                self.val_label.setText(
                    "No manifest.json, and no entry point could be detected.\n"
                    "Expected one of: main.qml, Main.qml, app.qml, main.py, app.py."
                )
                self.val_label.setStyleSheet("color: #ef4444;")
                self.btn_deploy.setEnabled(False)
                return
            kind = "Qt Quick (QML)" if proposed["runtime"] == "qml" else "Python (Qt Widgets)"
            answer = QMessageBox.question(
                self,
                "Create manifest?",
                f"This folder has no manifest.json.\n\n"
                f"Detected a {kind} application with entry '{proposed['entry']}'.\n\n"
                f"Create a manifest.json so it can be deployed?\n"
                f"  name:    {proposed['name']}\n"
                f"  version: {proposed['version']}\n"
                f"  screen:  {proposed['screen']['width']}x{proposed['screen']['height']}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                self.val_label.setText("Import cancelled: no manifest.json.")
                self.val_label.setStyleSheet("color: #ef4444;")
                self.btn_deploy.setEnabled(False)
                return
            try:
                written = write_manifest(dir_path, proposed)
                self.log(f"Created {written}")
            except OSError as exc:
                QMessageBox.critical(self, "Error", f"Could not write manifest.json:\n{exc}")
                return

        is_valid, msgs = validate_bundle(dir_path)
        if is_valid:
            self.bundle_dir = dir_path
            self.settings.setValue("last_bundle", dir_path)
            with open(os.path.join(dir_path, "manifest.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Manifests written before qt_binding existed do not say which Qt
            # binding the app needs. The panel can sniff it, but recording it
            # here means the deployed bundle states it outright and the two
            # sides cannot disagree.
            if manifest.get("runtime") == "python" and "qt_binding" not in manifest:
                manifest["qt_binding"] = detect_qt_binding(dir_path, manifest.get("entry", ""))
                if manifest["qt_binding"] == "pyside2" and manifest.get("qt", "").startswith(">=6"):
                    # Inferred by an importer that only knew about Qt6; leaving
                    # it would have the bundle advertise a Qt it cannot use.
                    manifest["qt"] = ">=5.15"
                try:
                    write_manifest(dir_path, manifest)
                    self.log(
                        f"Recorded qt_binding={manifest['qt_binding']} in manifest.json"
                    )
                except OSError as exc:
                    self.log(f"Could not update manifest.json: {exc}")

            # Remember it: the panel picker's "Custom" entry reads this, and the
            # caption strip reports the geometry the bundle actually declares.
            self.current_manifest = manifest
            screen = manifest.get("screen", {})
            if self.cmb_panel.currentIndex() >= len(PANEL_PRESETS):
                self.device_panel.set_target_resolution(
                    int(screen.get("width", 1280)), int(screen.get("height", 800))
                )
            self.lbl_resolution.setText(self.device_panel.resolution_text())

            runtime = manifest.get("runtime", "qml")
            if runtime == "qml":
                kind = "QML"
            else:
                # Name the binding: it decides which runtime the panel starts,
                # and it is the difference between the app rendering and dying
                # on its first import.
                kind = "Python / " + (
                    "PySide2 (Qt5)"
                    if manifest.get("qt_binding", "pyside6") == "pyside2"
                    else "PySide6 (Qt6)"
                )
            self.val_label.setText(
                f"Bundle Valid: {manifest.get('name')} v{manifest.get('version')}  [{kind}]"
            )
            self.val_label.setStyleSheet("color: #22c55e;")  # success
            self.btn_deploy.setEnabled(True)

            self.device_panel.load_bundle(dir_path, manifest)
            tags = manifest.get("tags_required", [])
            self.start_simulator(tags)

            # Bind the bundle's tags into Tag Lab so the user can inject signals
            # for any tag the app declares.
            self.taglab_panel.bind_tags(tags)
            self.designer_workspace.set_bundle(dir_path, manifest)
            # A bundle opened after Connect still targets the real panel: the
            # manifest's screen is only a default for an unknown display.
            if self.detected_resolution:
                self.designer_workspace.apply_target_resolution(*self.detected_resolution)
        else:
            err_text = "\n".join(msgs)
            self.val_label.setText(f"Validation Failed:\n{err_text}")
            self.val_label.setStyleSheet("color: #ef4444;")  # destructive
            self.btn_deploy.setEnabled(False)

    def _preview_designed_bundle(self, bundle_dir: str) -> None:
        """Reload generated QML through the established in-process preview."""
        self.load_bundle(bundle_dir)
        self.log("Designer preview loaded.")

    def _deploy_designed_bundle(self, bundle_dir: str) -> None:
        """Generate first, then enter the existing validated deploy pipeline."""
        self.load_bundle(bundle_dir)
        if self.btn_deploy.isEnabled():
            self.on_deploy()

    def _stop_all_senders(self) -> None:
        """
        Stop simulator, relay, and Tag Lab sender.

        Enforces mutual exclusion: only one source may drive TagEngine at a time.
        Called before starting any new source.
        """
        if self.simulator:
            self.simulator.stop()
            self.simulator = None
        if self.relay:
            self.relay.stop()
            self.relay = None
        if self.taglab_sender:
            self.taglab_sender.stop()
            self.taglab_sender = None
        if hasattr(self, "taglab_panel"):
            self.taglab_panel.set_sending(False)

    def tag_rx_port(self) -> int:
        """The port the preview's tag engine is actually listening on.

        Not always 5001: a stale process holding it makes the engine fall back
        to an ephemeral port, and a sender still aimed at 5001 would deliver
        every frame to nobody. Falls back to the documented port when there is
        no engine yet, which is the right guess for the first bundle.
        """
        engine = getattr(self.device_panel, "tag_engine", None)
        port = getattr(engine, "rx_port", 0) if engine is not None else 0
        return int(port) or 5001

    def start_simulator(self, expected_tags):
        self._stop_all_senders()
        self.simulator = TelemetrySimulator(
            expected_tags, self, udp_port=self.tag_rx_port()
        )
        self.simulator.error.connect(self.log)
        self.simulator.start()

    def start_relay(self):
        self._stop_all_senders()

        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        self.relay = TelemetryRelay(
            host, user, self.ssh_port(), key, self, udp_port=self.tag_rx_port()
        )
        self.relay.error.connect(self.log)
        self.relay.start()

    # ------------------------------------------------------------------
    # Tag Lab sender lifecycle (mutual exclusion enforced here)
    # ------------------------------------------------------------------

    def _on_taglab_start(self) -> None:
        """Slot: TagLabPanel requested start.  Enforce mutual exclusion."""
        self._stop_all_senders()
        model = self.taglab_panel.model()
        self.taglab_sender = TagLabSender(
            model, parent=self, port=self.tag_rx_port()
        )
        self.taglab_sender.error.connect(self.log)
        self.taglab_sender.start()
        self.taglab_panel.set_sending(True)

    def _on_taglab_stop(self) -> None:
        """Slot: TagLabPanel requested stop."""
        if self.taglab_sender:
            self.taglab_sender.stop()
            self.taglab_sender = None
        self.taglab_panel.set_sending(False)
        # Resume the offline simulator using the last known tags so the
        # preview does not go dark after Tag Lab is stopped.
        tags = (self.current_manifest or {}).get("tags_required", [])
        if tags:
            self.start_simulator(tags)

    # ------------------------------------------------------------------
    # Deployment progress
    # ------------------------------------------------------------------

    def _progress_begin(self) -> None:
        """Shows the bar at zero, in its neutral colour, for a new deploy."""
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setFormat("%p%")
        self.progress.setStyleSheet("")
        self.progress.setValue(0)
        self.lbl_stage.setVisible(True)
        self.lbl_stage.setStyleSheet("color: #a1a1aa;")
        self.lbl_stage.setText("Preparing...")
        self._deploy_failed = False

    def _progress_busy(self, stage: str) -> None:
        """
        Puts the bar in its indeterminate state for work of unknown length.

        Args:
            stage: caption shown under the bar.

        Packaging cannot report a percentage -- the cost is dominated by files
        the packer has not looked at yet -- but it can report that it is
        running. A bar sweeping under a stage line is the difference between a
        tool that is working and a window that has stopped answering.
        """
        self.progress.setRange(0, 0)
        self.progress.setFormat("")
        self.lbl_stage.setText(stage)

    def _progress_cancel(self, reason: str) -> None:
        """
        Stand the bar down without calling it a failure.

        Args:
            reason: caption shown under the bar.

        A deploy the operator called off is not a fault, and painting it red
        would teach them to ignore red.
        """
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setStyleSheet("")
        self.lbl_stage.setStyleSheet("color: #a1a1aa;")
        self.lbl_stage.setText(reason)

    def _progress_set(self, percent: int, stage: str = "") -> None:
        """
        Moves the bar forward.

        Args:
            percent: absolute value, 0-100.
            stage: caption shown under the bar; blank leaves it unchanged.

        Never moves backwards, and never overwrites a failure: once a deploy
        has failed the bar must keep saying so until the next attempt.
        """
        if self._deploy_failed:
            return
        if self.progress.maximum() == 0:
            # Leaving the indeterminate state: a real percentage has arrived.
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
        self.progress.setValue(max(self.progress.value(), int(percent)))
        if stage:
            self.lbl_stage.setText(stage)

    def _progress_fail(self, reason: str) -> None:
        """
        Marks the deployment failed: red bar, the reason kept on screen.

        A failed deploy that merely stops leaves the operator reading a
        half-filled bar and guessing. The panel itself is safe either way --
        the installer rolls back on its own -- but the tool still has to say
        plainly that this attempt did not land.
        """
        self._deploy_failed = True
        self.progress.setVisible(True)
        if self.progress.maximum() == 0:
            # A failure during an indeterminate stage: stop the sweep, and fill
            # the bar so the red says plainly that this attempt is over.
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
        self.progress.setFormat("Failed")
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background-color: #ef4444; }"
        )
        self.lbl_stage.setVisible(True)
        self.lbl_stage.setStyleSheet("color: #ef4444;")
        self.lbl_stage.setText(reason)
        self.log(f"DEPLOY FAILED: {reason}")
        self.device_panel.set_led_state(3)

    def _record_transport_line(self, line: str) -> None:
        """Remember the last thing an SSH/SCP step said, for failure messages."""
        text = line.strip()
        if text:
            self._last_transport_line = text

    def _transport_failure(self, what: str, code: int) -> str:
        """
        Describe a failed SSH/SCP step by what actually went wrong.

        Args:
            what: the step, named for a sentence ("the bundle upload").
            code: its exit code; -1 is this tool's watchdog, not the panel's.

        Returns:
            A sentence for the progress bar and the console.

        ssh reports its own failures as 255, and the remote command never ran
        at all in that case -- an unreachable panel, a refused key, or a panel
        already holding its 64 SSH sessions all arrive that way. Blaming those
        on whatever the step was trying to do sent people looking at the panel
        filesystem for a problem that was never there.
        """
        detail = self._last_transport_line
        if code == -1:
            return (
                f"The panel stopped responding during {what}"
                + (f": {detail}" if detail else ".")
            )
        if code == 255:
            return (
                "Could not reach the panel over SSH: "
                + (detail or "ssh exited 255 without saying why")
            )
        return (
            f"{what.capitalize()} failed on the panel (exit {code})"
            + (f": {detail}" if detail else ".")
        )

    def _progress_succeed(self) -> None:
        """Marks the deployment complete: full green bar."""
        self.progress.setValue(100)
        self.progress.setFormat("Deployed")
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background-color: #22c55e; }"
        )
        self.lbl_stage.setStyleSheet("color: #22c55e;")
        self.lbl_stage.setText("Running on the panel, and set as the boot default.")

    def _on_install_line(self, line: str) -> None:
        """
        Advances the bar from the installer's machine-readable STEP output.

        The installer prints `STEP <tag> <ok|fail> [detail]` for every stage it
        completes (CONTRACT section 6), which is a far better progress source
        than a timer: it reports what the panel has actually done. A `fail`
        marks the deployment failed and names the step.
        """
        if not line.startswith("STEP "):
            return
        parts = line.split(None, 3)
        if len(parts) < 3:
            return
        tag, status = parts[1], parts[2]
        detail = parts[3] if len(parts) > 3 else ""

        self._last_install_step = INSTALL_STEP_LABEL.get(tag, tag)
        if status == "fail":
            self._progress_fail(
                f"{INSTALL_STEP_LABEL.get(tag, tag)} failed: {detail}".strip()
            )
            return
        if tag in INSTALL_STEP_PROGRESS:
            self._progress_set(INSTALL_STEP_PROGRESS[tag],
                               INSTALL_STEP_LABEL.get(tag, tag))

    def log(self, text):
        """Append one console line with a semantic transport colour."""
        message = str(text)
        lowered = message.lower()
        if any(token in lowered for token in (
            "error", "failed", "failure", "denied", "traceback", "fault",
        )):
            colour = "#f31260"  # error / failed operation
        elif any(token in lowered for token in (
            "warning", "warn", "incomplete", "could not", "timeout",
        )):
            colour = "#f5a524"  # warning / incomplete result
        elif any(token in lowered for token in (
            "success", "complete", "ready", "ssh ok", "exited with 0",
            "landed",
        )):
            colour = "#17c964"  # completed / healthy result
        else:
            colour = "#a1a1aa"  # ordinary transport information

        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))
        cursor.setCharFormat(fmt)
        cursor.insertText(message + "\n")
        # scroll to bottom
        vbar = self.console.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def ssh_port(self) -> int:
        """Return the SSH port to use, falling back to 22.

        Returns:
            The port from the connection form, or 22 when the field is empty
            or not a number.

        Every call site used to pass a literal 22 even though build_ssh_cmd
        takes a port and the host CLI exposes -P, so a panel reachable only on
        a non-standard port could not be deployed to from this tool at all.
        """
        raw = self.inp_port.text().strip()
        if not raw.isdigit():
            return 22
        port = int(raw)
        return port if 1 <= port <= 65535 else 22

    def save_settings(self):
        self.settings.setValue("host", self.inp_host.text().strip())
        self.settings.setValue("user", self.inp_user.text().strip())
        self.settings.setValue("port", self.ssh_port())
        self.settings.setValue("key", self.inp_key.text().strip())

    def on_test_conn(self):
        self.save_settings()
        self.log("Testing connection...")
        self.device_panel.set_led_state(2)  # deploying (amber)
        self._set_link_state("connecting")
        # The geometry on screen belongs to the previous panel until this
        # attempt reports one of its own. Saying so beats showing a resolution
        # that may belong to a board no longer on the other end of the cable.
        self.lbl_target_resolution.setText("Probing the connected display...")
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(),
            self.inp_user.text().strip(),
            self.ssh_port(),
            self.inp_key.text().strip(),
            # Status already reports the active release and GUI readiness. Keep
            # this connection survey short; disk details live in Memory Profile.
            "echo 'SSH OK'; hmi-install status; " + DISPLAY_PROBE_COMMAND
        )

        def on_test_finished(code):
            # Only when the operator is looking at the profile. Measuring the
            # compressed size of a release means re-compressing it, which on
            # this hardware is a minute of one core at 100% for a 300 MB app --
            # long enough that the next Test Connection times out behind it.
            # Nobody asked for that by pressing Connect.
            if code == 0 and self._right_tabs.currentWidget() is self._profile_page:
                self.refresh_memory_profile()

        self.run_ssh_worker(
            cmd,
            "Test Connection",
            callback=on_test_finished,
            timeout_s=SSH_TEST_TIMEOUT_S,
            line_hook=self._record_detected_resolution,
        )

    def run_upload_worker(self, cmd, local_path, total_bytes, desc, callback=None,
                          timeout_s=DEFAULT_SSH_TIMEOUT_S):
        """
        Streams a file to the panel, driving the progress bar from bytes sent.

        Args:
            cmd: argv that consumes the file on stdin (build_upload_cmd).
            local_path: the file to send.
            total_bytes: its size, for the percentage.
            desc: label used in the console.
            callback: called with the exit code on completion.
            timeout_s: watchdog for the whole transfer.

        Side effects: same worker-lifetime handling as run_ssh_worker.
        """
        self.btn_deploy.setEnabled(False)
        started = time.monotonic()
        worker = UploadWorker(cmd, local_path, timeout_s=timeout_s, parent=self)
        self._ssh_workers.append(worker)
        self._last_transport_line = ""
        worker.outputLine.connect(self.log)
        worker.outputLine.connect(self._record_transport_line)
        worker.error.connect(self._record_transport_line)

        span = PROGRESS_UPLOAD_END - PROGRESS_UPLOAD_START

        def on_progress(sent, total):
            if not total:
                return
            fraction = sent / total
            self._progress_set(
                PROGRESS_UPLOAD_START + fraction * span,
                f"Uploading {sent / (1024 * 1024):.1f} / "
                f"{total / (1024 * 1024):.1f} MB "
                f"({sent / max(time.monotonic() - started, 1e-6) / 1024:.0f} KB/s)",
            )

        worker.progress.connect(on_progress)

        def on_finished(code):
            elapsed = time.monotonic() - started
            self.log(f"{desc} exited with {code} ({elapsed:.0f}s)")
            if code != 0:
                self.device_panel.set_led_state(3)
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            worker.wait(2000)
            if worker in self._ssh_workers:
                self._ssh_workers.remove(worker)
            if callback:
                callback(code)

        worker.finished.connect(on_finished)
        worker.error.connect(self.log)
        worker.start()

    def run_ssh_worker(self, cmd, desc, callback=None, timeout_s=DEFAULT_SSH_TIMEOUT_S,
                       heartbeat_s=0, line_hook=None):
        """
        Runs one SSH/SCP command off the UI thread and reports its exit code.

        Args:
            cmd: the argv list to execute.
            desc: human label used in the console and in the LED logic.
            callback: called with the exit code once the command completes,
                after the console line has been written. A deploy is a chain of
                these, so a step that drops its callback silently ends the
                deployment -- see on_deploy.
            timeout_s: watchdog for this specific command. One value cannot fit
                every step: a mkdir answers instantly, an scp of a large bundle
                takes minutes, and `hmi-install install` deliberately blocks for
                up to GUI_READY_TIMEOUT (25 s) waiting for the panel to render.
            heartbeat_s: when non-zero, write a console line every this many
                seconds for as long as the command runs. scp prints its progress
                meter only to a terminal, so a multi-minute upload through a
                pipe produces no output at all until it finishes -- which reads
                as a hang, and has been reported as one. A step that says how
                long it has been running is the difference between "working"
                and "frozen".
            line_hook: called with every output line, in addition to the
                console. The install step uses it to drive the progress bar
                from the installer's own STEP output.

        Side effects: disables the deploy button for the duration, keeps the
        worker referenced until its thread has actually finished.
        """
        self.btn_deploy.setEnabled(False)
        started = time.monotonic()
        worker = SshWorker(cmd, timeout_s=timeout_s, parent=self)
        # Hold a strong reference for the lifetime of the thread. Overwriting a
        # single self.ssh_worker attribute -- which is what the chained deploy
        # does, four times in a row -- dropped the last reference to a QThread
        # that had emitted finished() but not yet returned from run(), and Qt
        # aborts the process when a running QThread is destroyed.
        self._ssh_workers.append(worker)
        self.ssh_worker = worker
        self._last_transport_line = ""
        worker.outputLine.connect(self.log)
        worker.outputLine.connect(self._record_transport_line)
        worker.error.connect(self._record_transport_line)
        if line_hook is not None:
            worker.outputLine.connect(line_hook)

        pulse = None
        if heartbeat_s > 0:
            pulse = QTimer(self)
            pulse.setInterval(heartbeat_s * 1000)
            pulse.timeout.connect(
                lambda: self.log(
                    f"  {desc}: {time.monotonic() - started:.0f}s elapsed"
                    f"{self._heartbeat_detail(desc)}..."
                )
            )
            pulse.start()

        def on_finished(code):
            if pulse is not None:
                pulse.stop()
            elapsed = time.monotonic() - started
            self.log(f"{desc} exited with {code} ({elapsed:.0f}s)")
            if code == 0:
                self.device_panel.set_led_state(1)  # Link up
                if desc == "Test Connection":
                    self._set_link_state("connected")
                if hasattr(self, "lbl_connection"):
                    self.lbl_connection.setText("●  LINK ESTABLISHED")
                    self.lbl_connection.setProperty("state", "connected")
                    self.lbl_connection.style().unpolish(self.lbl_connection)
                    self.lbl_connection.style().polish(self.lbl_connection)
                if desc == "Test Connection":
                    self.start_relay()
            else:
                self.device_panel.set_led_state(3)  # Fault
                if desc == "Test Connection":
                    self._set_link_state("fault")
                    # Nothing answered, so nothing reported a display. Leaving
                    # the previous panel's geometry up reads as a live value.
                    if self.detected_resolution is None:
                        self.lbl_target_resolution.setText("Not detected")
                    else:
                        width, height = self.detected_resolution
                        self.lbl_target_resolution.setText(
                            f"{width} x {height} px (last seen; not connected)"
                        )
                if hasattr(self, "lbl_connection"):
                    self.lbl_connection.setText("●  CONNECTION FAULT")
                    self.lbl_connection.setProperty("state", "fault")
                    self.lbl_connection.style().unpolish(self.lbl_connection)
                    self.lbl_connection.style().polish(self.lbl_connection)
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            # run() emits this as its last act, so the thread is at most
            # microseconds from returning; the bounded wait keeps the object
            # alive across that window without stalling the UI.
            worker.wait(2000)
            if worker in self._ssh_workers:
                self._ssh_workers.remove(worker)
            if callback:
                callback(code)

        worker.finished.connect(on_finished)
        worker.error.connect(self.log)
        worker.start()

    def _heartbeat_detail(self, desc: str) -> str:
        """
        Name what the panel last reported, so a long wait is not a blank one.

        Args:
            desc: the step label the worker was given.

        Returns:
            A clause for the heartbeat line, or "" when there is nothing to add.

        An install that takes two minutes on a loaded panel used to print
        nothing but a rising number, which reads as a hang -- especially once
        the application is visibly up on the panel and the tool still appears
        to be waiting for something.
        """
        if desc != "Install":
            return ""
        step = getattr(self, "_last_install_step", "")
        return f" (last step: {step})" if step else ""

    def _discard_packaging_dir(self, path: str = "") -> None:
        """Remove the temp directory holding a deployment's tarball.

        Args:
            path: the directory to remove. Defaults to the one this window
                currently records, which is only correct when the caller knows
                no newer deploy has started.

        Returns: nothing
        Side effects: deletes the directory tree, and forgets it if it is the
            one on record.
        Never raises: failing to tidy up must not fail or interrupt a deploy.

        Every deploy names the directory it created. A deploy step that
        finishes late -- an install whose watchdog fired minutes ago, say --
        used to delete whatever directory was on record at the moment it ran,
        which by then belonged to the deploy that replaced it: the tarball
        uploaded, and its checksum was gone before it could follow.
        """
        target = path or getattr(self, "_packaging_dir", None)
        if not target:
            return
        if getattr(self, "_packaging_dir", None) == target:
            self._packaging_dir = None
        try:
            import shutil
            shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass

    def on_deploy(self):
        """
        Packages the loaded bundle and installs it on the panel.

        Packaging runs on a worker thread; the rest is three SSH/SCP steps
        chained through completion callbacks: upload tarball (which creates the
        landing directory) -> scp checksum -> hmi-install install. Each step
        only starts once the previous one has exited 0, so a failure anywhere
        stops the deployment with the failing step named in the console.
        """
        self.save_settings()
        self.log(f"Deploying {self.bundle_dir}...")
        # _progress_begin() bumps the generation, so everything below belongs
        # to this attempt.
        self._progress_begin()
        # Nothing else disables the button until the first SSH step starts, and
        # the checks before it take seconds.
        self.btn_deploy.setEnabled(False)
        self._start_dependency_scan()

    # ------------------------------------------------------------------
    # Dependency pre-flight
    # ------------------------------------------------------------------

    def _start_dependency_scan(self) -> None:
        """Read what the application imports, off the UI thread."""
        self._progress_busy("Reading the application's imports...")
        worker = DependencyWorker(self.bundle_dir, parent=self)
        self._dep_worker = worker
        worker.done.connect(self._on_deps_scanned)
        worker.failed.connect(self._on_dep_scan_failed)
        worker.start()

    def _release_dep_worker(self) -> None:
        """Let go of the scanning thread once it has reported."""
        worker = getattr(self, "_dep_worker", None)
        if worker is not None:
            worker.wait(2000)
            self._dep_worker = None

    def _qt_binding(self) -> str:
        """Return the binding this bundle runs under, defaulting to PySide6."""
        return (self.current_manifest or {}).get("qt_binding", "pyside6")

    def _on_dep_scan_failed(self, message: str) -> None:
        """A scan is a convenience; never let it stop a deploy that would work."""
        self._release_dep_worker()
        self.log(f"Could not read the application's imports: {message}")
        self._begin_packaging()

    def _on_deps_scanned(self, pairs) -> None:
        """Ask the panel whether it can import everything the bundle needs."""
        self._release_dep_worker()
        self._dependencies = [(str(m), str(d)) for m, d in pairs]
        if not self._dependencies:
            self.log("Dependencies: nothing beyond the standard library and Qt.")
            self._begin_packaging()
            return

        listed = ", ".join(
            module if module == distribution else f"{module} ({distribution})"
            for module, distribution in self._dependencies
        )
        self.log(f"Dependencies this app imports: {listed}")
        self._progress_busy("Checking dependencies on the panel...")
        self._deps_missing = []
        self.run_ssh_worker(
            build_ssh_cmd(
                self.inp_host.text().strip(), self.inp_user.text().strip(),
                self.ssh_port(), self.inp_key.text().strip(),
                build_dep_check_command(
                    [module for module, _ in self._dependencies], self._qt_binding()
                ),
            ),
            "Dependencies", self._on_deps_checked, timeout_s=SSH_TEST_TIMEOUT_S,
            line_hook=self._note_dep_line,
        )

    def _note_dep_line(self, line: str) -> None:
        """Collect the per-module verdicts from the panel's reply."""
        parts = line.split()
        if len(parts) == 3 and parts[0] == "DEP" and parts[2] == "missing":
            self._deps_missing.append(parts[1])

    def _on_deps_checked(self, code: int) -> None:
        """Decide what to do about anything the panel could not import."""
        if code != 0:
            # An unreachable panel will be reported again, in the same words,
            # by the upload; there is nothing useful to add here.
            self.log("Could not check the panel's packages; continuing anyway.")
            self._begin_packaging()
            return

        if not self._deps_missing:
            self.log("Dependencies: the panel has all of them.")
            self._begin_packaging()
            return

        wanted = [
            distribution
            for module, distribution in self._dependencies
            if module in self._deps_missing
        ]
        self.log(f"Dependencies missing on the panel: {', '.join(wanted)}")

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Packages missing on the panel")
        box.setText(
            f"The panel cannot import {len(wanted)} package(s) this application "
            "needs:\n\n    " + "\n    ".join(wanted) + "\n\n"
            "Deployed as it is, the application will fail on its first import "
            "and the panel will roll back."
        )
        box.setInformativeText("Install them on the panel now?")
        install = box.addButton("Install and deploy", QMessageBox.AcceptRole)
        anyway = box.addButton("Deploy anyway", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(install)
        box.exec()
        clicked = box.clickedButton()

        if clicked is anyway:
            self.log("Deploying without the missing packages, at your request.")
            self._begin_packaging()
            return
        if clicked is not install:
            self.log("Deployment cancelled.")
            self._progress_cancel("Cancelled -- packages missing on the panel.")
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            return

        self._pip_failed = []
        self._pip_done = 0
        self._pip_total = len(wanted)
        self._progress_busy(f"Installing {self._pip_total} package(s) on the panel...")
        self.log(f"Installing on the panel: {', '.join(wanted)}")
        self.run_ssh_worker(
            build_ssh_cmd(
                self.inp_host.text().strip(), self.inp_user.text().strip(),
                self.ssh_port(), self.inp_key.text().strip(),
                build_dep_install_command(wanted, self._qt_binding()),
            ),
            "Install packages", self._on_deps_installed,
            timeout_s=DEP_INSTALL_TIMEOUT_S, heartbeat_s=10,
            line_hook=self._note_pip_line,
        )

    def _note_pip_line(self, line: str) -> None:
        """Drive the stage line from pip's progress through the list."""
        text = line.strip()
        if text.startswith("PIP_START "):
            self._pip_done += 1
            name = text.split(None, 1)[1]
            self._progress_busy(
                f"Installing {name} ({self._pip_done} of {self._pip_total})..."
            )
        elif text.startswith("PIP_FAIL "):
            self._pip_failed.append(text.split(None, 1)[1])

    def _on_deps_installed(self, code: int) -> None:
        """Re-import packages after pip; installed does not mean loadable."""
        if code == 0 and not self._pip_failed:
            self.log("Package installation finished; verifying imports...")
            self._deps_missing = []
            self.run_ssh_worker(
                build_ssh_cmd(
                    self.inp_host.text().strip(), self.inp_user.text().strip(),
                    self.ssh_port(), self.inp_key.text().strip(),
                    build_dep_check_command(
                        [module for module, _ in self._dependencies], self._qt_binding()
                    ),
                ),
                "Verify packages", self._on_deps_rechecked,
                timeout_s=SSH_TEST_TIMEOUT_S, line_hook=self._note_dep_line,
            )
            return

        names = ", ".join(self._pip_failed) or "the packages"
        self._progress_fail(f"Could not install {names} on the panel.")
        self.log(
            "The console above has pip's own output. A panel with no route to "
            "an index needs the packages installed by hand; deploying without "
            "them would only crash-loop and roll back."
        )
        self.btn_deploy.setEnabled(self.bundle_dir is not None)

    def _on_deps_rechecked(self, code: int) -> None:
        """Package only when every dependency imports after installation."""
        if code == 0 and not self._deps_missing:
            self.log(f"Installed and verified {self._pip_total} package(s) on the panel.")
            self._begin_packaging()
            return
        names = ", ".join(self._deps_missing) or "the installed packages"
        self._progress_fail(f"The panel still cannot import {names} after installation.")
        self.log(
            "Installation did not make the package importable. This usually means "
            "a native shared library required by the Python package is absent."
        )
        self.btn_deploy.setEnabled(self.bundle_dir is not None)

    def _begin_packaging(self) -> None:
        """Pack the bundle for upload, on a worker thread."""
        import tempfile

        try:
            out_dir = tempfile.mkdtemp(prefix="hmi-deploy-")
        except Exception as e:
            self._progress_fail(f"Could not start the deployment: {e}")
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            return


        # The previous deploy's tarball is discarded by the same worker rather
        # than here: it is up to 500 MB, and deleting it inline is one more
        # stall on the thread that has to keep the window alive. Every deploy
        # used to leave its tarball behind, and a working session is many
        # deploys.
        discard = getattr(self, "_packaging_dir", None) or ""
        self._packaging_dir = out_dir
        self._packaging_generation = self._deploy_generation

        self._package_started = time.monotonic()
        self._progress_busy("Packaging bundle...")
        self.log("Packaging bundle (large applications take a few seconds)...")
        self._package_pulse = QTimer(self)
        self._package_pulse.setInterval(1000)
        self._package_pulse.timeout.connect(self._on_package_tick)
        self._package_pulse.start()

        worker = PackageWorker(self.bundle_dir, out_dir, discard, parent=self)
        self._package_worker = worker
        worker.done.connect(self._on_packaged)
        worker.failed.connect(self._on_package_failed)
        worker.start()

    def _on_package_tick(self) -> None:
        """Keep the stage line counting, so a long pack still looks alive."""
        elapsed = time.monotonic() - self._package_started
        self.lbl_stage.setText(f"Packaging bundle... ({elapsed:.0f}s)")

    def _release_package_worker(self) -> None:
        """Stop the elapsed counter and let go of the packaging thread."""
        pulse = getattr(self, "_package_pulse", None)
        if pulse is not None:
            pulse.stop()
            self._package_pulse = None
        worker = getattr(self, "_package_worker", None)
        if worker is not None:
            # Emitted as run()'s last act, so the thread is microseconds from
            # returning; Qt aborts the process if it is destroyed still running.
            worker.wait(2000)
            self._package_worker = None

    def _on_packaged(self, tar_path: str, sha256_path: str) -> None:
        """Packaging succeeded: report the artefact and start the upload."""
        self._release_package_worker()
        if self._packaging_generation != self._deploy_generation:
            # A newer deploy owns the window; this tarball is nobody's.
            self._discard_packaging_dir(os.path.dirname(tar_path))
            return
        tar_size = os.path.getsize(tar_path)
        self.log(
            f"Packaged to {tar_path} ({tar_size / (1024 * 1024):.1f} MB) "
            f"in {time.monotonic() - self._package_started:.0f}s"
        )
        self._progress_set(
            PROGRESS_PACKAGED,
            f"Packaged {tar_size / (1024 * 1024):.1f} MB",
        )
        self._start_upload(tar_path, sha256_path, tar_size)

    def _on_package_failed(self, kind: str, message: str) -> None:
        """Packaging failed: say why, and leave nothing behind."""
        self._release_package_worker()
        if self._packaging_generation != self._deploy_generation:
            return
        self._discard_packaging_dir()
        if kind == "too-large":
            self._progress_fail("Bundle is too large for the panel.")
            self.log(message)
            QMessageBox.critical(self, "Bundle too large", message)
        else:
            self._progress_fail(f"Could not package the bundle: {message}")
        self.btn_deploy.setEnabled(self.bundle_dir is not None)

    def _start_upload(self, tar_path: str, sha256_path: str, tar_size: int) -> None:
        """
        Sends the packaged bundle to the panel and installs it.

        Args:
            tar_path: the packaged bundle.
            sha256_path: its checksum sidecar.
            tar_size: the tarball's size, for the timeout and the throughput
                line.
        """
        try:
            host = self.inp_host.text().strip()
            user = self.inp_user.text().strip()
            key = self.inp_key.text().strip()

            # This attempt's own state, captured rather than read back later:
            # by the time a step returns, the window may belong to a newer one.
            generation = self._deploy_generation
            packaging_dir = os.path.dirname(tar_path)

            def superseded() -> bool:
                """True once a later deploy has taken over the window."""
                return generation != self._deploy_generation

            # Upload allowance scaled to the payload. A slow panel link moving a
            # large bundle is normal, not a hang; a fixed short timeout would
            # kill the transfer partway and leave a truncated file in the tmpfs.
            scp_timeout = SCP_BASE_TIMEOUT_S + int(tar_size / SCP_MIN_BYTES_PER_S)

            # Step 1: upload the bundle. The upload command creates
            # /tmp/hmi_upload itself, so the transfer is the first thing that
            # touches the panel.
            from .ssh import build_scp_cmd
            tar_name = os.path.basename(tar_path)

            def on_upload(code):
                if superseded():
                    return
                if code != 0:
                    self._discard_packaging_dir(packaging_dir)
                    self._progress_fail(self._transport_failure("the bundle upload", code))
                    return
                elapsed = max(time.monotonic() - self._upload_started, 1e-6)
                self.log(
                    f"Uploaded {tar_size / (1024 * 1024):.1f} MB in {elapsed:.0f}s "
                    f"({tar_size / elapsed / 1024:.0f} KB/s)."
                )
                self._progress_set(PROGRESS_UPLOAD_END, "Uploading checksum...")
                cmd_scp2 = build_scp_cmd(host, user, self.ssh_port(), key, sha256_path, "/tmp/hmi_upload/")
                self.run_ssh_worker(cmd_scp2, "SCP sha256", on_scp2, timeout_s=SSH_SHORT_TIMEOUT_S)

            def on_scp2(code):
                if superseded():
                    return
                if code != 0:
                    self._discard_packaging_dir(packaging_dir)
                    self._progress_fail(self._transport_failure("the checksum upload", code))
                    return
                self._progress_set(PROGRESS_INSTALL_START, "Installing on the panel...")
                cmd_install = build_ssh_cmd(host, user, self.ssh_port(), key, f"hmi-install install /tmp/hmi_upload/{tar_name}")
                # The installer blocks for up to its own GUI_READY_TIMEOUT
                # waiting for the panel to render, then may roll back and
                # restart again, so it needs far more headroom than a shell
                # command that answers immediately.
                self.run_ssh_worker(
                    cmd_install, "Install", on_install,
                    timeout_s=INSTALL_TIMEOUT_S, heartbeat_s=5,
                    line_hook=self._on_install_line,
                )

            def on_install(code):
                if superseded():
                    # Still clean up after ourselves; just do not report.
                    self._discard_packaging_dir(packaging_dir)
                    return
                self._discard_packaging_dir(packaging_dir)
                if code == 0 and not self._deploy_failed:
                    self.log("Deployment complete.")
                    self._progress_succeed()
                    self.start_relay()
                    return
                if not self._deploy_failed:
                    # A non-zero exit with no failing STEP line: either the
                    # installer died before it could report which stage broke,
                    # or the connection carrying it did.
                    if code in (-1, 255):
                        self._progress_fail(self._transport_failure("the install", code))
                    else:
                        self._progress_fail(
                            f"hmi-install exited {code}. See the console for the last step reached."
                        )
                if code in (-1, 255):
                    # The installer did not get to say what it did. It may have
                    # finished, and it may have swapped the symlink and died
                    # before the health check could undo it. The panel knows.
                    self._recover_interrupted_install(
                        host, user, key, tar_name[: -len(".tar.gz")]
                    )
                    return
                self.start_relay()

            self.log(
                f"Uploading {tar_size / (1024 * 1024):.1f} MB to {user}@{host} "
                f"(allowing up to {scp_timeout}s)..."
            )
            self._progress_set(PROGRESS_UPLOAD_START, "Uploading bundle...")
            self._upload_started = time.monotonic()
            self.run_upload_worker(
                build_upload_cmd(host, user, self.ssh_port(), key, f"/tmp/hmi_upload/{tar_name}"),
                tar_path, tar_size, "Upload", on_upload, timeout_s=scp_timeout,
            )

        except Exception as e:
            self._discard_packaging_dir(os.path.dirname(tar_path))
            self._progress_fail(f"Could not start the deployment: {e}")
            self.btn_deploy.setEnabled(self.bundle_dir is not None)

    def _recover_interrupted_install(
        self, host: str, user: str, key: str, release: str = ""
    ) -> None:
        """
        Find out what a cut-off install actually left on the panel.

        Args:
            host, user, key: the same target the install was sent to.
            release: the release directory this deploy was creating, so the
                answer can distinguish "it landed" from "something landed".

        The panel decides. If its GUI is up on the release we sent, the deploy
        succeeded and only the reporting was lost -- which is what a busy panel
        plus a client-side watchdog produces, and telling the operator it
        failed would send them to re-deploy something already running. If the
        GUI is not up, the panel rolls itself back.
        """
        self.log("Install was cut off -- asking the panel what state it is in...")
        self._recovered = ""
        self._recovered_release = ""

        def note(line: str) -> None:
            if "HMI_RECOVER=" in line:
                self._recovered = line.split("HMI_RECOVER=", 1)[1].strip()
            elif "HMI_CURRENT=" in line:
                self._recovered_release = line.split("HMI_CURRENT=", 1)[1].strip()

        def done(code: int) -> None:
            landed = release and self._recovered_release == release
            if self._recovered == "ok" and landed:
                self.log(
                    f"The panel is running {self._recovered_release} and is ready: "
                    "the deployment landed, only its final report was lost."
                )
                self._deploy_failed = False
                self._progress_succeed()
            elif self._recovered == "ok":
                self.log(
                    f"The panel is running and ready on {self._recovered_release or 'its current release'}; "
                    "nothing to undo."
                )
            elif self._recovered == "rollback":
                self.log("The panel was rolled back to the previous release.")
                self._progress_fail(
                    "Install did not finish; the panel was rolled back to the "
                    "previous release."
                )
            else:
                self.log(
                    "Could not confirm the panel's state. Check it with "
                    "Connect / Test before deploying again."
                )
            self.start_relay()

        self.run_ssh_worker(
            build_ssh_cmd(host, user, self.ssh_port(), key, INSTALL_RECOVERY_COMMAND),
            "Recover", done, timeout_s=INSTALL_TIMEOUT_S, line_hook=note,
        )

    def on_rollback(self):
        self.save_settings()
        self.log("Rolling back to previous release...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, self.ssh_port(), key, "hmi-install rollback")
        # Rollback restarts the GUI on its way out, so it is not instant.
        self.run_ssh_worker(cmd, "Rollback", timeout_s=INSTALL_TIMEOUT_S)

    # ------------------------------------------------------------------
    # Panel logs
    # ------------------------------------------------------------------

    def on_toggle_logs(self) -> None:
        """Start or stop following the panel's journal."""
        if self._log_worker is not None:
            self.stop_logs()
            return

        self.save_settings()
        self._log_lines = []
        self.logs_view.setPlaceholderText("Waiting for the panel...")
        self._render_logs()

        cmd = build_ssh_cmd(
            self.inp_host.text().strip(), self.inp_user.text().strip(),
            self.ssh_port(), self.inp_key.text().strip(),
            build_logs_command(LOG_HISTORY_LINES, follow=True),
        )
        # A follow has no natural end, so the ordinary watchdog would kill it
        # mid-stream. SshWorker is used directly rather than through
        # run_ssh_worker: this must not disable the deploy button, must not
        # touch the link badge, and must not write the journal into the deploy
        # console.
        worker = SshWorker(cmd, timeout_s=LOG_FOLLOW_TIMEOUT_S, parent=self)
        self._log_worker = worker
        worker.outputLine.connect(self._on_log_line)
        worker.error.connect(self._on_log_error)
        worker.finished.connect(self._on_logs_finished)
        worker.start()

        self.btn_logs_follow.setText("Stop Following")
        self.log("Following the panel's journal.")

    def stop_logs(self) -> None:
        """Cancel the follow, if one is running."""
        worker = self._log_worker
        if worker is None:
            return
        self._log_worker = None
        try:
            worker.cancel()
            worker.wait(2000)
        except RuntimeError:
            pass
        self.btn_logs_follow.setText("Start Following")

    def _on_log_line(self, line: str) -> None:
        """Keep one journal line, bounded so a long follow cannot grow forever."""
        self._log_lines.append(line)
        if len(self._log_lines) > LOG_BUFFER_LINES:
            del self._log_lines[: len(self._log_lines) - LOG_BUFFER_LINES]
        self._render_logs()

    def _on_log_error(self, message: str) -> None:
        """Report a follow that could not run, in the log view itself."""
        self._log_lines.append(f"[studio] {message}")
        self._render_logs()

    def _on_logs_finished(self, code: int) -> None:
        """The stream ended: the panel dropped, or the user stopped it.

        The thread is waited on before the reference is let go. run() emits
        this as its last act, so it is microseconds from returning -- but
        dropping the last reference inside that window destroys a QThread that
        is still running, and Qt aborts the process when that happens. Every
        other worker in this window is released the same way; this one was not,
        which made it the one shaped like the crash the codebase already
        documents.
        """
        worker = self._log_worker
        if worker is not None:
            self._log_lines.append(f"[studio] journal stream ended (exit {code})")
            self._render_logs()
            worker.wait(2000)
        self._log_worker = None
        self.btn_logs_follow.setText("Start Following")

    def on_clear_logs(self) -> None:
        """Empty the view without stopping the follow."""
        self._log_lines = []
        self._render_logs()

    def _render_logs(self) -> None:
        """Paint the buffer through the filter, staying pinned to the tail.

        Rewriting the whole document keeps filtering and following the same
        operation: typing a filter re-reads history rather than only applying
        to lines that arrive next.
        """
        needle = self.inp_log_filter.text().strip().lower()
        lines = (
            [line for line in self._log_lines if needle in line.lower()]
            if needle else self._log_lines
        )
        scrollbar = self.logs_view.verticalScrollBar()
        at_tail = scrollbar.value() >= scrollbar.maximum() - 4
        self.logs_view.setPlainText("\n".join(lines))
        if at_tail:
            scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # Installed releases
    # ------------------------------------------------------------------

    def refresh_releases(self) -> None:
        """Ask the panel which releases it still holds."""
        self.save_settings()
        self._releases = []
        self.btn_refresh_releases.setEnabled(False)
        self.log("Listing releases on the panel...")
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(), self.inp_user.text().strip(),
            self.ssh_port(), self.inp_key.text().strip(),
            build_release_list_command(),
        )

        def on_finished(code):
            self.btn_refresh_releases.setEnabled(True)
            self._render_releases(code == 0)

        self.run_ssh_worker(
            cmd, "List Releases", callback=on_finished,
            timeout_s=SSH_SHORT_TIMEOUT_S,
            line_hook=self._record_release_line,
        )

    def _record_release_line(self, line: str) -> None:
        """Collect one release row from the panel's listing."""
        release = parse_release_line(line)
        if release is not None:
            self._releases.append(release)

    def _render_releases(self, ok: bool) -> None:
        """Put the panel's releases in the picker, newest first.

        The listing arrives in directory order; release names carry a UTC
        timestamp suffix, so sorting by name descending is newest first and
        puts the release most likely to be wanted at the top.
        """
        self.cmb_releases.clear()
        if not ok or not self._releases:
            self.cmb_releases.addItem(
                "No releases listed" if ok else "Could not list releases"
            )
            self.cmb_releases.setEnabled(False)
            self.btn_activate.setEnabled(False)
            return

        for release in sorted(self._releases, key=lambda r: r.name, reverse=True):
            self.cmb_releases.addItem(release.label(), release.name)
            if release.is_current:
                self.cmb_releases.setCurrentIndex(self.cmb_releases.count() - 1)

        self.cmb_releases.setEnabled(True)
        self.btn_activate.setEnabled(True)
        self.log(f"Panel holds {len(self._releases)} release(s).")

    def on_activate_release(self) -> None:
        """Re-point the panel at the selected release."""
        release = self.cmb_releases.currentData()
        if not release:
            return

        current = next((r.name for r in self._releases if r.is_current), "")
        if release == current:
            self.log(f"{release} is already running on the panel.")
            return

        answer = QMessageBox.question(
            self,
            "Activate release?",
            f"Point the panel at this release and restart the GUI?\n\n"
            f"  {release}\n\n"
            f"The release running now ({current or 'none'}) becomes the "
            f"rollback target, so this is undoable with Rollback.\n\n"
            f"Unlike a deploy, an activated release is not health-checked: it "
            f"is not rolled back automatically if it fails to render.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.log("Activation cancelled.")
            return

        self.save_settings()
        self.log(f"Activating {release}...")
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(), self.inp_user.text().strip(),
            self.ssh_port(), self.inp_key.text().strip(),
            build_activate_command(release),
        )
        # Activation restarts the GUI on its way out, as rollback does.
        self.run_ssh_worker(
            cmd, "Activate Release",
            callback=lambda code: self.refresh_releases() if code == 0 else None,
            timeout_s=INSTALL_TIMEOUT_S,
        )

    def on_restart(self):
        self.save_settings()
        self.log("Restarting GUI...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, self.ssh_port(), key, "systemctl restart hmi-gui.service")
        self.run_ssh_worker(cmd, "Restart GUI", timeout_s=SSH_SHORT_TIMEOUT_S)

    def _shutdown_transport(self) -> None:
        """
        End every SSH session this window owns.

        Stopping the senders covers the telemetry relay; the rest of the list
        is whatever deploy or diagnostic step was still in flight. Each one is
        a live session on the panel, and the panel's socket-activated dropbear
        serves 64 at a time and drops every connection past that, so sessions
        left running by a closing window are eventually paid for by a deploy
        that cannot connect at all.

        Never raises: this runs on the way out, and a failure here would only
        replace a clean exit with a crash.
        """
        # The journal follow is a live ssh session like any other, and it is
        # the one most likely to still be open: it runs until stopped.
        try:
            self.stop_logs()
        except Exception:
            pass
        try:
            self._stop_all_senders()
        except Exception:
            pass
        for worker in list(self._ssh_workers):
            try:
                worker.cancel()
                if worker.isRunning():
                    worker.wait(2000)
            except Exception:
                pass
        # Packaging cannot be interrupted safely part-way through a tarball, so
        # it is waited out rather than cancelled; Qt aborts the process if the
        # thread is destroyed while it still runs.
        for name, grace in (("_package_worker", 10000), ("_dep_worker", 10000)):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if worker.isRunning():
                    worker.wait(grace)
            except Exception:
                pass

    def closeEvent(self, event):
        """Release every local/remote telemetry source before closing."""
        self._shutdown_transport()
        self._discard_packaging_dir()
        self.device_panel.stop_preview()
        super().closeEvent(event)
