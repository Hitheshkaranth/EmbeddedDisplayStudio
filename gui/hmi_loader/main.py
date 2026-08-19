"""
gui/hmi_loader/main.py
Layer: 2 (GUI Loader)
Purpose: Entry point for the HMI GUI. Parses arguments, sets up the QML engine,
loads the app manifest, and exposes the TagEngine and Hmi objects to QML.
Implements CONTRACT Sections 4 (App bundle validation) and 6 (Deployment).
"""

import os
import sys
import json
import logging
import argparse
import re
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot, Property, QTimer, qInstallMessageHandler, QtMsgType, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from tagengine import TagEngine

# Structured logging for journald (CONTRACT 7)
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("hmi-gui")

def qml_log_handler(msg_type, context, message):
    """
    Routes QML engine warnings/errors into the standard python logger.
    This ensures QML warnings land in journald.
    
    Args:
        msg_type: Type of Qt message.
        context: Context of the message.
        message: The actual log string.
    """
    if msg_type == QtMsgType.QtDebugMsg:
        logger.debug(f"QML Debug: {message}")
    elif msg_type == QtMsgType.QtInfoMsg:
        logger.info(f"QML Info: {message}")
    elif msg_type == QtMsgType.QtWarningMsg:
        logger.warning(f"QML Warning: {message}")
    elif msg_type == QtMsgType.QtCriticalMsg:
        logger.error(f"QML Critical: {message}")
    elif msg_type == QtMsgType.QtFatalMsg:
        logger.critical(f"QML Fatal: {message}")

class Hmi(QObject):
    """
    Exposes app metadata and system operations to QML.
    """
    
    lastErrorChanged = Signal()

    def __init__(self, manifest: dict, apps_dir: Path, ready_file: Path, parent: QObject = None):
        """
        Initializes the Hmi object.
        
        Args:
            manifest (dict): Parsed manifest dictionary (empty if failed).
            apps_dir (Path): The root directory of the application bundle.
            ready_file (Path): The path to the readiness marker file.
            parent (QObject): Parent QObject.
        """
        super().__init__(parent)
        self._manifest = manifest
        self._apps_dir = apps_dir
        self._ready_file = ready_file
        self._last_error = ""
        
        if manifest:
            entry = manifest.get("entry", "main.qml")
            self._app_entry_url = QUrl.fromLocalFile(str((self._apps_dir / entry).resolve()))
        else:
            self._app_entry_url = QUrl()

    @Property(str, constant=True)
    def appName(self) -> str:
        """Returns the app name."""
        return self._manifest.get("name", "Unknown") if self._manifest else "Error"

    @Property(str, constant=True)
    def appVersion(self) -> str:
        """Returns the app version."""
        return self._manifest.get("version", "0.0.0") if self._manifest else "0.0.0"

    @Property(QUrl, constant=True)
    def appEntryUrl(self) -> QUrl:
        """Returns the QUrl to the app's main entry point."""
        return self._app_entry_url

    @Property(int, constant=True)
    def screenWidth(self) -> int:
        """Returns the requested screen width."""
        screen = self._manifest.get("screen", {}) if self._manifest else {}
        return screen.get("width", 1280)

    @Property(int, constant=True)
    def screenHeight(self) -> int:
        """Returns the requested screen height."""
        screen = self._manifest.get("screen", {}) if self._manifest else {}
        return screen.get("height", 800)

    def get_last_error(self) -> str:
        """Returns the last validation error."""
        return self._last_error
        
    def set_last_error(self, err: str) -> None:
        """Sets the last validation error."""
        if self._last_error != err:
            self._last_error = err
            self.lastErrorChanged.emit()

    # Exposed to QML for the Fallback screen to display what went wrong
    lastError = Property(str, get_last_error, set_last_error, notify=lastErrorChanged)

    @Slot()
    def markReady(self) -> None:
        """
        Touches the ready file. The deployment pipeline's health check (Layer 3) 
        depends on this exact behavior to commit an atomic swap. If this file 
        isn't created within a timeout, the deployment rolls back.
        """
        try:
            # We must ensure the parent directory exists, as the deployment script
            # might not have created `/run/hmi/` if it was wiped.
            self._ready_file.parent.mkdir(parents=True, exist_ok=True)
            self._ready_file.touch(exist_ok=True)
            logger.info(f"Marked ready at {self._ready_file}")
        except Exception as e:
            logger.error(f"Failed to touch ready file {self._ready_file}: {e}")

    @Slot()
    def restart(self) -> None:
        """Requests application restart (simulated by exit 1 for systemd)."""
        logger.info("Restart requested by QML.")
        sys.exit(1)

    @Slot(str)
    def log(self, msg: str) -> None:
        """
        Allows QML to log arbitrary messages to journald.
        
        Args:
            msg (str): Message to log.
        """
        logger.info(f"App Log: {msg}")

