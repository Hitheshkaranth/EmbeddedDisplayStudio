# ui/ -- shadcn/ui Design System for Qt (QML + Widgets)

**Layer:** Shared design system (CONTRACT Section 11)
**Owner:** W7

A faithful port of [shadcn/ui](https://github.com/shadcn-ui/ui) (default "slate"
theme) to Qt, usable from both QML (the on-target HMI, Layer 2) and Qt Widgets
(the host deployer tool, W5). Reproduces shadcn's actual component semantics:
the same variant names, size names, geometry in px, interaction states (hover,
pressed, focus-visible ring, disabled at 50% opacity), and the same restraint.

---

## Quick Start

### QML (on-target HMI or app bundles)

The GUI loader adds `/usr/lib/hmi/qml` to the QML import path.  In your
`main.qml` (or any QML file):

```qml
import QtQuick 2.15
import Shadcn 1.0

Rectangle {
    color: Theme.background
    width: 1280; height: 800

    ShButton {
        text: "Deploy"
        variant: "default"
        onClicked: console.log("clicked")
    }
}
```

### Qt Widgets (host deployer)

```python
import sys
from PySide6.QtWidgets import QApplication
from ui.python.shadcn import apply, icon, qml_import_path

app = QApplication(sys.argv)
apply(app, "light")  # or "dark"

# Use icons
upload_icon = icon("upload", size=18)

# Get QML import path for QQmlEngine
engine.addImportPath(qml_import_path())
```

---

## File Layout

```
ui/
  tokens.json                    Single source of truth for all design tokens
  __init__.py                    Package init
  README.md                      This file
  python/
    __init__.py                  Package init
    shadcn.py                    Token loader, QSS generator, icon helper
  qml/
    Shadcn/
      qmldir                    QML module declaration
      Theme.qml                 Singleton: all tokens as QML properties
      TablerIcons.js             Vendored icon SVG registry (generated)
      ShButton.qml              Button (6 variants, 4 sizes)
      ShInput.qml               Text input field
      ShCard.qml                Card container
      ShCardHeader.qml          Card header section
      ShCardTitle.qml           Card title text
      ShCardDescription.qml     Card description text
      ShCardContent.qml         Card content area
      ShBadge.qml               Inline badge (6 variants)
      ShSwitch.qml              Toggle switch
      ShProgress.qml            Progress bar
      ShSeparator.qml           Horizontal/vertical separator
      ShAlert.qml               Alert box (default/destructive)
      ShTabs.qml                Tabbed container
      ShLabel.qml               Text label
      ShSkeleton.qml            Loading placeholder
      ShDialog.qml              Modal dialog
      ShGauge.qml               Analog gauge (HMI addition)
      ShStatDot.qml             State LED indicator (HMI addition)
      ShValueTile.qml           Large numeric readout (HMI addition)
      ShIcon.qml                Tabler icon renderer
  qss/
    shadcn_light.qss            Pre-generated light stylesheet
    shadcn_dark.qss             Pre-generated dark stylesheet
  icons/
    __init__.py                  Package init
    tabler_icons.py              Vendored icon path-data registry (generated)
    vendor_icons.py              Generator script (fetches from unpkg)
    LICENSE.tabler               MIT license for Tabler Icons
  gallery.py                     Visual gallery + screenshot tool
  tests/
    __init__.py                  Package init
    test_tokens.py               Verifies Theme.qml matches tokens.json
```

---

## Design Tokens (CONTRACT 11.1)

All colours, radii, spacing, typography, shadows, and motion values live in
`tokens.json`. This file is the canonical reference; both the QML `Theme`
singleton and the generated QSS stylesheets derive from it.

### Colour Palettes

