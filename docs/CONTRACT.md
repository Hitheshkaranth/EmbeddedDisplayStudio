# BYOA HMI — Binding Interface Contract (v1)

**Status: NORMATIVE.** Every component in this repository is written against this
document. Do not invent alternative names, ports, paths or JSON shapes; if
something here looks wrong, change this document first.

Target: Toradex Verdin **i.MX8M Plus**, **native Toradex Yocto Reference
Multimedia Image**, systemd. **No Docker, no TorizonOS, no containers.**
Everything runs on the rootfs as systemd units. **No Qt and no compositor on
the panel:** the GUI (`hmi-ui`, `native/hmi-ui`, C + LVGL) draws to DRM/KMS
itself and interprets the deployed design file directly.

---

## 1. Three decoupled layers

```
 ┌────────────────────────────┐   UDP/JSON 127.0.0.1   ┌────────────────────────┐
 │ hmi-hwd (Layer 1)          │  :5000  commands  ◄────│ hmi-ui   (Layer 2)     │
 │ GPIO / IIO-ADC / UART      │  :5001  telemetry ────►│ C + LVGL on DRM/KMS    │
 │ ONLY process touching HW   │                        │ ZERO driver code       │
 └────────────────────────────┘                        └──────────┬─────────────┘
                                                                  │ interprets
                                          /opt/hmi_apps/current/project.edsui
                                                                  ▲
                                          SCP → /tmp/hmi_upload (tmpfs) → atomic
                                          swap ← hmi-install ← deploy (Layer 3)
```

The GUI is a **pure UDP client**. It never opens `/dev/gpiochip*`, `/sys/bus/iio`
or a serial port. The daemon never draws anything.

---

## 2. Wire protocol (JSON over UDP, loopback only)

Encoding: UTF-8, one JSON **object** per datagram, no framing, no newline
required. Max accepted datagram: **8192 bytes** (larger is dropped + counted).

### 2.1 Endpoints

| Direction | Default socket | Notes |
| --- | --- | --- |
| Client → daemon (commands) | `127.0.0.1:5000` | daemon binds this |
| Daemon → client (telemetry) | `127.0.0.1:5001` | static sink, always sent |
| Daemon → dynamic subscribers | learned from `subscribe` | TTL 5 s |

### 2.2 Commands (client → daemon)

```jsonc
{"id":"c-17","cmd":"set",   "tag":"do.relay1", "value":1}      // 0/1/true/false
{"id":"c-18","cmd":"pulse", "tag":"do.relay1", "ms":250}       // 1..10000
{"id":"c-19","cmd":"uart_tx","data":"PING\r\n"}                // optional link
{"id":"c-20","cmd":"subscribe","ttl":5}                        // reply-addr sink
{"id":"c-21","cmd":"unsubscribe"}
{"id":"c-22","cmd":"list"}                                     // tag catalogue
{"id":"c-23","cmd":"ping"}
```

`id` is optional and opaque (max 64 chars). Unknown fields are ignored.

### 2.3 Acknowledgement (daemon → sender, only when `id` present, or for
`ping`/`list`)

```jsonc
{"t":"ack","id":"c-17","ok":true}
{"t":"ack","id":"c-17","ok":false,"err":"unknown_tag"}
```

Error codes (closed set): `bad_json`, `not_an_object`, `too_large`,
`unknown_cmd`, `unknown_tag`, `not_writable`, `bad_value`, `hw_error`,
`rate_limited`, `no_history` (13.4).

### 2.4 Telemetry frame (daemon → subscribers, default every 100 ms)

```jsonc
{
  "t": "tags",
  "seq": 4711,
  "ts": 1755600000.123,          // float, CLOCK_REALTIME seconds
  "src": "hmi-hwd",
  "tags": {
    "ai.pot":     1.842,          // float volts, or null if the read failed
    "di.estop":   false,          // bool
    "do.relay1":  true,           // bool (read-back of the driven state)
    "sys.uptime": 1234.5,         // float seconds
    "sys.errors": 0               // int, cumulative hardware error count
  }
}
```

A tag whose hardware read failed is published as `null` — **never omitted**, so
QML bindings stay resolvable. `seq` increments monotonically and wraps at 2^31.

### 2.5 Tag naming

`^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$` — lowercase, dot-separated. Reserved prefixes:

| Prefix | Meaning | Writable |
| --- | --- | --- |
| `ai.` | analog input (IIO ADC), float | no |
| `di.` | digital input (GPIO in), bool | no |
| `do.` | digital output (GPIO out), bool | **yes** |
| `mb.` | Modbus TCP tag (coil/discrete/holding/input) | **yes** (coil/holding with `writable: true`) |
| `uart.` | serial link tags | `uart.tx` only |
| `sys.` | daemon health/diagnostics (incl. `sys.modbus_online`) | no |

Modbus tags are registered under the `modbus` section of `hwd.json`. Each tag specifies a `kind` (coil, discrete, holding, input), a 0-based `address`, a `type` (bool for coils/discrete, int16/uint16/int32/uint32/float32 for holding/input), and optional `scale`/`offset`/`word_order` fields. The daemon polls all configured Modbus tags in a background thread and updates the tag store on each poll cycle. Read failures set the tag to `null` (never omit). A write to a Modbus holding register encodes the value using the configured `type` and `scale`/`offset`, then writes via FC 6 (single register) or FC 16 (multiple registers).

**QML alias:** dots are illegal in QML property names, so the Tag Engine also
exposes each tag with `.` replaced by `_` (`ai.pot` → `Tags.ai_pot`). Commands
always use the raw dotted name.

---

## 3. Filesystem layout on target

| Path | Owner | Purpose |
| --- | --- | --- |
| `/usr/lib/hmi/hmi_hwd.py` | root:root 0755 | hardware daemon |
| `/usr/lib/hmi/modbus.py` | root:root 0644 | its Modbus TCP client, imported as a sibling module |
| `/usr/lib/hmi/manifest.py` | root:root 0644 | shared section 4 validator |
| `/usr/lib/hmi/ui/hmi-ui` | root:root 0755 | the GUI runtime (`native/hmi-ui`, aarch64 ELF) |
| `/usr/lib/hmi/kit/fonts/` | root:root 0755 | Inter fonts the runtime renders text with |
| `/usr/lib/hmi/kit/icons/` | root:root 0755 | Tabler icons as 96 px PNGs (`schema/gen_icons.py`) |
| `/usr/bin/hmi-install` | root:root 0755 | target-side atomic installer |
| `/usr/bin/hmi-hwd-launch` | root:root 0755 | interpreter resolver + exec (daemon) |
| `/etc/hmi/hwd.json` | root:root 0644 | daemon config (tag → pin map) |
| `/etc/default/hmi-ui` | root:root 0644 | GUI env overrides (DRM device, touch node, log level) |
| `/opt/hmi_apps/releases/<id>/` | root:root 0755 | unpacked app releases |
| `/opt/hmi_apps/current` | symlink | → `releases/<id>`, atomically swapped |
| `/opt/hmi_apps/previous` | symlink | → the release `current` pointed at before |
| `/tmp/hmi_upload/` | root:root 0700 | **tmpfs** SCP landing zone |
| `/run/hmi/gui-ready` | root:root | touched by the GUI once the first page is on screen |
| `/run/hmi/install.lock` | root:root | `flock` for serialised installs |

