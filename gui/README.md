# gui/ -- HMI GUI Loader (Layer 2)

**Layer:** 2 (GUI Loader)
**Owner:** W2

This directory contains the pure UDP client GUI Loader for the BYOA (Bring Your Own App) HMI system. It is responsible for loading the customer's QML application, providing it with real-time hardware data, and maintaining the system's reliability contract.

---

## Architecture

The loader is built on PySide6 and Qt Quick. It consists of two main components:
1. **TagEngine (`hmi_loader/tagengine.py`)**: A subclass of `QQmlPropertyMap` that maintains a real-time dictionary of hardware tags. It listens on `127.0.0.1:5001` for telemetry from the hardware daemon (Layer 1) and sends commands to `127.0.0.1:5000`. It performs zero hardware I/O itself.
2. **Main Loader (`hmi_loader/main.py`)**: Parses arguments, loads the customer's app bundle (`manifest.json` and `main.qml`), injects the `Tags` and `Hmi` context properties, and manages the main window (`shell/Shell.qml`).

---

## Tag Binding Rules

Customer QML applications interact with hardware by reading and writing properties on the injected `Tags` context property.

### Safe Reading

Tags should always be read using the `Tags.getValue(name, fallback)` method. This ensures that if the hardware daemon goes offline or a tag is not present, the QML UI will gracefully render the fallback value instead of throwing an undefined reference error (CONTRACT 7).

```qml
// Example: Safe read with a fallback of 0.0
ShGauge {
    value: Tags.getValue("ai.pot", 0.0)
}
```

### Writing (Write-through Tags)

Hardware tag names are dot-separated (e.g., `do.relay1`), which is illegal for QML properties. The Tag Engine automatically exposes an underscored alias for every tag (e.g., `do_relay1`).

When you assign a value to an underscored tag property in QML, the `TagEngine` intercepts the assignment, resolves it back to the dotted name, and seamlessly transmits a JSON `set` command to the hardware daemon.

```qml
ShSwitch {
    // Reading the current state safely
    checked: Tags.value("do.relay1", false)
    
    // Writing back to hardware
    onToggled: {
        Tags.do_relay1 = checked; // Emits: {"cmd":"set", "tag":"do.relay1", "value":true}
    }
}
```

You can also explicitly pulse a tag:
```qml
ShButton {
    onClicked: Tags.pulse("do.relay1", 500)
}
```

---

## Authoring an App Bundle

A developer ships a tarball containing at minimum a `manifest.json` and a `main.qml`.

### `manifest.json`

Must conform exactly to schema 1:
```json
{
  "schema": 1,
  "name": "my-controller",
  "version": "1.0.0",
  "entry": "main.qml",
  "screen": {"width": 1280, "height": 800},
  "tags_required": ["ai.pot", "do.relay1"],
  "qt": ">=6.5"
}
```

### `main.qml`

Must be the entry point referenced in the manifest. The `Shadcn` QML component kit is automatically available for import:
```qml
import QtQuick 2.15
import Shadcn 1.0

Rectangle {
    color: Theme.background
    // UI built with ShCard, ShButton, etc.
}
```

---

## Running on Desktop (Simulation)

You can run the GUI Loader on your development machine against a simulated daemon.

```bash
# Navigate to the project root
cd /path/to/EmbeddedDisplay

# Run the loader with the demo app in windowed mode
python gui/hmi_loader/main.py --apps-dir apps/demo-app --windowed
```

To see data move, you can simulate the hardware daemon by sending UDP telemetry frames to `127.0.0.1:5001`. For example, using a short python script:
```python
import socket, json, time
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
payload = {
    "t": "tags",
    "seq": 1,
    "ts": time.time(),
    "src": "sim",
    "tags": {"ai.pot": 2.1, "di.estop": False, "do.relay1": True}
}
sock.sendto(json.dumps(payload).encode('utf-8'), ('127.0.0.1', 5001))
```

---

## Error Handling and Fallbacks

If `manifest.json` is malformed, or if `main.qml` fails to compile, the loader **will not crash to a black screen**. Instead, `Shell.qml` detects the `Loader.Error` or `Loader.Null` state and immediately displays `Fallback.qml`. 

The fallback screen centers a `ShCard` containing diagnostic information, including the exact manifest validation error, preventing the HMI from appearing completely dead (CONTRACT 7).

---

## The Ready-File Contract

When the customer's QML loads successfully (`Loader.Ready`), the shell calls `Hmi.markReady()`. This touches a specific file on the filesystem (default `/run/hmi/gui-ready`). 

The deployment pipeline (Layer 3) waits for this exact file to appear. If it does not appear within a specified timeout (e.g., due to a QML compilation error trapping the UI on the fallback screen), the deployment script assumes the bundle is broken and **automatically rolls back** the symlink to the previous working release.

### Deviation from Contract
The contract specifies Tags.value(name, fallback). However, QQmlPropertyMap in PySide6 resolves all dot-notation property reads dynamically. This means Tags.value attempts to read a tag named alue, which intercepts the function call and causes a TypeError: Property 'value' is not a function. Therefore, the method was renamed to getValue, and apps must use Tags.getValue(name, fallback). The architect must reconcile this change.