| Token                  | Light       | Dark        |
| ---------------------- | ----------- | ----------- |
| `background`           | `#ffffff`   | `#020817`   |
| `foreground`           | `#020817`   | `#f8fafc`   |
| `card` / `popover`     | `#ffffff`   | `#020817`   |
| `cardForeground`       | `#020817`   | `#f8fafc`   |
| `primary`              | `#0f172a`   | `#f8fafc`   |
| `primaryForeground`    | `#f8fafc`   | `#0f172a`   |
| `secondary`            | `#f1f5f9`   | `#1e293b`   |
| `secondaryForeground`  | `#0f172a`   | `#f8fafc`   |
| `muted` / `accent`     | `#f1f5f9`   | `#1e293b`   |
| `mutedForeground`      | `#64748b`   | `#94a3b8`   |
| `accentForeground`     | `#0f172a`   | `#f8fafc`   |
| `destructive`          | `#ef4444`   | `#7f1d1d`   |
| `destructiveForeground`| `#f8fafc`   | `#f8fafc`   |
| `border` / `input`     | `#e2e8f0`   | `#1e293b`   |
| `ring`                 | `#020817`   | `#cbd5e1`   |
| `success`              | `#22c55e`   | `#22c55e`   |
| `warning`              | `#f59e0b`   | `#f59e0b`   |
| `info`                 | `#3b82f6`   | `#3b82f6`   |

### Radii (px)

| Name   | Value |
| ------ | ----- |
| `sm`   | 4     |
| `md`   | 6     |
| `lg`   | 8     |
| `xl`   | 12    |
| `full` | 9999  |

### Spacing (px, 4px base grid)

`4  8  12  16  24  32  48`

### Typography

**Font stack:** `Inter, Noto Sans, DejaVu Sans, sans-serif`

| Size name | px  |
| --------- | --- |
| `xs`      | 12  |
| `sm`      | 14  |
| `base`    | 16  |
| `lg`      | 18  |
| `xl`      | 20  |
| `2xl`     | 24  |
| `3xl`     | 30  |

**Weights:** normal = 400, medium = 500, semibold = 600

**Heading letter spacing:** -0.4 px (tracking-tight)

### Shadows

| Name | Value                              |
| ---- | ---------------------------------- |
| `sm` | `0 1px 2px rgba(0,0,0,.05)`       |
| `md` | `0 4px 6px -1px rgba(0,0,0,.1)`   |
| `lg` | `0 10px 15px -3px rgba(0,0,0,.1)` |

### Motion

- Colour transitions: 150 ms, `Easing.OutQuad`
- Focus ring: appears instantly (no animation)

---

## Component Reference

### ShButton

Button with six variants and four sizes.

| Property   | Type   | Default     | Description                               |
| ---------- | ------ | ----------- | ----------------------------------------- |
| `text`     | string | `""`        | Button label text                         |
| `variant`  | string | `"default"` | Visual variant (see below)                |
| `size`     | string | `"default"` | Size preset (see below)                   |
| `enabled`  | bool   | `true`      | Interactive state                         |

**Variants:** `default`, `secondary`, `destructive`, `outline`, `ghost`, `link`

**Sizes:** `default` (h=36, px=16), `sm` (h=32, px=12), `lg` (h=40, px=24),
`icon` (36x36, no padding)

**Signal:** `clicked()`

```qml
ShButton {
    text: "Save Changes"
    variant: "default"
    size: "default"
    onClicked: controller.save()
}

ShButton {
    text: "Delete"
    variant: "destructive"
    onClicked: controller.delete()
}

ShButton {
    variant: "outline"
    size: "icon"
    ShIcon { name: "settings"; size: 16; anchors.centerIn: parent }
}
```

### ShInput

Text input field with border and focus ring.

| Property          | Type   | Default | Description                     |
| ----------------- | ------ | ------- | ------------------------------- |
| `text`            | string | `""`    | Current text value              |
| `placeholderText` | string | `""`    | Placeholder shown when empty    |
| `enabled`         | bool   | `true`  | Interactive state               |
| `readOnly`        | bool   | `false` | Read-only mode                  |

**Signals:** `accepted()`, `textChanged()`

```qml
ShInput {
    placeholderText: "Enter IP address..."
    onAccepted: controller.connect(text)
}
```

### ShCard, ShCardHeader, ShCardTitle, ShCardDescription, ShCardContent

Card container with structured sections.

```qml
ShCard {
    width: 350

    ShCardHeader {
        ShCardTitle { text: "Device Status" }
        ShCardDescription { text: "Real-time sensor readings" }
    }

    ShCardContent {
        Column {
            spacing: 8
            ShLabel { text: "Temperature: 42.3 C" }
            ShLabel { text: "Pressure: 1013 hPa" }
        }
    }
}
```