Release id: `<name>-<UTC yyyymmddTHHMMSSZ>`, generated by `hmi-install` from
the **validated manifest**, never from the uploaded filename. The timestamp is
what makes it unique, and uniqueness is load-bearing: deriving the release
directory from a filename like `<name>-<version>.tar.gz` means redeploying the
same version resolves to the directory `current` already points at, and the
installer then deletes the release the panel is running before recording that
same directory as the rollback target.

Extraction goes to `releases/.stage.$$` and is renamed into place only after
validation, so a partially written release is never visible under its final
name.

Keep the **3** newest releases plus whatever `current` and `previous` point at;
prune the rest.

The kit directory is looked up as `$HMI_UI_KIT`, then `/usr/lib/hmi/kit`, then
`/usr/lib/hmi/qml/Shadcn` (where a panel provisioned for the retired Qt loader
had the fonts). Nothing under `/usr/lib/hmi/qml`, `/usr/lib/hmi/gui`,
`/usr/lib/hmi/shell` or `/usr/lib/hmi/qt6` is part of the platform any more;
`deploy/provision_panel.py` removes them from a panel that still has them.

Both interpreters (`hmi-install`, `hmi-hwd-launch`) resolve
Python in the same order: `$HMI_PYTHON`, then `/opt/hmi-python/bin/python3`,
then `/usr/bin/python3`. Nothing may name `/usr/bin/python3` directly: on a base
Yocto image that interpreter is `python3-core` alone, with no `json` and no
`asyncio`.

## 4. App bundle format (what a developer ships)

A gzip tarball whose members sit at the archive root, containing at minimum:

```
manifest.json
main.qml
<any other .qml, images, fonts, qmldir …>
```

`manifest.json`:

```jsonc
{
  "schema": 1,
  "name": "line-controller",            // ^[a-z0-9][a-z0-9._-]{0,63}$
  "version": "1.4.0",
  "entry": "main.qml",                  // relative, no "..", must exist
  "runtime": "qml",                     // "qml" (default) or "python"
  "screen": {"width": 1280, "height": 800},
  "tags_required": ["ai.pot", "di.estop", "do.relay1"],
  "qt": ">=6.5"
}
```

#### Required vs optional (NORMATIVE)

| Field | Required | Default when absent |
| --- | --- | --- |
| `schema` | yes | — (must equal 1) |
| `name` | yes | — |
| `version` | yes | — |
| `entry` | yes | — |
| `runtime` | no | `"qml"` |
| `screen` | no | `{"width": 1280, "height": 800}` |
| `tags_required` | no | `[]` |
| `qt` | no | unconstrained |
| `qt_binding` | no | `"pyside6"` (only meaningful when `runtime` is `python`) |
| `alarms` | no | `[]` (no alarm evaluation) |

An optional field that IS present is still type-checked. Absence is not an
error; a `screen` that is a string is.

#### Alarm definitions (`alarms`)

When present, `alarms` must be a list of alarm definition objects. Each object
describes a single tag-level alarm:

```jsonc
{
  "alarms": [
    {
      "tag": "ai.pressure",       // required, must match tag naming rule
      "label": "Pressure Alarm",  // optional, human-readable name
      "unit": " bar",             // optional, unit string
      "warning": {                // optional: at least one of warning/critical required
        "op": ">=",
        "value": 5.0
      },
      "critical": {
        "op": ">",
        "value": 8.0
      }
    }
  ]
}
```

**Validation rules:**

| Constraint | Rule |
| --- | --- |
| `tag` | Required, must match `^[a-z][a-z0-9]*(\.[a-z0-9_]+)+$` |
| `label` | Optional string |
| `unit` | Optional string |
| `warning` / `critical` | Optional objects with `op` and `value` |
| `op` | One of `">"`, `">="`, `"<"`, `"<="`, `"=="`, `"!="` |
| `value` | Required when `op` is present; must be a number (int or float, not bool) |
| Thresholds | At least one of `warning` or `critical` must be present |

Alarm tag names are collected at load time and added to the tag engine's
tracking set (CONTRACT C3), so the engine records history and evaluates alarms
for them.

This table exists because its absence caused a real divergence: three
implementations each guessed differently at which fields were mandatory. The
desktop tool required `qt`, `screen` and `tags_required` — so the manifest
printed in this document's own example section was rejected there — while the
host CLI and the target installer required `version`, which the desktop tool
never checked.

#### One implementation, two validations

Validation is performed **twice**: host-side before upload, target-side before
the swap. A bundle that fails validation must never reach `current`.

Both validations call the **same code**: `schema/manifest.py`, which is
installed onto the target at `/usr/lib/hmi/manifest.py`. The target still
validates independently of the host — that is the point of validating twice,
because a bundle can reach `/tmp/hmi_upload` without passing through any host
tool — but it does not validate by different rules.

Three copies of these rules could not be kept in agreement by testing them
against each other; the cross-validator suite passed throughout the divergence
because every fixture manifest was fully populated, so the fields only one
implementation cared about were never varied. One copy with three callers
cannot disagree at all.

### 4.1 Runtime kinds

`runtime` selects how the panel starts the app. It is optional; absent means
`"qml"`, so every manifest written before this field existed stays valid.

