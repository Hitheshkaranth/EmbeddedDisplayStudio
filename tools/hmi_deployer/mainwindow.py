"""
tools/hmi_deployer/mainwindow.py
Layer: 3 (Host Deployer)
Purpose: Main application window, layout, actions, and state machine.
"""
import os
import json
import time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QApplication,
    QSplitter, QGroupBox, QFormLayout, QLineEdit, QProgressBar,
    QPlainTextEdit, QFileDialog, QMessageBox, QTabWidget
)
from PySide6.QtCore import Qt, QSettings, QTimer
from .devicepanel import DevicePanel, PANEL_PRESETS
from .deployer import (
    BundleTooLargeError, validate_bundle, package_bundle, detect_bundle,
    detect_qt_binding, write_manifest,
)
from .telemetry import TelemetrySimulator, TelemetryRelay
from .ssh import SshWorker, UploadWorker, build_ssh_cmd, build_upload_cmd
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
APP_VERSION = "0.0.1"

# ---- SSH step budgets -------------------------------------------------------
# One timeout cannot serve every step of a deploy: the commands differ in cost
# by three orders of magnitude. Each is a watchdog, not an expectation.

# Commands that answer immediately (mkdir, a checksum file, rollback, restart).
SSH_SHORT_TIMEOUT_S = 30

# Fallback for callers that do not say what they are running.
DEFAULT_SSH_TIMEOUT_S = 60

# `hmi-install install` waits up to GUI_READY_TIMEOUT (25 s) for the panel to
# render, and on failure rolls back and restarts again before it exits.
INSTALL_TIMEOUT_S = 180