### ShBadge

Inline status badge.

| Property  | Type   | Default     | Description              |
| --------- | ------ | ----------- | ------------------------ |
| `text`    | string | `""`        | Badge label              |
| `variant` | string | `"default"` | Visual variant           |

**Variants:** `default`, `secondary`, `destructive`, `outline`, `success`, `warning`

```qml
ShBadge { text: "Online"; variant: "success" }
ShBadge { text: "Error"; variant: "destructive" }
```

### ShSwitch

Toggle switch.

| Property  | Type | Default | Description     |
| --------- | ---- | ------- | --------------- |
| `checked` | bool | `false` | Toggle state    |
| `enabled` | bool | `true`  | Interactive     |

**Signal:** `toggled()`

```qml
ShSwitch {
    checked: settings.darkMode
    onToggled: settings.darkMode = checked
}
```

### ShProgress

Progress bar.

| Property        | Type | Default | Description                         |
| --------------- | ---- | ------- | ----------------------------------- |
| `value`         | real | `0.0`   | Progress (0.0 to 1.0)              |
| `indeterminate` | bool | `false` | Indeterminate animation mode        |

```qml
ShProgress { value: uploadProgress }
```

### ShSeparator

Visual divider.

| Property      | Type | Default           | Description                  |
| ------------- | ---- | ----------------- | ---------------------------- |
| `orientation` | int  | `Qt.Horizontal`   | Direction of the separator   |

```qml
ShSeparator { width: parent.width }
ShSeparator { orientation: Qt.Vertical; height: parent.height }
```

### ShAlert

Alert message box.

| Property      | Type   | Default     | Description                  |
| ------------- | ------ | ----------- | ---------------------------- |
| `title`       | string | `""`        | Alert title                  |
| `description` | string | `""`        | Alert body text              |
| `variant`     | string | `"default"` | `"default"` or `"destructive"` |

```qml
ShAlert {
    title: "Connection Lost"
    description: "The device is not responding. Check the network cable."
    variant: "destructive"
}
```

### ShTabs

Tabbed content container.

| Property       | Type     | Default | Description              |
| -------------- | -------- | ------- | ------------------------ |
| `model`        | list     | `[]`    | Tab label strings        |
| `currentIndex` | int      | `0`     | Active tab index         |

**Signal:** `tabChanged(int index)`

```qml
ShTabs {
    model: ["Overview", "Sensors", "Config"]
    currentIndex: 0
    onTabChanged: contentStack.currentIndex = index
}
```

### ShLabel

Simple text label.

| Property | Type   | Default | Description |
| -------- | ------ | ------- | ----------- |
| `text`   | string | `""`    | Label text  |

```qml
ShLabel { text: "Serial Number:" }
```

### ShSkeleton

Loading placeholder with pulse animation.

```qml
ShSkeleton { width: 200; height: 20 }
ShSkeleton { width: 100; height: 100; radius: 9999 }
```

### ShDialog

Modal dialog with overlay.

| Property      | Type   | Default | Description             |
| ------------- | ------ | ------- | ----------------------- |
| `visible`     | bool   | `false` | Show/hide the dialog    |
| `title`       | string | `""`    | Dialog title            |
| `description` | string | `""`    | Dialog description      |

**Signals:** `accepted()`, `rejected()`

```qml
ShDialog {
    id: confirmDialog
    title: "Confirm Deployment"
    description: "This will replace the running application."

    Row {
        spacing: 8
        ShButton { text: "Cancel"; variant: "outline"; onClicked: confirmDialog.rejected() }
        ShButton { text: "Deploy"; onClicked: confirmDialog.accepted() }
    }
}
```

### ShGauge (HMI Addition)

Analog value gauge with threshold-based colouring. Designed for industrial
dashboards showing sensor readings with visual warning/fault indication.

