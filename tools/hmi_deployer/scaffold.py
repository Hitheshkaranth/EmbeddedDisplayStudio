"""
tools/hmi_deployer/scaffold.py
Layer: 3 (Host Deployer)
Purpose: Scaffolds a new "Bring Your Own App" bundle containing the bare minimum
files to deploy and run on the HMI target. (CONTRACT section 4).
"""
import json
import os
import tarfile
from pathlib import Path
from typing import Dict, Any

def create_bundle(target_dir: str, name: str = "new-app") -> None:
    """
    Creates a new app bundle directory with a manifest and a main.qml.

    Args:
        target_dir: Absolute path where the app directory will be created.
        name: Name of the application.

    Raises:
        FileExistsError: If target_dir already exists.
    """
    os.makedirs(target_dir, exist_ok=False)
    
    # Generate manifest.json (CONTRACT 4)
    manifest: Dict[str, Any] = {
        "schema": 1,
        "name": name,
        "version": "1.0.0",
        "entry": "main.qml",
        "screen": {"width": 1280, "height": 800},
        "tags_required": ["sys.uptime"],
        "qt": ">=6.5"
    }
    
    manifest_path = os.path.join(target_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    
    # Generate main.qml
    main_qml = """import QtQuick
import Shadcn 1.0

Rectangle {
    width: 1280
    height: 800
    color: Theme.background

    Column {
        anchors.centerIn: parent
        spacing: 24

        ShLabel {
            text: "Welcome to your new HMI app"
            font.pixelSize: 30
            color: Theme.foreground
        }

        ShValueTile {
            label: "System Uptime"
            value: Tags.sys_uptime !== null ? Tags.sys_uptime.toFixed(1) : "--"
            unit: "s"
            state: Tags.online ? "ok" : "warn"
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
}
"""
    main_qml_path = os.path.join(target_dir, "main.qml")
    with open(main_qml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(main_qml)
