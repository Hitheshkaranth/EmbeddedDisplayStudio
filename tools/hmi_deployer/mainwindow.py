"""
tools/hmi_deployer/mainwindow.py
Layer: 3 (Host Deployer)
Purpose: Main application window, layout, actions, and state machine.
"""
import os
import sys
import json
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QSplitter, QGroupBox, QFormLayout, QLineEdit, 
    QPlainTextEdit, QFileDialog, QMessageBox, QTabWidget,
    QProgressBar, QStackedWidget
)
from PySide6.QtCore import Qt, QSettings
from .devicepanel import DevicePanel, PANEL_PRESETS
from .deployer import validate_bundle, package_bundle, detect_bundle, write_manifest
from .telemetry import TelemetrySimulator, TelemetryRelay
from .ssh import SshWorker, build_ssh_cmd
from .scaffold import create_bundle

try:
    from ui.python.shadcn import apply, icon, qml_import_path
except ImportError:
    # Dummy mock if not running correctly
    def apply(app, theme): pass
    def icon(name, size=18, color=None): from PySide6.QtGui import QIcon; return QIcon()
    def qml_import_path(): return ""

# Product version, shown hard right in the footer. Single source of truth.
APP_VERSION = "0.0.1"


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
        # Manifest of the loaded bundle; the panel picker's Custom entry reads it.
        self.current_manifest = None
        self.ssh_worker = None
        
        self.setup_ui()
        self.apply_theme()
        
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
        
        # Right: Tools
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        # Connection Box
        conn_box = QGroupBox("Target Configuration")
        conn_layout = QFormLayout(conn_box)
        self.inp_host = QLineEdit(self.settings.value("host", "192.168.1.100"))
        self.inp_user = QLineEdit(self.settings.value("user", "root"))
        self.inp_key = QLineEdit(self.settings.value("key", ""))
        self.inp_key.setPlaceholderText("Leave empty for default agent")
        
        conn_layout.addRow("Host:", self.inp_host)
        conn_layout.addRow("User:", self.inp_user)
        conn_layout.addRow("Key:", self.inp_key)
        
        test_layout = QHBoxLayout()
        self.btn_test = QPushButton("Connect / Test")
        self.btn_test.clicked.connect(self.on_test_conn)
        test_layout.addWidget(self.btn_test)
        test_layout.addStretch()
        conn_layout.addRow("", test_layout)
        
        right_layout.addWidget(conn_box)
        
        # Deployment Actions
        deploy_box = QGroupBox("Deployment")
        deploy_layout = QVBoxLayout(deploy_box)
        
        self.val_label = QLabel("No bundle loaded.")
        self.val_label.setWordWrap(True)
        deploy_layout.addWidget(self.val_label)
        
        self.btn_deploy = QPushButton("Deploy to Target")
        self.btn_deploy.setProperty("variant", "default")
        self.btn_deploy.setIcon(icon("upload"))
        self.btn_deploy.clicked.connect(self.on_deploy)
        self.btn_deploy.setEnabled(False)
        deploy_layout.addWidget(self.btn_deploy)
        
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
        
        splitter.addWidget(right_panel)
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
            kind = "QML" if runtime == "qml" else "Python"
            self.val_label.setText(
                f"Bundle Valid: {manifest.get('name')} v{manifest.get('version')}  [{kind}]"
            )
            self.val_label.setStyleSheet("color: #22c55e;") # success
            self.btn_deploy.setEnabled(True)
            
            self.device_panel.load_bundle(dir_path, manifest)
            self.start_simulator(manifest.get("tags_required", []))
        else:
            err_text = "\n".join(msgs)
            self.val_label.setText(f"Validation Failed:\n{err_text}")
            self.val_label.setStyleSheet("color: #ef4444;") # destructive
            self.btn_deploy.setEnabled(False)

    def start_simulator(self, expected_tags):
        if self.simulator:
            self.simulator.stop()
        if self.relay:
            self.relay.stop()
            self.relay = None
            
        self.simulator = TelemetrySimulator(expected_tags, self)
        self.simulator.start()
        
    def start_relay(self):
        if self.simulator:
            self.simulator.stop()
            self.simulator = None
        if self.relay:
            self.relay.stop()
        
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        self.relay = TelemetryRelay(host, user, 22, key, self)
        self.relay.start()

    def log(self, text):
        self.console.appendPlainText(text)
        # scroll to bottom
        vbar = self.console.verticalScrollBar()
        vbar.setValue(vbar.maximum())

    def save_settings(self):
        self.settings.setValue("host", self.inp_host.text().strip())
        self.settings.setValue("user", self.inp_user.text().strip())
        self.settings.setValue("key", self.inp_key.text().strip())

    def on_test_conn(self):
        self.save_settings()
        self.log("Testing connection...")
        self.device_panel.set_led_state(2) # deploying (amber)
        cmd = build_ssh_cmd(
            self.inp_host.text().strip(),
            self.inp_user.text().strip(),
            22,
            self.inp_key.text().strip(),
            "echo 'SSH OK'; hmi-install --help; systemctl is-active hmi-gui.service; df -h /tmp /opt"
        )
        self.run_ssh_worker(cmd, "Test Connection")

    def run_ssh_worker(self, cmd, desc, callback=None):
        self.btn_deploy.setEnabled(False)
        self.ssh_worker = SshWorker(cmd, timeout_s=10, parent=self)
        self.ssh_worker.outputLine.connect(self.log)
        def on_finished(code):
            self.log(f"{desc} exited with {code}")
            if code == 0:
                self.device_panel.set_led_state(1) # Link up
                if desc == "Test Connection":
                    self.start_relay()
            else:
                self.device_panel.set_led_state(3) # Fault
            self.btn_deploy.setEnabled(self.bundle_dir is not None)
            if callback:
                callback(code)
        self.ssh_worker.finished.connect(on_finished)
        self.ssh_worker.error.connect(self.log)
        self.ssh_worker.start()

    def on_deploy(self):
        self.save_settings()
        self.log(f"Deploying {self.bundle_dir}...")
        try:
            import tempfile
            out_dir = tempfile.mkdtemp()
            tar_path, sha256_path = package_bundle(self.bundle_dir, out_dir)
            self.log(f"Packaged to {tar_path}")
            
            host = self.inp_host.text().strip()
            user = self.inp_user.text().strip()
            key = self.inp_key.text().strip()
            
            # Step 1: Create /tmp/hmi_upload and scp files
            from .ssh import build_scp_cmd
            cmd_mkdir = build_ssh_cmd(host, user, 22, key, "mkdir -p /tmp/hmi_upload")
            
            def on_mkdir(code):
                if code != 0: return
                cmd_scp1 = build_scp_cmd(host, user, 22, key, tar_path, "/tmp/hmi_upload/")
                self.run_ssh_worker(cmd_scp1, "SCP tarball", lambda c: on_scp1(c))
                
            def on_scp1(code):
                if code != 0: return
                cmd_scp2 = build_scp_cmd(host, user, 22, key, sha256_path, "/tmp/hmi_upload/")
                self.run_ssh_worker(cmd_scp2, "SCP sha256", lambda c: on_scp2(c))
                
            def on_scp2(code):
                if code != 0: return
                tar_name = os.path.basename(tar_path)
                cmd_install = build_ssh_cmd(host, user, 22, key, f"hmi-install install /tmp/hmi_upload/{tar_name}")
                self.run_ssh_worker(cmd_install, "Install", lambda c: self.start_relay())
                
            self.run_ssh_worker(cmd_mkdir, "Mkdir")
            
        except Exception as e:
            self.log(f"Deploy failed: {e}")

    def on_rollback(self):
        self.save_settings()
        self.log("Rolling back to previous release...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, 22, key, "hmi-install rollback")
        self.run_ssh_worker(cmd, "Rollback")

    def on_restart(self):
        self.save_settings()
        self.log("Restarting GUI...")
        host = self.inp_host.text().strip()
        user = self.inp_user.text().strip()
        key = self.inp_key.text().strip()
        cmd = build_ssh_cmd(host, user, 22, key, "systemctl restart hmi-gui.service")
        self.run_ssh_worker(cmd, "Restart GUI")