| Property            | Type   | Default   | Description                                    |
| ------------------- | ------ | --------- | ---------------------------------------------- |
| `value`             | real   | `0.0`     | Current value to display                       |
| `minValue`          | real   | `0.0`     | Minimum scale value                            |
| `maxValue`          | real   | `100.0`   | Maximum scale value                            |
| `unit`              | string | `""`      | Unit label (e.g. "V", "mA", "C")              |
| `label`             | string | `""`      | Gauge description label                        |
| `thresholdWarning`  | real   | `70.0`    | Value above which gauge shows warning colour   |
| `thresholdFault`    | real   | `90.0`    | Value above which gauge shows fault colour     |

The gauge displays a horizontal bar with the current value as a large numeric
readout. The bar colour transitions from `success` (below warning threshold) to
`warning` (between warning and fault thresholds) to `destructive` (above fault
threshold).

```qml
ShGauge {
    value: Tags.ai_pot
    minValue: 0.0
    maxValue: 3.3
    unit: "V"
    label: "Potentiometer"
    thresholdWarning: 2.5
    thresholdFault: 3.0
}
```

### ShStatDot (HMI Addition)

State LED indicator -- a small coloured dot showing system state.

| Property | Type   | Default  | Description                             |
| -------- | ------ | -------- | --------------------------------------- |
| `state`  | string | `"idle"` | State: `"ok"`, `"warn"`, `"fault"`, `"idle"` |
| `size`   | int    | `12`     | Diameter in px                          |

Colours: ok = success, warn = warning, fault = destructive (with pulse
animation), idle = mutedForeground.

```qml
ShStatDot { state: Tags.di_estop ? "fault" : "ok" }
```

### ShValueTile (HMI Addition)

Large numeric readout tile for dashboards. Combines a value display with label,
unit, and state badge in a card-styled container.

| Property | Type   | Default  | Description                      |
| -------- | ------ | -------- | -------------------------------- |
| `value`  | string | `"--"`   | Displayed value (string for formatting control) |
| `label`  | string | `""`     | Description label                |
| `unit`   | string | `""`     | Unit suffix                      |
| `state`  | string | `"idle"` | State for the badge              |

```qml
ShValueTile {
    value: Tags.ai_pot !== null ? Tags.ai_pot.toFixed(2) : "--"
    label: "Potentiometer"
    unit: "V"
    state: "ok"
}
```

### ShIcon

Renders a Tabler icon from the vendored registry.

| Property | Type   | Default              | Description               |
| -------- | ------ | -------------------- | ------------------------- |
| `name`   | string | `""`                 | Tabler icon name          |
| `size`   | int    | `18`                 | Render size in px         |
| `color`  | color  | `Theme.foreground`   | Stroke colour             |

Unknown names render a visible placeholder (grey box with "?") and log a
`console.warn`. They never throw an exception.

```qml
ShIcon { name: "upload"; size: 18; color: Theme.foreground }
ShIcon { name: "sun"; size: 24; color: Theme.warning }
```

---

## Available Icons (Tabler, outline set)

All icons from CONTRACT 11.3 are vendored:

`upload`, `download`, `plug`, `plug-connected`, `plug-off`, `refresh`,
`rotate-clockwise`, `device-desktop`, `device-imac`, `cpu`, `server`,
`terminal-2`, `file-code`, `folder-open`, `folder-plus`, `trash`, `settings`,
`adjustments`, `sun`, `moon`, `alert-triangle`, `circle-check`, `circle-x`,
`info-circle`, `loader-2`, `player-play`, `player-stop`, `power`, `bolt`,
`activity`, `gauge`, `wifi`, `wifi-off`, `key`, `search`, `plus`, `x`,
`chevron-down`, `chevron-right`, `clipboard-text`, `history`

---

## Theming

### Runtime Theme Switching (QML)

```qml
import Shadcn 1.0

// Switch to dark mode
Theme.mode = "dark"

// Switch to light mode
Theme.mode = "light"
```

All components bind their colours to `Theme` properties, so changing `Theme.mode`
instantly recolours every visible element.

**Convention:** The on-target HMI defaults to `Theme.mode = "dark"`. The host
deployer defaults to `"light"` with a toggle.

### Runtime Theme Switching (Qt Widgets)

```python
from ui.python.shadcn import apply

# Switch theme
apply(app, "dark")   # re-applies stylesheet + palette
apply(app, "light")
```

