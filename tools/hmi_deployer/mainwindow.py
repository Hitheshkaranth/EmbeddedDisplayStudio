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
from .devicepanel import DevicePanel
from .deployer import validate_bundle, package_bundle
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

class MainWindow(QMainWindow):
    def __init__(self, exit_after_ms=0):
        super().__init__()
        self.setWindowTitle("HMI Deployer")
        self.resize(1280, 800)
        self.exit_after_ms = exit_after_ms
        
        self.settings = QSettings("MIL-HMI", "Deployer")
        self.bundle_dir = self.settings.value("last_bundle", "")
        self.theme = "light"
        
        self.simulator = None
        self.relay = None
        self.ssh_worker = None
        
        self.setup_ui()
        self.apply_theme()
        
        if self.bundle_dir and os.path.isdir(self.bundle_dir):
            self.load_bundle(self.bundle_dir)

        if self.exit_after_ms > 0:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(self.exit_after_ms, self.close)
            
    def apply_theme(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        apply(app, self.theme)

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
        self.lbl_title = QLabel("HMI App Studio")
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
        
        # Left: Device Panel
        self.device_panel = DevicePanel()
        splitter.addWidget(self.device_panel)
        
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

    def on_toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.btn_theme.setIcon(icon("sun" if self.theme == "dark" else "moon"))
        self.apply_theme()
        
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
        is_valid, msgs = validate_bundle(dir_path)
        if is_valid:
            self.bundle_dir = dir_path
            self.settings.setValue("last_bundle", dir_path)
            with open(os.path.join(dir_path, "manifest.json"), "r", encoding="utf-8") as f:
                manifest = json.load(f)
            
            self.val_label.setText(f"Bundle Valid: {manifest.get('name')} v{manifest.get('version')}")
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