| `runtime` | `entry` | Execution model |
| --- | --- | --- |
| `edsui` | must end `.edsui` | **What the Studio writes.** `hmi-ui` interprets the design file directly: pages, widgets, bindings, actions and the manifest's alarms, with the tag engine and alarm engine built in. Nothing is generated for the panel; the Studio's `generated/` QML is its own preview and is excluded from the tarball (the manifest's `preview` key names it). The desktop previews an `edsui` bundle with `hmi-ui` itself, run headless, so the bezel, the Designer canvas and the Code section show what the panel draws; the generated QML is the fallback where no `hmi-ui` binary is at hand. |
| `qml` | must end `.qml` | Retired. Loaded by the Qt loader `hmi-gui` (`native/hmi-gui`, kept in the repo as a legacy fallback) into a QML engine. A Qt-free panel cannot start it. |
| `python` | must end `.py` | Retired. The app was the GUI process, exec'd by `hmi-gui-launch` under Wayland. A Qt-free panel cannot start it. |

A mismatch between `runtime` and the `entry` extension is a validation error,
because it would otherwise fail only on the target. Since all callers share
`schema/manifest.py`, this is enforced everywhere by construction.

The desktop tool previews every kind in the bezel. An `edsui` bundle's
`preview` QML and a `qml` bundle's entry are loaded into its QQuickWidget
directly. A `python` bundle cannot be composited into
another process's QML scene, so it is run unmodified in a child process at the
target resolution and its rendered frames are streamed back and painted into
the bezel; the window is kept off the screen with `WA_DontShowOnScreen` rather
than by selecting the offscreen platform plugin, which carries no font database
and would render every string as an empty box. Where that cannot run -- a
PySide2 bundle with no PySide2 interpreter on the host -- the bezel shows the
target geometry and an explicit note rather than a blank screen.

## 5. systemd units

| Unit | Type | Ordering |
| --- | --- | --- |
| `hmi-hwd.service` | `notify` (sd_notify `READY=1`, `WATCHDOG=1`) | `Before=hmi-ui.service`, `WantedBy=multi-user.target` |
| `hmi-ui.service` | `simple` | `After=hmi-hwd.service weston.service hmi-gui.service`, `Wants=hmi-hwd.service`, `Conflicts=weston.service hmi-gui.service`, `WantedBy=multi-user.target` |

Both `Restart=always`, `RestartSec=2`. The GUI must survive the daemon being
absent (shows "link lost", keeps rendering). `hmi-ui` opens the DRM device
itself, so a compositor left over from an earlier provisioning is stopped by
`Conflicts=` rather than shared with; `ExecStartPre` waits for it to release
the DRM master before the first modeset.

## 6. Deployment sequence (Layer 3, atomic)

1. Host validates the bundle, tars + `sha256sum`s it.
2. `scp` bundle + `.sha256` → `/tmp/hmi_upload/` (tmpfs — a failed upload never
   touches flash).
3. `ssh <target> hmi-install /tmp/hmi_upload/<file>.tar.gz`.
4. Target: `flock` → verify sha256 → extract to `releases/.stage.$$` → validate
   manifest → `rename()` stage → `releases/<id>`.
5. Atomic swap: create `.current.new` symlink → `os.replace()` onto `current`
   (`rename(2)`; **do not** `rm` then `ln` — that leaves a window with no UI).
6. `rm -f /run/hmi/gui-ready`; `systemctl restart hmi-ui.service`; wait ≤ 25 s
   for `/run/hmi/gui-ready`.
7. On timeout → swap the symlink back to the previous release, restart, exit
   non-zero. Deployment is therefore **self-rolling-back**.
8. Prune old releases, wipe the tmpfs upload.

`hmi-install` must reject any bundle path outside `/tmp/hmi_upload/` (it is
intended to be usable as a forced SSH command).

## 7. Reliability rules (non-negotiable)

* **Daemon:** no ingress path may raise out of the datagram handler. Malformed
  JSON, wrong types, oversized frames, hostile values → counted, rate-limited
  log line (max 1 per 5 s per error class), `ack{ok:false}` if `id` present.
  Never `exit()` on a hardware error; degrade the tag to `null`.
* **Daemon:** drive all outputs to their configured safe state on SIGTERM/SIGINT
  and release the GPIO lines.
* **GUI:** a missing tag must render a placeholder, never a QML error. Seed the
  tag map with defaults from `tags_required` at startup.
* **GUI:** if the app bundle fails to load, show the built-in fallback screen
  with the error text — never a black screen.
* **Both:** structured logging to stdout/stderr (journald captures it); no
  `print()` debugging left behind.
* Every script: `set -euo pipefail`, `trap` cleanup, no unquoted expansions.
* **Installer:** reject unsafe archive members — absolute paths, `..`
  components, links resolving outside the bundle, non-regular members —
  **before** extracting. Checking the extracted tree cannot work: a member that
  escaped is by definition not in the directory being walked.
* Never write `cmd` followed by `[ $? -ne 0 ]` under `set -e`: the shell has
  already exited and the check is dead code. Use `if ! cmd; then`. The same
  applies to `var=$(cmd)` whose status you intend to inspect — append
  `|| true` and test the captured output.

### 7.1 Documentation standard (NORMATIVE — applies to every file)

This is a long-lived industrial codebase that will be handed to integrators, so
it is documented to a level most projects would call excessive. That is
deliberate.

* **File header** on every source file: what it is, which layer it belongs to,
  its inputs/outputs, and any contract section it implements.
* **Every function, method, class and signal**: a docstring/comment block
  giving purpose, each parameter (with unit and valid range), the return value,
  raised exceptions/error paths, and any side effect (I/O, hardware state,
  blocking). Python uses docstrings; QML/JS uses `/** ... */`; bash uses a
  `# ---- name() ----` block above the function listing `Args:`/`Returns:`/
  `Exits:`.
* **Every declared variable, constant, property and config key** gets a comment
  stating what it holds, its unit (V, ms, px, bytes) and why that value —
  including QML `property` declarations and bash globals. Loop counters and
  self-evident temporaries are exempt; anything carrying a magic number is not.
* Explain *why*, not *what*, wherever the code already says what.
* No commented-out code, no stale comments. A comment that contradicts the code
  is a defect.

## 8. Hardware notes for the Verdin i.MX8M Plus

* GPIO is accessed **only** through libgpiod character devices
  (`/dev/gpiochipN`); sysfs GPIO is deprecated and must not be used. Support
  **both** libgpiod 1.x (`gpiod.Chip`/`get_line`) and 2.x
  (`gpiod.request_lines`/`LineSettings`) — BSP 6 ships 1.6.x, BSP 7 ships 2.x.
* ADC is read through IIO sysfs: `/sys/bus/iio/devices/iio:deviceN/`, value =
  `(raw + offset) * scale`, `scale` in **mV** for voltage channels. The device
  must be resolved **by its `name` attribute**, never by a hard-coded index —
  on Verdin i.MX8M Plus the analog inputs come from an external I²C IIO device,
  so channel numbering differs per carrier board. Confirm with `iio_info`.
* Pins must be freed from their default pinmux via a Toradex device-tree overlay
  (`/boot/overlays.txt`) before the daemon can claim them. Document, don't guess.
* Serial: prefer the stable `/dev/verdin-uartN` aliases over `/dev/ttymxcN`.
* Modbus TCP: the daemon uses a pure-stdlib TCP client (no pyModbus3, no minimalmodbus).
  It supports FC 1, 2, 3, 4, 5, 6, 16. Transaction IDs are monotonically increasing
  and echoed by the device. The poll loop runs in a background thread and is independent
  of the asyncio event loop. The Modbus module is imported from `daemon/modbus.py` (stdlib-only, no external deps).
  On target it is installed beside the daemon as `/usr/lib/hmi/modbus.py` (section 3).
  `--sim` mode uses an in-memory `ModbusSim` that tracks register/coil state locally.

## 9. Alarm and history semantics (C2 + C3)

### 9.1 Manifest alarm definitions

A manifest may include an optional `"alarms"` array. Each entry describes a
threshold-based alarm bound to a single tag (CONTRACT 4.1, §4). The alarm engine
runs inside the tag engine (Bus/TagEngine) — it does not speak to the daemon.

### 9.2 History ring buffer

The tag engine maintains a per-tag ring buffer that records every numeric value
received on every telemetry frame.

* **Recorded tags:** every tag in `tags_required` plus every tag referenced in
  `alarms[*].tag`. Tags that arrive on the wire but are not tracked are NOT
  recorded.
* **Value conversion:** booleans are stored as 0/1. `null` values are skipped
  (a failed hardware read does not corrupt the buffer).
* **Depth:** configurable via `TagEngine(..., history_depth=N)`. Default 600
  (60 s at 10 Hz). When the buffer is full, the oldest sample is dropped.
* **QML API:** `Bus.history(tag, n)` returns the last ≤ n samples, oldest first,
  as a `QVariantList`. Unknown tags return an empty list.
* **Version:** `Bus.historyVersion` increments by one on every telemetry frame,
  so QML bindings that depend on history re-evaluate once per frame.

### 9.3 Alarm evaluation

Alarms are evaluated on every telemetry frame against the current tag values.

* **Activation:** an alarm activates when the threshold condition is met.
  Condition: `tag_value <op> threshold_value`, where `<op>` is one of `>`,
  `>=`, `<`, `<=`, `==`, `!=`.
* **Dual thresholds:** each alarm may define both `warning` and `critical`.
  If both are met, `critical` takes priority.
* **Null clears:** if a tag value becomes `null` (failed read), any active alarm
  for that tag is cleared.
* **Severity escalation/de-escalation:** if a value moves from the warning range
  into the critical range, the alarm's severity updates in place. The reverse is
  also true.
* **QML API:**
  * `Bus.alarmCount` — number of active alarms (Property, int).
  * `Bus.activeAlarms` — list of active alarm objects (Property, QVariantList),
    each containing `{tag, label, severity, value, message, timestamp, acknowledged}`.
    Sorted: critical first, then warning. Within each severity: newest first.
  * `Bus.acknowledge(tag)` — marks an alarm as acknowledged. Re-activation
    creates a new, unacknowledged entry.
  * `Bus.activeAlarmsChanged` — emitted whenever the alarm list changes.

### 9.4 Single emission per burst

`Bus.activeAlarmsChanged` is emitted after alarm evaluation, not on every
individual value update. This prevents QML alarm bindings from re-evaluating
10 times a second unnecessarily.

## 10. Repository layout

| Component | Path |
| --- | --- |
| Hardware daemon | `daemon/` |
| Panel runtime (C + LVGL) | `native/hmi-ui/` |
| Legacy Qt loaders | `gui/`, `native/hmi-gui/`, `apps/demo-app/` |
| Target units and installer | `target/` |
| Deploy CLI | `deploy/` |
| Studio (deployer GUI) | `tools/hmi_deployer/` |
| Visual Designer | `designer/` |
| Bundle schema | `schema/` |
| Yocto layer | `yocto/` |
| Design system | `ui/` |

## 11. Host deployer GUI look & feel

The tool's centrepiece is a **centred hardware mock-up of the panel** — the
deployment target rendered as the physical device, with the customer's Qt app
drawn inside it exactly as it appears on the HMI.

* Canvas: the shadcn `muted` token (`#f1f5f9` light / `#1e293b` dark) — see §11;
  everything else is chrome around it.
* Bezel: near-black (`#050505`) rounded rectangle, corner radius ≈ 28 px, soft
  drop shadow, **centred** in the preview pane, aspect-preserving on resize.
* Screen inset: uniform bezel margin ≈ 9.5 % of bezel width; screen area is the
  target resolution from `manifest.json` (default 1280×800), idle colour
  `#2b2b2b`.
* A single small status LED (Ø ≈ 10 px) in the bezel's top-left corner:
  dim blue `#1a3d7c` = idle/disconnected, brighter blue = link up, amber =
  deploying, red = fault.
* Inside the screen: the **actual app QML**, rendered live at target resolution
  and scaled to fit, bound to the same Tag Engine — fed by real telemetry
  tunnelled from the device when connected, or a simulator when offline. This is
  a true WYSIWYG preview, not a screenshot mock.

---

## 12. Design system — shadcn/ui, ported to Qt (NORMATIVE)

**Every user-facing element** — the on-target HMI shell, the demo app, the
fallback screen and the host deployer tool — is built from a Qt port of
[shadcn/ui](https://github.com/shadcn-ui/ui). No ad-hoc colours, radii,
paddings or hand-rolled buttons anywhere. If a screen needs a widget the kit
does not have, add it *to the kit* in the shadcn idiom.

`ui/` holds the single source of truth:

```
ui/tokens.json                 both palettes + radii + spacing + type scale
ui/qml/Shadcn/qmldir           QML module "Shadcn" (import Shadcn 1.0)
ui/qml/Shadcn/Theme.qml        singleton: Theme.background, Theme.primary, ...
ui/qml/Shadcn/*.qml            the components below
ui/qss/shadcn_light.qss        Qt Widgets stylesheet (deployer chrome)
ui/qss/shadcn_dark.qss
ui/python/shadcn.py            loads tokens.json, renders the .qss, helpers
ui/README.md
```

The GUI loader adds `/usr/lib/hmi/qml` to the QML import path, so **BYOA apps
get the kit for free** with `import Shadcn 1.0`.

### 12.1 Tokens (shadcn default "slate" theme, verbatim)

| Token | Light | Dark |
| --- | --- | --- |
| `background` | `#ffffff` | `#020817` |
| `foreground` | `#020817` | `#f8fafc` |
| `card` / `popover` | `#ffffff` | `#020817` |
| `cardForeground` | `#020817` | `#f8fafc` |
| `primary` | `#0f172a` | `#f8fafc` |
| `primaryForeground` | `#f8fafc` | `#0f172a` |
| `secondary` / `muted` / `accent` | `#f1f5f9` | `#1e293b` |
| `secondaryForeground` / `accentForeground` | `#0f172a` | `#f8fafc` |
| `mutedForeground` | `#64748b` | `#94a3b8` |
| `destructive` | `#ef4444` | `#7f1d1d` |
| `destructiveForeground` | `#f8fafc` | `#f8fafc` |
| `border` / `input` | `#e2e8f0` | `#1e293b` |
| `ring` | `#020817` | `#cbd5e1` |

Semantic extras (an HMI needs states shadcn does not ship): `success #22c55e`,
`warning #f59e0b`, `info #3b82f6`, each with a `*Foreground` of `#f8fafc`.

**Radii** (`--radius: 0.5rem`): `sm 4`, `md 6`, `lg 8`, `xl 12`, `full 9999`.
**Spacing**: 4 px base scale (4/8/12/16/24/32/48).
**Type**: Inter, then Noto Sans, then DejaVu Sans (the reference image ships
DejaVu, so the fallback must be graceful). Sizes: `xs 12`, `sm 14`, `base 16`,
`lg 18`, `xl 20`, `2xl 24`, `3xl 30`. Weights 400/500/600. Headings use
`letterSpacing: -0.4` (tracking-tight).
**Shadows**: `sm 0 1px 2px rgba(0,0,0,.05)`, `md 0 4px 6px -1px rgba(0,0,0,.1)`,
`lg 0 10px 15px -3px rgba(0,0,0,.1)`.
**Motion**: 150 ms `Easing.OutQuad` colour transitions; the focus ring appears
without animation.

### 11.2 Component kit (geometry copied from shadcn, in px)

| Component | Spec |
| --- | --- |
| `ShButton` | h 36 (`sm` 32, `lg` 40, `icon` 36x36), radius md, px 16, text sm/500; variants `default` (primary bg), `secondary`, `destructive`, `outline` (1 px border, transparent bg, hover accent), `ghost` (hover accent), `link`; hover = 90 % opacity of bg; disabled = 50 % opacity; focus ring 2 px `ring` offset 2 px |
| `ShInput` | h 36, radius md, 1 px `input` border, transparent bg, px 12, text sm, placeholder `mutedForeground`, focus ring 1 px `ring` |
| `ShCard` + `ShCardHeader` / `ShCardTitle` / `ShCardDescription` / `ShCardContent` | radius xl, 1 px `border`, `card` bg, shadow sm; header padding 24, title text base/600 tracking-tight, description sm `mutedForeground`, content padding 24 with top 0 |
| `ShBadge` | h 20, radius full, px 10, text xs/600; variants `default`/`secondary`/`destructive`/`outline`/`success`/`warning` |
| `ShSwitch` | track 36x20 radius full (`primary` on, `input` off), thumb 16 px white, 150 ms slide |
| `ShProgress` | h 8, radius full, `secondary` track, `primary` indicator |
| `ShSeparator` | 1 px `border`, horizontal or vertical |
| `ShAlert` | radius lg, 1 px border, padding 16, title sm/500, description sm `mutedForeground`; `destructive` variant tints border and text |
| `ShTabs` | list h 36 radius lg `muted` bg padding 4; trigger radius md text sm/500, active = `background` bg + shadow sm |
| `ShLabel` | text sm/500, `foreground` |
| `ShSkeleton` | `muted` bg, radius md, 1.5 s pulse |
| `ShDialog` | overlay `rgba(0,0,0,.8)`, panel radius lg, `background` bg, 1 px border, padding 24, shadow lg |
| `ShGauge`, `ShStatDot`, `ShValueTile` | HMI additions in the same idiom, documented in `ui/README.md` |

Every component exposes `variant`, `size` (where applicable) and `enabled`, and
takes its colours **only** from `Theme`. `Theme.mode` (`"light"`/`"dark"`) is
switchable at runtime and every component must follow it live.

Defaults: the on-target HMI runs `Theme.mode = "dark"`; the host deployer runs
`"light"` with a toggle.

### 11.3 Icons — Tabler Icons (NORMATIVE)

All iconography comes from [Tabler Icons](https://github.com/tabler/tabler-icons)
(MIT). Nothing else: no emoji, no unicode glyphs standing in for icons, no
hand-drawn shapes.

* Style: the **outline** set — 24x24 viewBox, `stroke-width 2`, round caps and
  joins, no fill. Rendered at 16 px inside `sm` controls, 18 px inside default
  controls, 20-24 px standalone.
* Icons are **vendored, not fetched at runtime** (the target has no internet).
  The needed SVGs come from
  `https://unpkg.com/@tabler/icons@3.31.0/icons/outline/<name>.svg`, strips them
  to their path data, and embeds them in a registry keyed by Tabler name.
* Colour comes from `Theme` (stroke follows the surrounding text colour), so an
  icon recolours with the theme automatically. Never bake a colour into the SVG.
* API: `ShIcon { name: "upload"; size: 18; color: Theme.foreground }` in QML,
  and `shadcn.icon("upload", size=18, color=...)` returning a `QIcon`/`QPixmap`
  for Qt Widgets. An unknown name renders a visible placeholder box and logs a
  warning — it must never throw.
* `ui/icons/LICENSE.tabler` carries the upstream MIT notice and attribution.

Minimum icon set to vendor (add more as needed, same names as upstream):
`upload`, `download`, `plug`, `plug-connected`, `plug-off`, `refresh`,
`rotate-clockwise`, `device-desktop`, `device-imac`, `cpu`, `server`,
`terminal-2`, `file-code`, `folder-open`, `folder-plus`, `trash`, `settings`,
`adjustments`, `sun`, `moon`, `alert-triangle`, `circle-check`, `circle-x`,
`info-circle`, `loader-2`, `player-play`, `player-stop`, `power`, `bolt`,
`activity`, `gauge`, `wifi`, `wifi-off`, `key`, `search`, `plus`, `x`,
`chevron-down`, `chevron-right`, `clipboard-text`, `history`.

---

## 13. Operator runtime v2 (NORMATIVE)

Everything here is **additive**: a design, manifest or frame that uses none of
it reads, validates and behaves exactly as before, and an older `hmi-ui`
ignores the new keys (its loader skips unknown keys). The Python model
(`designer/model/`) and the C runtime (`native/hmi-ui/src/`) implement the
same rules; where they could differ, this section decides.

### 13.1 Actions

`actions[<signal>]` is one action object **or a list** of them. A list runs
in order, as one unit.

| `kind` | Fields | Effect |
| --- | --- | --- |
| `write` | `tag`, `value`? | unchanged (`value` absent: the control's own state) |
| `pulse` | `tag`, `ms` 1..10000 | unchanged |
| `navigate` | `page` | show page `page`; the page left is pushed on the history |
| `back` | -- | show the most recent page on the history (depth 16, oldest dropped); nothing when empty |
| `toggle` | `tag` | write `!truthy(current)`; a tag never seen counts as `false` |
| `increment` / `decrement` | `tag`, `step` (default 1), `min`?, `max`? | write `current +/- step`, clamped to `[min, max]`; never seen = 0 |
| `ack` | `tag`? | acknowledge the alarm on `tag`, else the signal's argument; `"*"` = every active alarm |
| `shelve` | `tag`?, `ms` 1..86400000 (default 600000) | shelve that alarm (13.3) |

Every kind also takes `confirm` (string). When **any** action of a signal's
list has a non-empty `confirm`, the runtime shows one modal dialog with the
**first** such text and the buttons **Cancel** / **OK**; OK runs the whole
list, Cancel runs none of it. While a dialog (or any 13.5 popup) is open,
another confirmation is refused (logged); lists without `confirm` still run.

`truthy`: bool as is; number != 0; string not in `""`, `"false"`, `"0"`;
null false. Legacy: on `alarmActivated`, a `write` or `pulse` action still
means `ack` (designs saved before 13.1).

Python (`DesignerAction`): new fields `step: float = 1.0`, `min`/`max:
float | None = None`, `confirm: str = ""`, and `then: list[DesignerAction]`
holding actions 2..n of a list. `widget.actions[signal]` stays the first
action, so code that knows one action per signal keeps working. It serialises
as an object when `then` is empty, as a list otherwise; a new field at its
default is not written.

### 13.2 Bindings

New optional binding fields:

* `decimals` (int, default `-1` = automatic): when >= 0, a numeric reading
  that becomes text -- through a `format` `%1`, or into a str-typed property
  -- is written with exactly that many decimals (`"%.*f"`, 0..6).
* `expr` (string, default `""`): the reading is the expression's value
  instead of the tag's. `tag` may then be `""`; the binding depends on every
  tag the expression names. `multiplier`, `offset`, `format`, `decimals`,
  thresholds and rules apply to the result as to a tag reading. A non-numeric
  result passes through like a non-numeric tag value.
* `rules` (list, default `[]`): `{"if": "<op> <number>", "prop": <name>,
  "value": <JSON scalar>}`. Evaluated on the (scaled) reading each time it
  changes; per target property the **first** matching rule sets it; a
  property no rule matches gets the widget's declared value, else the kit
  default. A rule's `prop` must be a property of the widget type and must not
  itself be bound.

**Expression language** (identical in `expr.c` and `designer/model/expr.py`):

```
expr    := or ('?' expr ':' expr)?
or      := and ('||' and)*
and     := cmp ('&&' cmp)*
cmp     := sum (('=='|'!='|'<'|'<='|'>'|'>=') sum)?
sum     := prod (('+'|'-') prod)*
prod    := unary (('*'|'/'|'%') unary)*
unary   := ('!'|'-') unary | primary
primary := NUMBER | STRING | 'true' | 'false' | TAG
         | FUNC '(' expr (',' expr)* ')' | '(' expr ')'
FUNC    := abs/1 | floor/1 | ceil/1 | round/1-2 | min/2+ | max/2+ | clamp/3
NUMBER  := [0-9]+ ('.' [0-9]+)?
TAG     := [a-z][a-z0-9]*(\.[a-z0-9_]+)+      (CONTRACT 2.5)
STRING  := '"' ( any char but " and \ | '\"' | '\\' )* '"'
```

Values are null, bool, number or string. A tag never seen is null.
Arithmetic, unary minus and the functions on a null or string operand (bools
count as 1/0), division or `%` by zero, and a non-finite result are null.
Comparisons: two strings compare by value (`==`/`!=` only; `<` etc. on
strings are false); otherwise both sides as numbers; any null operand makes
the comparison false (`!=` too). `!`, `&&`, `||` and `?:` use `truthy`;
`!`, `&&`, `||` yield bools. `round(x)` rounds half away from zero; `round(x,
n)` to n decimals (n 0..6, else null). `clamp(x, lo, hi)`. A wrong function
name or arity, a bad token, and exceeding a limit are compile errors. Limits:
512 characters, 16 distinct tags, nesting depth 32 (parentheses, function
calls and unary operators, counted as they nest). A null result is treated
as a tag never seen (the binding's fallback value).

### 13.3 Alarms

Manifest `alarms[]` entries (CONTRACT 4) take new optional keys:

| Key | Rule | Meaning |
| --- | --- | --- |
| `priority` | int 1..4 | 1 = highest. Default: 1 while critical, 3 while warning |
| `latch` | bool | stays listed after the condition clears, until acknowledged |
| `delay_ms` | int 0..600000 | the condition must hold this long before the alarm raises |
| `deadband` | number >= 0 | an active alarm clears only when the value is `deadband` past the threshold (`> 80`, deadband 2: clears at `<= 78`) |
| `message` | string | replaces the generated `"<label> <value><unit>"` text |

Life cycle per tag: *normal* -> (condition held `delay_ms`) -> **active,
unacknowledged** -> ack -> **active, acknowledged** -> clears -> normal. With
`latch`, clearing while unacknowledged leaves **cleared, unacknowledged**
(still listed, `value` frozen) until an ack removes it. A null value clears
immediately (a latched unacknowledged alarm still stays listed). Shelving
removes an alarm from the active list and stops it raising until the shelve
expires; on expiry it is re-evaluated on the last value. A shelve on a tag
with no definition does nothing.

The active list (ShAlarmTable `alarms`) is ordered by priority (1 first),
then newest first. Each item is the list
`[tag, label, severity, value, message, timestamp, acknowledged, priority, state]`
-- the first seven unchanged -- with `state` `"active"` or `"cleared"`.

**Journal.** With `hmi-ui --journal PATH` every raise, clear, ack, shelve and
unshelve appends one JSON line
`{"ts": <epoch ms>, "event": "raise"|"clear"|"ack"|"shelve"|"unshelve",
"tag", "label", "severity", "priority", "value"}`, flushed at once and fsynced
at most once a second. When the file passes 1 MiB it is renamed `PATH.1`
(replacing that) and a new one starts. Without `--journal` nothing is written
(Studio renders never journal). `hmi-ui.service` passes
`--journal /var/lib/hmi/alarm-journal.jsonl`.

ShAlarmTable `mode`: `"active"` (default) shows the active list;
`"history"` shows the journal's newest `maxVisible` events, newest first, as
items `[tag, label, severity, value, event, timestamp, true, priority,
"cleared"]` (the message column carries the event name).

Python: `DesignerBinding.alarm` (dict, default `{}`) carries these keys for
the tag's entry; `DesignerProject.alarms()` merges them in.

### 13.4 History and tag quality (additions to section 2)

Command and reply:

```jsonc
{"id":"gui-9","cmd":"history","tag":"eng.egt","seconds":3600,"points":200}
{"t":"ack","id":"gui-9","ok":true,
 "history":{"tag":"eng.egt","samples":[[1790569717123, 612.5], ...]}}
```

`seconds` 1..604800 (default 3600), `points` 1..200 (default 200). Samples are
`[epoch ms, number]`, oldest first, at most `points`: when more were stored in
the period, it is split into `points` equal buckets and each non-empty
bucket's **last** sample is kept. Errors: `unknown_tag`, `bad_value`, and the
new code `no_history` (no historian, or it does not log that tag).

**Historian** (`daemon/historian.py`, run inside `hmi-hwd`), configured in
`hwd.json`:

```jsonc
"history": {
  "path": "/var/lib/hmi/history.db",     // SQLite
  "retention_days": 7,                    // 1..365
  "tags": {"eng.egt": {"period_ms": 1000, "deadband": 0.5}, "*": {"period_ms": 5000}}
}
```

A numeric tag is logged at most once per `period_ms` (100..3600000), and only
when it moved more than `deadband` (default 0) since its last logged sample,
or `60 * period_ms` passed since it. `"*"` applies to every numeric tag not
listed. Commits are batched (at most every 5 s, for flash wear); retention is
enforced at start and hourly. No `history` key: no historian, and `history`
answers `no_history`. A malformed `history` block is logged as an error at start and
the daemon runs without a historian (the I/O matters more than the log). `python3 historian.py export --db PATH --tag T
[--since SECONDS]` prints CSV `timestamp_iso,epoch_ms,tag,value` for the
Studio's `tools/hmi_deployer/history_export.py` (run over SSH).

**Quality.** A telemetry frame may carry `"q": {"<tag>": "bad"|"stale"}`
listing only tags that are not good (absent = all good). `bad`: the read
failed (the value is `null`, as before). `stale`: the value is the last good
one and older than 5 poll periods. `hmi-ui` keeps the latest quality of
every tag (`hmi_tags_quality`); a tag missing from `q` in a frame that
carries it is good again.

**Backfill.** When `hmi-ui` shows a page it sends `history` for every
scalar tag bound to an `ShTrendChart` `data` (points = the chart's
`maxPoints`, at most 200). Samples older than the oldest one held are put in
front of the tag's ring (never more than it holds), and the chart redraws.
`no_history` changes nothing.

### 13.5 Operator input and the screen

* **ShNumInput**: a tap on the value opens a numeric keypad on the top layer
  (`0`-`9`, `.`, `-`, backspace, `C`, **Cancel**, **OK**) holding the current
  value. OK with a value outside `[minValue, maxValue]` (or not a number)
  keeps the keypad open and shows `min..max` in the destructive colour;
  otherwise the value is rounded to `decimalPlaces`, shown, and
  `valueChanged(value)` is emitted. Not when `enabled` is false.
* **ShInput**: a tap opens an on-screen keyboard (text mode) with the text;
  OK sets `text` and emits the new signal `accepted(text)` (its state
  property is `text`). Not when `readOnly` or not `enabled`.
* One popup at a time: a keypad, keyboard or confirmation opening while
  another is open is refused.
* **Link lost**: when the daemon link goes offline, or has not come online
  5 s after start, a banner across the top of the screen reads
  `No connection to controller - values may be stale`; it goes when the link
  is back. Never shown without a daemon link (headless renders).
* **Idle**: `screen.idle` = `{"dimAfterS": N, "dimPercent": 10..100 (30),
  "offAfterS": N}` (0 or absent = never). After `dimAfterS` without a touch
  the backlight goes to `dimPercent`; after `offAfterS` it goes to 0 and a
  black overlay covers the screen. A touch restores full brightness; the
  touch that wakes an **off** screen does nothing else. Backlight: the first
  directory in `/sys/class/backlight/` (`HMI_BACKLIGHT_DIR` overrides), its
  `brightness` written as that share of `max_brightness`. No backlight: the
  overlay alone.

---

## 14. hmi-hwd in C, and the panel's peripherals (NORMATIVE, wave 5)

`native/hmi-hwd/` is the C port of `daemon/hmi_hwd.py`: same wire protocol
(section 2 and 13.4), same `hwd.json`, same CLI (`--config --sim --strict
--selftest --log-level`) plus `--modbus-live`. `daemon/hmi_hwd.py` stays the
reference; the acceptance tests run against either (`HMI_HWD_CMD`).

Additions, all in the C daemon (the Python daemon ignores sections it does
not know):

* **Test hook.** `HWD_SIM_FAIL="ai.pot,serial.scan.rx"` (environment) makes
  those tags' simulated reads fail: published `null` with quality `bad`.
* **Discovery.** UDP `0.0.0.0:47800` (`daemon.discovery`, default true;
  `daemon.discovery_port`). A datagram `{"cmd":"discover"}` is answered,
  unicast, with `{"t":"hello","host":H,"model":M,"hwd":"0.2.0","cmd_port":N,"tags":K}`
  (`model` from `/proc/device-tree/model`, "" when absent).
* **Stale.** A tag whose value has not been refreshed for 5 poll periods (or
  a CAN signal past its `timeout_ms`) is `"stale"` in `q`.
* **Extra commands** (acked like section 2.3):
  `{"cmd":"serial_tx","port":P,"data":S}`, `{"cmd":"can_tx","id":"0x123","data":"0102AABB","extended":false}`,
  `{"cmd":"usb_export","what":"history"|"logs"}` (ack carries `"file"`).

### 14.1 Serial ports (USB and native) -- `"serial"`

```jsonc
"serial": {"ports": {
  "scan": {"match": {"vid": "0403", "pid": "6001", "serial": "A10K1"},   // or "path": "/dev/ttyUSB0"
           "baudrate": 9600, "bytesize": 8, "parity": "N", "stopbits": 1,
           "eol": "\r\n", "max_line": 256}}}
```

Port names `[a-z0-9_]+`. `match` finds the device under
`/sys/bus/usb-serial/devices` / `/sys/class/tty/*/device` (vid, pid,
optional serial; `HWD_SYSFS_ROOT` overrides `/sys` for tests); `path` may be
any tty (`/dev/ttymxc1`, `/dev/serial/by-id/...`, a pty in tests). Tags:
`serial.<name>.present` (bool), `serial.<name>.rx` (string, the last
complete line without `eol`, null before the first), `serial.<name>.rx_count`
(int). Unplugged: present false, rx keeps its value, quality `stale`; the
port is re-opened within 1 s of coming back. `serial_tx` writes `data` as is.
Sim: present true; every 2 s a line `SIM <n>` is received.

### 14.2 Modbus RTU -- `"modbus_rtu"`

```jsonc
"modbus_rtu": {"path": "/dev/ttyUSB1", "baudrate": 19200, "parity": "E", "stopbits": 1,
               "unit_id": 1, "poll_interval_ms": 200, "timeout_s": 0.5, "reconnect_s": 2.0,
               "tags": {"mb.rtu.temp": {"unit": 3, "kind": "input", "address": 0, "type": "int16", "scale": 0.1}}}
```

`path` or `match` as in 14.1. Tags take the Modbus TCP keys (section 2.5) and
`unit` (default `unit_id`). `sys.modbus_rtu_online`. Frames are CRC-16/MODBUS;
a request waits `timeout_s` for the reply, and 3.5 character times separate
frames. Both Modbus links honour **`enum`** (holding/input integer tags): an
array of strings; the published value is `enum[raw]` when in range, else the
number; writing one of those strings writes its index.

### 14.3 CAN -- `"can"`

```jsonc
"can": {"interface": "can0",
        "signals": {
          "can.motor.rpm":    {"id": "0x123", "extended": false, "start_bit": 0, "length": 16,
                               "byte_order": "little", "signed": false, "scale": 0.25,
                               "offset": 0, "timeout_ms": 1000},
          "can.motor.enable": {"id": "0x200", "start_bit": 0, "length": 1, "writable": true,
                               "period_ms": 100}}}
```

SocketCAN (`PF_CAN`, raw). Bit numbering as in DBC files: `little`
(Intel) counts `start_bit` from the LSB of byte 0; `big` (Motorola) gives the
MSB's position in the DBC sawtooth numbering. A received frame updates every
signal with its id; a signal not seen for `timeout_ms` goes `stale`.
Writable signals share a transmit frame per id (8 bytes, unset bits 0):
writing a signal updates its bits and sends the frame, and repeats it every
`period_ms` when given. `can_tx` sends a raw frame. `sys.can_online` = the
interface is up. Sim: received signals ramp across their range; writes are
echoed back as received values. A virtual interface (one with no
`/sys/class/net/<if>/device`, e.g. `vcan0`) touches no hardware and is used
for real even under `--sim`.

### 14.4 HID input (barcode scanners) -- `"hid"`

```jsonc
"hid": {"devices": {"scanner": {"match": {"vid": "0c2e", "pid": "0b61", "name": "Barcode"},
                                "path": "/dev/input/event3", "grab": true, "eol": "enter"}}}
```

evdev (`/dev/input/event*`, matched by `/sys/class/input/event*/device`
id/vendor, id/product or name substring; `path` may be any file or FIFO of
`struct input_event` in tests). Key presses are decoded with a US layout
(shift handled) into text; `eol` (`enter` or `tab`) ends a scan. `grab`
takes the device exclusively (`EVIOCGRAB`) so its keys never reach hmi-ui.
Tags: `hid.<name>.present`, `hid.<name>.text` (last scan), `hid.<name>.count`.
Hotplug as in 14.1. Sim: a scan `SIM-000n` every 5 s.

### 14.5 USB storage and devices -- `"usb"`

```jsonc
"usb": {"storage": {"mount_root": "/media", "auto_mount": false, "export_dir": "hmi-export"},
        "devices": true}
```

Storage: the first mount point of a `/dev/sd*` block device under
`mount_root` (from `/proc/mounts`; `HWD_PROC_MOUNTS` overrides the path for
tests). With `auto_mount` the daemon mounts an unmounted `/dev/sd?1`
(vfat, exfat or ext4) at `<mount_root>/usb0` and unmounts it on removal.
Tags: `usb.storage.present`, `usb.storage.path` (string or null),
`usb.storage.free_mb`. `usb_export` copies the history database
(`what: history`) or the daemon's own log ring (`logs`, last 1000 lines) to
`<path>/<export_dir>/<what>-<UTC stamp>.<db|txt>` and answers `"file"`;
`hw_error` when no storage. `devices`: `usb.devices` (int) = USB devices
attached (`/sys/bus/usb/devices/*` with an `idVendor`). Sim: storage present
at a temporary directory; `usb.devices` 2.

### 14.6 I2C and SPI sensors -- `"i2c"`, `"spi"`

```jsonc
"i2c": {"sensors": {
  "i2c.cab.temp":   {"bus": 1, "address": "0x48", "device": "tmp102"},
  "i2c.cab.rh":     {"bus": 1, "address": "0x44", "device": "sht3x", "measure": "humidity"},
  "i2c.io.inputs":  {"bus": 1, "address": "0x20", "register": "0x09", "type": "uint8", "period_ms": 100},
  "i2c.io.outputs": {"bus": 1, "address": "0x20", "register": "0x0A", "type": "uint8", "writable": true}}},
"spi": {"sensors": {
  "spi.adc.ch0": {"bus": 1, "cs": 0, "mode": 0, "speed_hz": 1000000, "tx": "01 80 00",
                  "rx_offset": 1, "length": 2, "byte_order": "big", "mask": "0x03FF",
                  "type": "uint16", "scale": 0.00322, "period_ms": 100}}}
```

I2C through `/dev/i2c-<bus>` (`I2C_RDWR`), SPI through
`/dev/spidev<bus>.<cs>` (`SPI_IOC_MESSAGE`). Generic reads: `register`
(1 byte, optional), `type` uint8/int8/uint16/int16/uint32/int32/float32,
`byte_order`, optional `mask` and `shift` (right shift after masking), then
`scale` (default 1) and `offset` (default 0); `period_ms` default 1000,
100..3600000. Presets (`device`): `tmp102`, `lm75` (temperature °C),
`sht3x` (`measure` temperature °C or humidity %RH, single-shot high
repeatability), `ina219` (`measure` bus_voltage V or current A with
`shunt_ohm`, default 0.1), `ads1115` (`channel` 0..3, single-ended, volts,
±4.096 V range). A writable generic I2C tag writes its register.
Reads run in the backend's thread; a failed transaction is `null`/`bad`.
Sim: presets give plausible values (22-26 °C, 40-50 %RH, 23.8-24.2 V,
0.4-0.6 A, ramping), generic tags ramp across their type's range.