### Regenerating the QSS Files

If you modify `tokens.json`, regenerate the committed QSS files:

```python
from ui.python.shadcn import generate_qss_files
generate_qss_files()
```

Or from the command line:

```bash
python -c "from ui.python.shadcn import generate_qss_files; generate_qss_files()"
```

---

## Font Fallback on the Toradex Reference Image

The preferred font is **Inter** (the shadcn default), but it is not included in
the Toradex Yocto Reference Multimedia Image.

**Fallback chain:** `Inter -> Noto Sans -> DejaVu Sans -> sans-serif`

The reference image ships **DejaVu Sans**, so that is the guaranteed fallback.
If the integrator installs `noto-fonts` via the Yocto layer, Noto Sans will be
used instead.

**Layout shift mitigation:** All three fonts have similar metrics (x-height,
cap-height, average character width). The design uses integer px sizes and
explicit component heights, so the layout remains stable regardless of which
font the system resolves.

If pixel-perfect fidelity to the shadcn upstream is required, add Inter to the
Yocto image via a custom recipe or place the `.ttf` files in the app bundle and
load them with `FontLoader` in QML:

```qml
FontLoader { source: "fonts/Inter-Regular.ttf" }
FontLoader { source: "fonts/Inter-Medium.ttf" }
FontLoader { source: "fonts/Inter-SemiBold.ttf" }
```

---

## Qt Widgets Stylesheet Details

The generated QSS files style the following widgets:

| Widget                          | Styled as                          |
| ------------------------------- | ---------------------------------- |
| `QWidget`                       | Base: background, foreground, font |
| `QMainWindow`                   | Background colour                  |
| `QPushButton`                   | ShButton (variant via `variant` property) |
| `QLineEdit`                     | ShInput                            |
| `QComboBox`                     | Dropdown with styled arrow         |
| `QLabel`                        | Foreground, font                   |
| `QGroupBox`                     | Card (border, radius, title)       |
| `QPlainTextEdit` / `QTextEdit`  | Console surface (muted bg, mono)   |
| `QTabWidget` / `QTabBar`        | ShTabs                             |
| `QProgressBar`                  | ShProgress                         |
| `QCheckBox` / `QRadioButton`    | Styled indicators                  |
| `QListWidget` / `QTreeView`     | Item styling, selection            |
| `QToolTip`                      | Popover styling                    |
| `QMenu`                         | Popover with hover                 |
| `QScrollBar`                    | Thin (8px), rounded, muted         |
| `QSplitter`                     | Thin handle                        |
| `QStatusBar`                    | Border-top, muted bg               |

To use the `variant` property on `QPushButton`:

```python
from PySide6.QtWidgets import QPushButton

btn = QPushButton("Delete")
btn.setProperty("variant", "destructive")
```

---

## Python API Reference

```python
from ui.python.shadcn import (
    FONT_STACK,          # tuple: ('Inter', 'Noto Sans', 'DejaVu Sans', 'sans-serif')
    load_tokens,         # (path=None) -> dict
    color,               # (name, theme='light') -> str  e.g. '#020817'
    qss,                 # (theme='light') -> str
    apply,               # (app, theme='light') -> None
    qml_import_path,     # () -> str  (absolute path to ui/qml/)
    icon,                # (name, size=18, color=None) -> QIcon
    generate_qss_files,  # () -> None
)
```

---

## Testing

Run the token-drift test (verifies Theme.qml matches tokens.json):

```bash
python ui/tests/test_tokens.py
```

Run the visual gallery (offscreen rendering for CI):

```bash
QT_QPA_PLATFORM=offscreen python ui/gallery.py --theme light --screenshot /tmp/light.png --exit-after 2500
QT_QPA_PLATFORM=offscreen python ui/gallery.py --theme dark  --screenshot /tmp/dark.png  --exit-after 2500
```

On Windows (PowerShell):

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python ui/gallery.py --theme light --screenshot "$env:TEMP/light.png" --exit-after 2500
python ui/gallery.py --theme dark  --screenshot "$env:TEMP/dark.png"  --exit-after 2500
```