# Bundle upload: a fixed allowance plus time proportional to the payload. The
# floor rate is deliberately pessimistic (256 KiB/s) so a slow or congested
# field link is not mistaken for a hang.
SCP_BASE_TIMEOUT_S = 60
SCP_MIN_BYTES_PER_S = 256 * 1024

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
        self.setWindowTitle("EmbeddedDisplay")
        self.resize(1280, 800)
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
        self.ssh_worker = None
        # Every SSH/SCP worker still running. A deploy chains four of them, and
        # a QThread destroyed while running takes the process down with it.
        self._ssh_workers = []
        # When the current bundle upload began, for the throughput line.
        self._upload_started = 0.0
        # Set once a deploy has failed, so later steps cannot paint over it.
        self._deploy_failed = False

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
            app.aboutToQuit.connect(self._stop_all_senders)

        if self.bundle_dir and os.path.isdir(self.bundle_dir):
            self.load_bundle(self.bundle_dir)

        if self.exit_after_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(self.exit_after_ms, self.close)

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
        logging.getLogger("EmbeddedDisplay").info(
            "theme=%s stylesheet=%d chars", self.theme, len(app.styleSheet() or "")
        )

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # Top Bar
        top_bar = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton, QLabel
        from PySide6.QtGui import QPixmap

        # Product mark. Rendered from the 128 px asset and scaled to 28 px so it
        # stays crisp on HiDPI displays, where Qt asks for 2x the logical size.
        logo_path = os.path.join(os.path.dirname(__file__), "resources", "logo_128.png")
        self.lbl_logo = QLabel()
        self.lbl_logo.setPixmap(
            QPixmap(logo_path).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.lbl_logo.setFixedSize(28, 28)

        # Wordmark beside the logo, in the design system's heading style.
        self.lbl_title = QLabel("EmbeddedDisplay")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: 600; letter-spacing: -0.4px;")

        self.btn_open = QPushButton("Open Bundle...")
        self.btn_open.setProperty("variant", "outline")
        self.btn_open.setIcon(icon("folder-open"))
        self.btn_open.clicked.connect(self.on_open_bundle)

        self.btn_new = QPushButton("New App...")
        self.btn_new.setProperty("variant", "secondary")
        self.btn_new.setIcon(icon("plus"))
        self.btn_new.clicked.connect(self.on_new_app)

        self.btn_theme = QPushButton("")
        self.btn_theme.setProperty("variant", "ghost")
        self.btn_theme.setIcon(icon("moon"))
        self.btn_theme.clicked.connect(self.on_toggle_theme)

        top_bar.addWidget(self.lbl_logo)
        top_bar.addSpacing(8)
        top_bar.addWidget(self.lbl_title)
        top_bar.addSpacing(24)
        top_bar.addWidget(self.btn_open)
        top_bar.addWidget(self.btn_new)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_theme)

        main_layout.addLayout(top_bar)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter, 1)

        # Left: Device Panel, with a caption strip directly beneath the bezel
        # reporting the emulated geometry and letting the user pick a panel.
        from PySide6.QtWidgets import QComboBox

        panel_wrap = QWidget()
        panel_layout = QVBoxLayout(panel_wrap)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(10)

        self.device_panel = DevicePanel()
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
        self.cmb_panel.addItem("Custom (from manifest)")
        self.cmb_panel.setCurrentIndex(3)          # 10.1" 1280x800, the common default
        self.cmb_panel.currentIndexChanged.connect(self.on_panel_size_changed)

        caption.addWidget(QLabel("Display:"))
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
        self._right_tabs.setAccessibleName("Deployer tool tabs")

        # ── Deploy tab ────────────────────────────────────────────────────
        deploy_page = QWidget()
        right_layout = QVBoxLayout(deploy_page)
        right_layout.setContentsMargins(0, 8, 0, 0)

        # Connection Box
        conn_box = QGroupBox("Target Configuration")
        conn_layout = QFormLayout(conn_box)
        self.inp_host = QLineEdit(self.settings.value("host", "192.168.1.100"))
        self.inp_user = QLineEdit(self.settings.value("user", "root"))
        self.inp_port = QLineEdit(str(self.settings.value("port", "22")))
        self.inp_port.setPlaceholderText("22")
        self.inp_key = QLineEdit(self.settings.value("key", ""))
        self.inp_key.setPlaceholderText("Leave empty for default agent")

        conn_layout.addRow("Host:", self.inp_host)
        conn_layout.addRow("User:", self.inp_user)
        conn_layout.addRow("Port:", self.inp_port)
        conn_layout.addRow("Key:", self.inp_key)

        test_layout = QHBoxLayout()
        from PySide6.QtWidgets import QPushButton
        self.btn_test = QPushButton("Connect / Test")
        self.btn_test.clicked.connect(self.on_test_conn)
        test_layout.addWidget(self.btn_test)
        test_layout.addStretch()
        conn_layout.addRow("", test_layout)

        right_layout.addWidget(conn_box)

        # Deployment Actions
        deploy_box = QGroupBox("Deployment")
        deploy_layout = QVBoxLayout(deploy_box)

        from PySide6.QtWidgets import QLabel
        self.val_label = QLabel("No bundle loaded.")
        self.val_label.setWordWrap(True)
        deploy_layout.addWidget(self.val_label)

        self.btn_deploy = QPushButton("Deploy to Target")
        self.btn_deploy.setProperty("variant", "default")
        self.btn_deploy.setIcon(icon("upload"))
        self.btn_deploy.clicked.connect(self.on_deploy)
        self.btn_deploy.setEnabled(False)
        deploy_layout.addWidget(self.btn_deploy)

        # Deployment progress. A deploy spends most of its wall clock inside
        # one silent scp, so without this the tool looks frozen for minutes on
        # a large bundle -- which has been reported as a hang more than once.
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setVisible(False)
        deploy_layout.addWidget(self.progress)

        self.lbl_stage = QLabel("")
        self.lbl_stage.setWordWrap(True)
        self.lbl_stage.setVisible(False)
        deploy_layout.addWidget(self.lbl_stage)

        h_layout = QHBoxLayout()
        self.btn_rollback = QPushButton("Rollback")
        self.btn_rollback.setProperty("variant", "destructive")
        self.btn_rollback.setIcon(icon("history"))
        self.btn_rollback.clicked.connect(self.on_rollback)

        self.btn_restart = QPushButton("Restart GUI")
        self.btn_restart.setProperty("variant", "outline")
        self.btn_restart.setIcon(icon("refresh"))
        self.btn_restart.clicked.connect(self.on_restart)

        h_layout.addWidget(self.btn_rollback)
        h_layout.addWidget(self.btn_restart)
        deploy_layout.addLayout(h_layout)

        right_layout.addWidget(deploy_box)

        # Console Output
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(150)
        right_layout.addWidget(QLabel("Console Output:"))
        right_layout.addWidget(self.console, 1)

        self._right_tabs.addTab(deploy_page, "Deploy")

        # ── Tag Lab tab ────────────────────────────────────────────────────
        # Imported here (deferred) so the tab is only instantiated after
        # PySide6 is confirmed available. TagLabPanel guards its own imports.
        from .taglab_panel import TagLabPanel
        self.taglab_panel = TagLabPanel()
        self.taglab_panel.sendingStarted.connect(self._on_taglab_start)
        self.taglab_panel.sendingStopped.connect(self._on_taglab_stop)
        self._right_tabs.addTab(self.taglab_panel, "Tag Lab")

        splitter.addWidget(self._right_tabs)
        splitter.setSizes([800, 400])

        # Footer: attribution on the left, version hard right. Kept to the muted
        # token so it reads as chrome and never competes with the panel preview.
        footer = QHBoxLayout()
        footer.setContentsMargins(2, 8, 2, 0)

        self.lbl_footer = QLabel("Developed by FlyVi Technologies. All rights reserved.")
        self.lbl_footer.setObjectName("footerText")

        self.lbl_version = QLabel(APP_VERSION)
        self.lbl_version.setObjectName("footerVersion")

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

    def on_panel_size_changed(self, index):
        """
        Applies the selected panel geometry to the preview.

        Args:
            index: row in cmb_panel. The final row is "Custom", which falls back
                to the loaded manifest's screen block, or 1280x800 when no
                bundle is loaded yet.
        """
        if 0 <= index < len(PANEL_PRESETS):
            _label, _inches, width, height = PANEL_PRESETS[index]
        else:
            screen = (self.current_manifest or {}).get("screen", {})
            width = int(screen.get("width", 1280))
            height = int(screen.get("height", 800))
        self.device_panel.set_target_resolution(width, height)
        self.lbl_resolution.setText(self.device_panel.resolution_text())

    def on_toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.btn_theme.setIcon(icon("sun" if self.theme == "dark" else "moon"))
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
        else:
            err_text = "\n".join(msgs)
            self.val_label.setText(f"Validation Failed:\n{err_text}")
            self.val_label.setStyleSheet("color: #ef4444;")  # destructive
            self.btn_deploy.setEnabled(False)

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

    def start_simulator(self, expected_tags):
        self._stop_all_senders()
        self.simulator = TelemetrySimulator(expected_tags, self)
        self.simulator.start()

    def start_relay(self):
        self._stop_all_senders()

        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        self.relay = TelemetryRelay(host, user, self.ssh_port(), key, self)
        self.relay.start()

    # ------------------------------------------------------------------
    # Tag Lab sender lifecycle (mutual exclusion enforced here)
    # ------------------------------------------------------------------

    def _on_taglab_start(self) -> None:
        """Slot: TagLabPanel requested start.  Enforce mutual exclusion."""
        self._stop_all_senders()
        model = self.taglab_panel.model()
        self.taglab_sender = TagLabSender(model, parent=self)
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
        self.progress.setFormat("%p%")
        self.progress.setStyleSheet("")
        self.progress.setValue(0)
        self.lbl_stage.setVisible(True)
        self.lbl_stage.setStyleSheet("color: #a1a1aa;")
        self.lbl_stage.setText("Preparing...")
        self._deploy_failed = False

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
        self.progress.setFormat("Failed")
        self.progress.setStyleSheet(
            "QProgressBar::chunk { background-color: #ef4444; }"
        )
        self.lbl_stage.setVisible(True)
        self.lbl_stage.setStyleSheet("color: #ef4444;")
        self.lbl_stage.setText(reason)
        self.log(f"DEPLOY FAILED: {reason}")
        self.device_panel.set_led_state(3)

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

        if status == "fail":
            self._progress_fail(
                f"{INSTALL_STEP_LABEL.get(tag, tag)} failed: {detail}".strip()
            )
            return
        if tag in INSTALL_STEP_PROGRESS:
            self._progress_set(INSTALL_STEP_PROGRESS[tag],
                               INSTALL_STEP_LABEL.get(tag, tag))

    def log(self, text):
        self.console.appendPlainText(text)
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
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(),
            self.inp_user.text().strip(),
            22,
            self.inp_key.text().strip(),
            # `hmi-install help`, not `--help`: the installer dispatches on a
            # bare subcommand and answers anything else with a usage error.
            # is-enabled is reported alongside is-active because the two answer
            # different questions: whether the panel is showing the app now, and
            # whether it will still be showing it after the next power cycle.
            "echo 'SSH OK'; hmi-install help; "
            "echo -n 'hmi-gui now:  '; systemctl is-active hmi-gui.service; "
            "echo -n 'hmi-gui boot: '; systemctl is-enabled hmi-gui.service; "
            "hmi-install status; df -h /tmp /opt"
        )
        self.run_ssh_worker(cmd, "Test Connection", timeout_s=SSH_SHORT_TIMEOUT_S)

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
        worker.outputLine.connect(self.log)

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
        worker.outputLine.connect(self.log)
        if line_hook is not None:
            worker.outputLine.connect(line_hook)

        pulse = None
        if heartbeat_s > 0:
            pulse = QTimer(self)
            pulse.setInterval(heartbeat_s * 1000)
            pulse.timeout.connect(
                lambda: self.log(f"  {desc}: {time.monotonic() - started:.0f}s elapsed...")
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
                    self.start_relay()
            else:
                self.device_panel.set_led_state(3)  # Fault
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

    def _discard_packaging_dir(self) -> None:
        """Remove the temp directory holding the last deployment's tarball.

        Args:   none
        Returns: nothing
        Side effects: deletes the directory tree if one is recorded.
        Never raises: failing to tidy up must not fail or interrupt a deploy.
        """
        path = getattr(self, "_packaging_dir", None)
        if not path:
            return
        self._packaging_dir = None
        try:
            import shutil
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass

    def on_deploy(self):
        """
        Packages the loaded bundle and installs it on the panel.

        The flow is four SSH/SCP steps chained through completion callbacks:
        mkdir -> scp tarball -> scp checksum -> hmi-install install. Each step
        only starts once the previous one has exited 0, so a failure anywhere
        stops the deployment with the failing step named in the console.
        """
        self.save_settings()
        self.log(f"Deploying {self.bundle_dir}...")
        self._progress_begin()
        try:
            import tempfile
            # Cleaned up when the deployment finishes, succeeds or fails.
            # Every deploy used to leave its tarball behind -- up to 500 MB
            # each, and a working session is many deploys.
            self._discard_packaging_dir()
            out_dir = tempfile.mkdtemp(prefix="hmi-deploy-")
            self._packaging_dir = out_dir
            self._progress_set(2, "Packaging bundle...")
            tar_path, sha256_path = package_bundle(self.bundle_dir, out_dir)
            tar_size = os.path.getsize(tar_path)
            self.log(f"Packaged to {tar_path} ({tar_size / (1024 * 1024):.1f} MB)")
            self._progress_set(
                PROGRESS_PACKAGED,
                f"Packaged {tar_size / (1024 * 1024):.1f} MB",
            )

            host = self.inp_host.text().strip()
            user = self.inp_user.text().strip()
            key = self.inp_key.text().strip()

            # Upload allowance scaled to the payload. A slow panel link moving a
            # large bundle is normal, not a hang; a fixed short timeout would
            # kill the transfer partway and leave a truncated file in the tmpfs.
            scp_timeout = SCP_BASE_TIMEOUT_S + int(tar_size / SCP_MIN_BYTES_PER_S)

            # Step 1: Create /tmp/hmi_upload and upload the bundle
            from .ssh import build_scp_cmd
            cmd_mkdir = build_ssh_cmd(host, user, self.ssh_port(), key, "mkdir -p /tmp/hmi_upload")
            tar_name = os.path.basename(tar_path)

            def on_mkdir(code):
                if code != 0:
                    self._discard_packaging_dir()
                    self._progress_fail(
                        "Could not create /tmp/hmi_upload on the panel."
                    )
                    return
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

            def on_upload(code):
                if code != 0:
                    self._discard_packaging_dir()
                    self._progress_fail("Bundle upload failed.")
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
                if code != 0:
                    self._discard_packaging_dir()
                    self._progress_fail("Checksum upload failed.")
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
                self._discard_packaging_dir()
                if code == 0 and not self._deploy_failed:
                    self.log("Deployment complete.")
                    self._progress_succeed()
                elif not self._deploy_failed:
                    # A non-zero exit with no failing STEP line: the installer
                    # died before it could report which stage broke.
                    self._progress_fail(
                        f"hmi-install exited {code}. See the console for the last step reached."
                    )
                self.start_relay()

            self.run_ssh_worker(
                cmd_mkdir, "Mkdir", on_mkdir, timeout_s=SSH_SHORT_TIMEOUT_S
            )

        except BundleTooLargeError as e:
            self._progress_fail("Bundle is too large for the panel.")
            self.log(str(e))
            QMessageBox.critical(self, "Bundle too large", str(e))
        except Exception as e:
            self._progress_fail(f"Could not start the deployment: {e}")

    def on_rollback(self):
        self.save_settings()
        self.log("Rolling back to previous release...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, self.ssh_port(), key, "hmi-install rollback")
        # Rollback restarts the GUI on its way out, so it is not instant.
        self.run_ssh_worker(cmd, "Rollback", timeout_s=INSTALL_TIMEOUT_S)

    def on_restart(self):
        self.save_settings()
        self.log("Restarting GUI...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, self.ssh_port(), key, "systemctl restart hmi-gui.service")
        self.run_ssh_worker(cmd, "Restart GUI", timeout_s=SSH_SHORT_TIMEOUT_S)

    def closeEvent(self, event):
        """Release every local/remote telemetry source before closing."""
        self._stop_all_senders()
        self._discard_packaging_dir()
        super().closeEvent(event)
