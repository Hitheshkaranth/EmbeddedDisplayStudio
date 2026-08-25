<div align="center">

<img src="docs/assets/banner.jpg" alt="EmbeddedDisplay Studio" width="900" />

### Bring Your Own App — HMI platform for Toradex Verdin i.MX8M Plus

Ship the panel once. Let anyone drop their own Qt app onto it in seconds — over SSH, with no rebuild, no image reflash, and no hardware code in the app.

<br />

[![Platform](https://img.shields.io/badge/SoM-Toradex%20Verdin%20i.MX8M%20Plus-0b7285?style=for-the-badge)](https://www.toradex.com/computer-on-modules/verdin-arm-family/nxp-imx-8m-plus)
[![Yocto](https://img.shields.io/badge/Yocto-Reference%20Multimedia%20Image-4a7ebb?style=for-the-badge&logo=yocto&logoColor=white)](https://developer.toradex.com/linux-bsp/)
[![Wayland](https://img.shields.io/badge/Display-Wayland%20%2F%20Weston-1a3d7c?style=for-the-badge)](https://wayland.freedesktop.org/)
[![systemd](https://img.shields.io/badge/Init-systemd%20native-30363d?style=for-the-badge&logo=systemd&logoColor=white)](https://systemd.io/)

[![Qt](https://img.shields.io/badge/Qt%206-QML%20%2F%20PySide6-41cd52?style=for-the-badge&logo=qt&logoColor=white)](https://doc.qt.io/qtforpython-6/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![libgpiod](https://img.shields.io/badge/GPIO-libgpiod%20v1%20%2B%20v2-f59e0b?style=for-the-badge)](https://libgpiod.readthedocs.io/)
[![IIO](https://img.shields.io/badge/ADC-Linux%20IIO-ef4444?style=for-the-badge)](https://www.kernel.org/doc/html/latest/driver-api/iio/index.html)

[![Design system](https://img.shields.io/badge/UI-shadcn%2Fui%20port-020817?style=for-the-badge)](https://github.com/shadcn-ui/ui)
[![Icons](https://img.shields.io/badge/Icons-Tabler-206bc4?style=for-the-badge&logo=tabler&logoColor=white)](https://github.com/tabler/tabler-icons)
[![Tests](https://img.shields.io/badge/tests-153%20passing-22c55e?style=for-the-badge)](tests/)
[![CI](https://img.shields.io/badge/CI-Linux%20full%20suite-2088ff?style=for-the-badge&logo=githubactions&logoColor=white)](.github/workflows/ci.yml)
[![No Docker](https://img.shields.io/badge/containers-none-64748b?style=for-the-badge&logo=docker&logoColor=white)](#why-no-containers)

</div>

---

<div align="center">

<img src="docs/assets/screenshot-studio.png" alt="The Studio window, connected to a panel" width="900" />

<em>A customer's application running inside a live preview of the panel, beside
the target it deploys to — connected here to a 10.1" 1024 x 768 SOM.</em>

</div>

---

## The idea

A machine builder ships one panel image. Their customers — or their own app team —
write a Qt/QML application and push it to the panel with a single command. The
app never touches a GPIO line, an ADC node or a serial port: it binds to **tags**
that arrive over a loopback socket, and the platform does the rest.

```
        YOUR LAPTOP                                   THE PANEL
 ┌──────────────────────────┐                ┌────────────────────────────────┐
 │  EmbeddedDisplay Studio  │                │  hmi-gui.service               │
 │   drag in a Qt app       │   scp bundle   │   loader + tag engine          │
 │   see it in a real bezel │ ─────────────► │   /opt/hmi_apps/current        │
 │   one-click deploy       │   ssh install  │            ▲                   │
 ├──────────────────────────┤                │            │ UDP/JSON          │
 │  deploy_to_hmi.sh        │                │            ▼                   │
 │   the same thing, in CI  │                │  hmi-hwd.service               │
 └──────────────────────────┘                │   libgpiod · IIO · UART        │
                                             └────────────────────────────────┘
```

Three layers, deliberately decoupled:

| | Layer | Owns | Knows nothing about |
|---|---|---|---|
| **1** | `hmi-hwd` — hardware abstraction daemon | GPIO, ADC, UART, safe states | pixels |
| **2** | `hmi-gui` — app loader + tag engine | QML, bindings, the customer bundle | hardware |
| **3** | deployment | atomic install, health check, rollback | either of the above |

---

## Quick start

**On your laptop — no hardware needed.** The daemon simulates I/O so the whole
stack runs on a desktop.

```bash
python -m pip install PySide6

# terminal 1 — simulated hardware
python daemon/hmi_hwd.py --config daemon/hwd.json --sim

# terminal 2 — the panel UI, in a window
python gui/hmi_loader/main.py --apps-dir apps/demo-app --windowed

# terminal 3 — EmbeddedDisplay Studio
python -m tools.hmi_deployer.app
```

**On the panel.**

```bash
ssh-copy-id root@<panel-ip>                       # once
./deploy/deploy_to_hmi.sh -H <panel-ip> -b ./my-qt-app
```

If the panel is running a stock image rather than one built from
`yocto/meta-hmi`, install the platform onto it first — no reflash needed:

```bash
python deploy/provision_panel.py --host <panel-ip> --check   # survey only
python deploy/provision_panel.py --host <panel-ip>
```

`--check` surveys the board and names anything that would stop it hosting the
platform. Read it before assuming a stock image is ready: a **base** Toradex
image ships `python3-core` alone — no `json`, no `socket`, no `ctypes` — and no
Qt, which is enough to stop the installer, the loader and any application. See
[`deploy/README.md`](deploy/README.md#what-a-minimal-image-is-still-missing) for
what to add and where the scripts expect it.

If the new app fails to render within 25 s, the panel **rolls itself back** to the
previous release and the command exits non-zero. A bad deploy cannot leave a
machine without a UI.

A successful deploy also makes the app the panel's **boot default**: once the
release has been proven to render, `hmi-gui.service` is enabled, so a power
cycle brings the same application back with no further action. Deploying is the
only step — there is nothing to enable by hand afterwards.

---

## Writing an app

A bundle is a directory. Two files are enough.

```
my-qt-app/
├── manifest.json
└── main.qml
```

```json
{
  "schema": 1,
  "name": "line-controller",
  "version": "1.4.0",
  "entry": "main.qml",
  "runtime": "qml",
  "screen": { "width": 1280, "height": 800 },
  "tags_required": ["ai.pot", "di.estop", "do.relay1"]
}
```

Only four fields are required — `schema`, `name`, `version` and `entry`. The
rest are optional: `screen` defaults to 1280x800, `tags_required` to none,
`runtime` to `qml`. This is the smallest manifest that validates:

```json
{ "schema": 1, "name": "line-controller", "version": "1.4.0", "entry": "main.qml" }
```

`runtime` is optional and defaults to `qml`:

| runtime | entry | How it runs on the panel |
| --- | --- | --- |
| `qml` | `*.qml` | Loaded into the shell that is already running. Gets `Tags`/`Bus` injected, previews live in Studio. |
| `python` | `*.py` | Exec'd as the GUI process itself — for an existing Qt Widgets application that owns its own window. |

### Qt5 and Qt6 applications on the same panel

A native Python app also declares which binding it imports, because the two
cannot share an interpreter — PySide2 is Qt5-only and was never built past
Python 3.11:

```json
{ "runtime": "python", "entry": "main.py", "qt_binding": "pyside2", "qt": ">=5.15" }
```

| qt_binding | Runtime on the panel | For |
| --- | --- | --- |
| `pyside6` (default) | `/opt/hmi-python` — CPython 3.12 + PySide6 | Qt6 apps, and the QML loader |
| `pyside2` | `/opt/hmi-python-qt5` — CPython 3.11 + PySide2 + a private Qt 5.15 | Existing Qt5 apps |

The Qt5 runtime is not installed by default. Add it once per panel:

```bash
./deploy/provision_pyside2.sh --host <panel-ip>     # run from Linux or WSL
```

It ships its own Qt 5.15 rather than using the one already on the Toradex
image, because that is an i.MX **GLES** build while every available aarch64
PySide2 binary is compiled against desktop GL — loading one against the other
fails with `undefined symbol: _ZTI18QOpenGLTimeMonitor`. The panel's own Qt5 is
left untouched.

Already have a Qt app? Open it in Studio; it detects the entry point **and
the binding**, and writes the manifest for you.

Build outputs, caches and VCS metadata are left out of the bundle
automatically, by both the CLI and Studio — they share one packer, so the
same folder produces a byte-identical tarball either way. For anything else that
lives in the folder but is not part of the running application — source
archives, packaged installers, capture logs — add a `.hmiignore` next to the
manifest, one glob per line.

```qml
import QtQuick
import Shadcn 1.0          // the design kit ships on the device

ShCard {
    ShGauge {
        label: "Input Voltage"
        value: Bus.value("ai.pot", 0)     // missing tags degrade, never crash
        minValue: 0; maxValue: 3.3; unit: "V"
        thresholdWarning: 2.5; thresholdFault: 3.0
    }

    ShSwitch { onToggled: Bus.write("do.relay1", checked) }

    ShBadge {
        text: Tags.online ? "ONLINE" : "LINK LOST"
        variant: Tags.online ? "success" : "destructive"
    }
}
```

Two context properties are injected for you:

* **`Tags`** — live values, bound declaratively. Dots become underscores, so
  `ai.pot` reads as `Tags.ai_pot`. `Tags.online` tracks the hardware link.
* **`Bus`** — commands and safe reads: `Bus.write()`, `Bus.pulse()`,
  `Bus.uart_tx()`, `Bus.value(name, fallback)`.

`Bus.value()` is the habit worth forming: it returns your fallback for a tag that
is missing, null, or not published yet, so a screen written against a sensor that
isn't fitted still renders.

---

## EmbeddedDisplay Studio

The desktop tool. Import a bundle, watch it run inside a photo-real mock-up of
the panel, then push it.

* **True WYSIWYG** — the bezel contains a live QML engine rendering *your actual
  app* at target resolution with the same tag engine the device runs. Not a
  screenshot, not an approximation.
* **Live or simulated data** — connected, telemetry is relayed from the real
  daemon over SSH; offline, a built-in simulator drives plausible values.
* **Validation before upload** — every manifest rule is checked host-side, with
  the offending field named.
* **Scaffold** — "New App…" writes a valid starter bundle, already importing the
  design kit.
* **Panel picker** — preview against 5.0" 800×480, 7" 1024×600, 7"/10.1"/12.1"
  1280×800 or 15.6" 1920×1080, with the live resolution reported under the
  bezel. The preview never shrinks below a readable size and always holds the
  panel's aspect ratio.
* **Adopts apps that were never written for this platform** — point it at an
  existing Qt project with no `manifest.json` and it detects the entry point,
  proposes a manifest and writes it for you.
* **Qt Widgets apps preview live too.** A `runtime: python` bundle owns its own
  window, so it cannot be composited into the QML scene. It is run unmodified
  in a child process instead, forced to the target resolution, and its frames
  are streamed into the bezel — so you see the real application, with real
  fonts, before you deploy it. Nothing appears on your desktop: the window is
  kept unmapped with `WA_DontShowOnScreen`. A PySide2 bundle needs a PySide2
  interpreter on your machine; point `HMI_PREVIEW_PYTHON_QT5` at one, or skip
  it — the bundle still deploys and runs on the panel's own Qt5 runtime.
* **Nothing blocks the window.** Packaging, upload, install, rollback,
  restart and journal tail all run on worker threads, and the bar reports
  the stage it is in — a sweeping bar while the bundle is packed, then bytes
  and throughput for the upload, then the installer's own steps as the panel
  reaches them. A step that fails names what failed: an unreachable panel is
  reported as an unreachable panel, not as whatever the step was trying to do.

<div align="center">

<img src="docs/assets/screenshot-packaging.png" alt="Dependency check before packaging" width="860" />

<em>Creation of the package from the input GUI: the application's imports are
read, the panel is asked whether it can import each one, and the bar reports
the stage.</em>

<br /><br />

<img src="docs/assets/screenshot-installing.png" alt="Installing on the hardware" width="860" />

<em>Uploading the GUI onto the hardware: the installer's own steps arrive as
the panel reaches them, down to the release it is switching to.</em>

<br /><br />

<img src="docs/assets/screenshot-dark.png" alt="Studio in dark mode" width="860" />

<em>Dark mode.</em>

<br /><br />

<img src="docs/assets/screenshot-hmi.png" alt="The panel UI" width="720" />

<em>The panel screen, bound to live tags.</em>

</div>

---

## The tag protocol

JSON over UDP on loopback. Deliberately boring, so anything can speak it.

```jsonc
// daemon → clients, every 100 ms
{ "t": "tags", "seq": 4711, "ts": 1755600000.123,
  "tags": { "ai.pot": 1.842, "di.estop": false, "do.relay1": true } }

// client → daemon
{ "id": "c-17", "cmd": "set", "tag": "do.relay1", "value": 1 }
{ "t": "ack", "id": "c-17", "ok": true }
```

| Prefix | Meaning | Writable |
|---|---|---|
| `ai.` | analog input (IIO ADC), float | — |
| `di.` | digital input (GPIO), bool | — |
| `do.` | digital output (GPIO), bool | **yes** |
| `uart.` | serial link | `uart.tx` |
| `sys.` | daemon health | — |

A tag whose hardware read failed is published as `null`, never omitted — so a QML
binding always resolves. The full specification is [`docs/CONTRACT.md`](docs/CONTRACT.md).

---

## Built for the field

**The daemon cannot be crashed by its socket.** Malformed JSON, wrong types,
oversized frames, binary noise and invalid UTF-8 are counted and answered with a
typed error code — or with silence where no correlation id can be recovered,
which also stops it being used as a UDP reflector. Logging is rate-limited so a
flooding client cannot fill the journal. Outputs are driven to configured safe
states on `SIGTERM`, and systemd watchdog keep-alives are sent every cycle.

**Deployment is atomic and self-healing.** The bundle lands in a tmpfs, so a
failed upload never touches flash. It is checksum-verified, extracted to a
staging directory, validated again on the target, then promoted by a single
`rename(2)` onto the `current` symlink — never `rm` then `ln`, which would leave a
window with no UI. The GUI must recreate its ready-file within 25 s or the
symlink swaps back.

**Validation happens twice, from one implementation.** The host CLI, the target
installer and the desktop tool all call `schema/manifest.py`; the target still
validates independently of the host, as it must, but not by different rules.
They used to be three separate implementations that had drifted apart in both
directions — a bundle that passed on a laptop and was refused on the panel is
worse than one that fails everywhere.

**Both libgpiod generations.** BSP 6 ships libgpiod 1.6, BSP 7 ships 2.x, and
their Python APIs are incompatible. Both are implemented and selected at import.

---

## Design system

Every pixel — on the panel and on the desktop — comes from a Qt port of
[shadcn/ui](https://github.com/shadcn-ui/ui) with [Tabler](https://github.com/tabler/tabler-icons)
icons vendored offline. Same tokens, same variant names, same geometry.

`ShButton` · `ShInput` · `ShCard` · `ShBadge` · `ShSwitch` · `ShProgress` ·
`ShSeparator` · `ShAlert` · `ShTabs` · `ShLabel` · `ShSkeleton` · `ShDialog`
— plus HMI additions `ShGauge`, `ShStatDot`, `ShValueTile`.

```bash
python ui/gallery.py --theme dark      # every component, every state
```

Light and dark are switchable at runtime; the panel defaults to dark, the desktop
tool to light. `ui/tokens.json` is the single source of truth, and a test fails
if `Theme.qml` ever drifts from it.

---

## Layout

```
docs/CONTRACT.md      the normative interface spec — read this first
schema/               shared formats: manifest validation, bundle packing
daemon/               Layer 1  hardware daemon + tag map
gui/                  Layer 2  loader, tag engine, shell, fallback screen
apps/demo-app/        a worked example, and the pipeline's test fixture
ui/                   design system: tokens, QML kit, QSS, icons, gallery
target/               systemd units, atomic installer, Wayland launcher
deploy/               deploy_to_hmi.sh — the CLI; provision_panel.py — onboard a stock image
tools/hmi_deployer/   EmbeddedDisplay Studio
yocto/meta-hmi/       bitbake layer that puts it all in the image
tests/                protocol, integration and cross-validator suites
```

---

## Verification

```bash
python tests/run_all.py          # 153 tests
```

| Area | Coverage |
|---|---|
| Daemon protocol | error codes, silence on unparseable input, `seq` monotonicity, survives hostile frames |
| Tag engine | daemon → UDP → QML binding, command write-back, fallback on missing tags |
| Bundle validation | one implementation, three callers; minimal, README and malformed manifests |
| Install atomicity | unique release ids, running release survives redeploy, traversal refused before extraction |
| Fallback screen | the card lays out, sections do not overlap, the error text is shown |
| Design tokens | `tokens.json` and `Theme.qml` cannot drift |
| Gallery render | painted pixels asserted, not just "it ran" |
| Native preview | a real Qt Widgets app renders at the target resolution with content |

> **Run the installer tests on Linux.** Windows has no `flock`, so the
> atomic-swap and cross-validator suites skip there rather than pretending to
> pass — and the runner prints how many tests skipped, because a skip is not a
> pass. CI runs the whole suite on Linux and fails if anything skips.
> `tests/README.md` has the WSL command.

---

## Building the image

```bash
bitbake-layers add-layer /path/to/meta-hmi
bitbake tdx-reference-multimedia-image
```

`yocto/README.md` covers prerequisite layers (including the meta-qt6 caveat for
PySide6), how each recipe's `files/` directory maps onto this repository, and how
to verify on the target.

### Why no containers

This targets the **native** Toradex Yocto reference image. No Docker, no
TorizonOS, no container runtime — every component is a systemd unit on the
rootfs. Less to boot, less to update, less to explain to a certification body.

---

## Before first power-on

GPIO offsets, IIO device names and UART aliases are **board specific**.
`daemon/hwd.json` ships a documented default for a Verdin i.MX8M Plus on a
Dahlia carrier. Confirm yours:

```bash
gpioinfo                 # GPIO chip and line offsets
iio_info                 # ADC device name and channels
ls /dev/verdin-*         # stable UART aliases
```

Pins must first be released from their default pinmux with a Toradex device-tree
overlay (`/boot/overlays.txt`). `daemon/README.md` walks through it.

---

<div align="center">

**MIT licensed.** Tabler Icons are MIT — see `ui/icons/LICENSE.tabler`.

</div>