def validate_manifest(manifest_path: Path) -> tuple[dict, str]:
    """
    Validates manifest.json against CONTRACT Section 4.
    
    Args:
        manifest_path (Path): Path to manifest.json.
        
    Returns:
        tuple: (manifest_dict, error_string). If validation fails, manifest_dict is {}.
    """
    if not manifest_path.exists():
        return {}, f"Manifest not found: {manifest_path}"
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return {}, f"Manifest parse error: {e}"
        
    if manifest.get("schema") != 1:
        return {}, "Unsupported or missing schema version. Expected schema: 1."
        
    name = manifest.get("name", "")
    if not isinstance(name, str) or not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", name):
        return {}, f"Invalid app name: '{name}'. Must match ^[a-z0-9][a-z0-9._-]{{0,63}}$"
        
    entry = manifest.get("entry", "")
    if not entry:
        return {}, "Missing 'entry' in manifest."
    if ".." in entry or os.path.isabs(entry):
        return {}, f"Invalid entry path: '{entry}'. Cannot be absolute or contain '..'."
        
    entry_path = manifest_path.parent / entry
    if not entry_path.exists():
        return {}, f"Entry point not found: {entry_path}"
        
    return manifest, ""

def main():
    parser = argparse.ArgumentParser(description="HMI GUI Loader (Layer 2)")
    parser.add_argument("--apps-dir", default="/opt/hmi_apps/current", help="Path to the app bundle")
    parser.add_argument("--shell", help="Path to custom shell QML")
    parser.add_argument("--rx-port", type=int, default=5001, help="Telemetry receive port")
    parser.add_argument("--daemon-host", default="127.0.0.1", help="Hardware daemon host")
    parser.add_argument("--daemon-port", type=int, default=5000, help="Hardware daemon port")
    parser.add_argument("--ready-file", default="/run/hmi/gui-ready", help="Readiness marker file")
    parser.add_argument("--windowed", action="store_true", help="Run windowed for desktop dev")
    parser.add_argument("--theme", choices=["light", "dark"], default="dark", help="Initial theme")
    parser.add_argument("--exit-after", type=int, help=argparse.SUPPRESS) # Hidden, for smoke tests
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    
    args = parser.parse_args()
    
    logger.setLevel(getattr(logging, args.log_level))
    
    # Route QML warnings to logger
    qInstallMessageHandler(qml_log_handler)
    
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    
    # Resolve QML import path for the shadcn/ui kit.
    # The production installed path is /usr/lib/hmi/qml (CONTRACT 3).
    # When running from source, the path is ../../ui/qml relative to this script.
    # We add both to support both environments seamlessly.
    prod_qml_path = Path("/usr/lib/hmi/qml")
    src_qml_path = Path(__file__).parent.parent.parent / "ui" / "qml"
    
    if src_qml_path.exists():
        engine.addImportPath(str(src_qml_path.resolve()))
    engine.addImportPath(str(prod_qml_path))
    
    apps_dir = Path(args.apps_dir).resolve()
    manifest_path = apps_dir / "manifest.json"
    
    manifest, error = validate_manifest(manifest_path)
    if error:
        logger.error(error)
        
    expected_tags = manifest.get("tags_required", []) if manifest else []
    
    tag_engine = TagEngine(
        expected_tags,
        rx_port=args.rx_port,
        daemon_host=args.daemon_host,
        daemon_port=args.daemon_port,
    )
    hmi = Hmi(manifest, apps_dir, Path(args.ready_file))
    if error:
        hmi.set_last_error(error)

    # Two context properties, because a QQmlPropertyMap subclass cannot carry
    # slots under PySide6 (see the note at the top of tagengine.py):
    #   Tags - the value map, for declarative bindings (Tags.ai_pot, Tags.online)
    #   Bus  - the engine, for commands (Bus.write / Bus.pulse / Bus.value)
    engine.rootContext().setContextProperty("Tags", tag_engine.tagMap())
    engine.rootContext().setContextProperty("Bus", tag_engine)
    engine.rootContext().setContextProperty("Hmi", hmi)
    
    # Load the shell
    shell_qml = args.shell
    if not shell_qml:
        shell_qml = str((Path(__file__).parent.parent / "shell" / "Shell.qml").resolve())
        
    # We expose command line args as properties or just let QML use windowed
    engine.rootContext().setContextProperty("isWindowed", args.windowed)
    engine.rootContext().setContextProperty("initialTheme", args.theme)
    
    engine.load(QUrl.fromLocalFile(shell_qml))
    if not engine.rootObjects():
        logger.critical("Failed to load shell QML. Exiting.")
        sys.exit(1)
        
    if args.exit_after:
        QTimer.singleShot(args.exit_after, app.quit)
        
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
