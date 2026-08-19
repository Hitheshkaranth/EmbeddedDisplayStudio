# BYOA HMI — Binding Interface Contract (v1)

**Status: NORMATIVE.** Every component in this repository is written against this
document. Swarm workers MUST NOT invent alternative names, ports, paths or JSON
shapes. If something here looks wrong, implement it anyway and note the concern
in your component README — the architect reconciles.

Target: Toradex Verdin **i.MX8M Plus**, **native Toradex Yocto Reference
Multimedia Image** (Wayland/Weston), systemd. **No Docker, no TorizonOS, no
containers.** Everything runs on the rootfs as systemd units.

---

## 1. Three decoupled layers

```
 ┌────────────────────────────┐   UDP/JSON 127.0.0.1   ┌────────────────────────┐
 │ hmi-hwd (Layer 1)          │  :5000  commands  ◄────│ hmi-gui  (Layer 2)     │
 │ GPIO / IIO-ADC / UART      │  :5001  telemetry ────►│ Loader + Tag Engine    │
 │ ONLY process touching HW   │                        │ ZERO driver code       │
 └────────────────────────────┘                        └──────────┬─────────────┘
                                                                  │ loads
                                             /opt/hmi_apps/current/main.qml
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
`rate_limited`.

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
| `uart.` | serial link tags | `uart.tx` only |
| `sys.` | daemon health/diagnostics | no |

**QML alias:** dots are illegal in QML property names, so the Tag Engine also
exposes each tag with `.` replaced by `_` (`ai.pot` → `Tags.ai_pot`). Commands
always use the raw dotted name.

---

## 3. Filesystem layout on target

| Path | Owner | Purpose |
| --- | --- | --- |
| `/usr/lib/hmi/hmi_hwd.py` | root:root 0755 | hardware daemon |
| `/usr/lib/hmi/gui/` | root:root 0755 | GUI loader + shell QML |
| `/usr/lib/hmi/qml/Shadcn/` | root:root 0755 | shared shadcn QML component kit |
| `/usr/bin/hmi-install` | root:root 0755 | target-side atomic installer |
| `/usr/bin/hmi-gui-launch` | root:root 0755 | Wayland env resolver + exec |
| `/etc/hmi/hwd.json` | root:root 0644 | daemon config (tag → pin map) |
| `/etc/default/hmi-gui` | root:root 0644 | GUI env overrides |
| `/opt/hmi_apps/releases/<id>/` | root:root 0755 | unpacked app releases |
| `/opt/hmi_apps/current` | symlink | → `releases/<id>`, atomically swapped |
| `/tmp/hmi_upload/` | root:root 0700 | **tmpfs** SCP landing zone |
| `/run/hmi/gui-ready` | root:root | touched by GUI after successful QML load |
| `/run/hmi/install.lock` | root:root | `flock` for serialised installs |

Release id: `<name>-<UTC yyyymmddTHHMMSSZ>`. Keep the **3** newest releases plus
whatever `current` and `previous` point at; prune the rest.

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
  "screen": {"width": 1280, "height": 800},
  "tags_required": ["ai.pot", "di.estop", "do.relay1"],
  "qt": ">=6.5"
}
```

Validation is performed **twice**: host-side before upload, target-side before
the swap. A bundle that fails validation must never reach `current`.

## 5. systemd units

| Unit | Type | Ordering |
| --- | --- | --- |
| `hmi-hwd.service` | `notify` (sd_notify `READY=1`, `WATCHDOG=1`) | `Before=hmi-gui.service`, `WantedBy=multi-user.target` |
| `hmi-gui.service` | `simple` | `After=weston.service hmi-hwd.service`, `Requires=weston.service`, `WantedBy=multi-user.target` |

Both `Restart=always`, `RestartSec=2`. The GUI must survive the daemon being
absent (shows "link lost", keeps rendering).

## 6. Deployment sequence (Layer 3, atomic)

1. Host validates the bundle, tars + `sha256sum`s it.
2. `scp` bundle + `.sha256` → `/tmp/hmi_upload/` (tmpfs — a failed upload never
   touches flash).
3. `ssh <target> hmi-install /tmp/hmi_upload/<file>.tar.gz`.
4. Target: `flock` → verify sha256 → extract to `releases/.stage.$$` → validate
   manifest → `rename()` stage → `releases/<id>`.
5. Atomic swap: create `.current.new` symlink → `os.replace()` onto `current`
   (`rename(2)`; **do not** `rm` then `ln` — that leaves a window with no UI).
6. `rm -f /run/hmi/gui-ready`; `systemctl restart hmi-gui.service`; wait ≤ 25 s
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

## 9. Repository layout & swarm ownership

Each worker owns **only** its listed paths. Do not create, edit or delete files
outside your scope — the architect owns integration.

| Worker | Scope |
| --- | --- |
| W1 daemon | `daemon/` |
| W2 gui | `gui/`, `apps/demo-app/` |
| W3 target | `target/` |
| W4 deploy-cli | `deploy/` |
| W5 deployer-gui | `tools/hmi_deployer/` |
| W6 yocto | `yocto/` |
| W7 design system | `ui/` |
| architect | `README.md`, `docs/` |

Wave 1 (parallel): W1, W3, W4, W6, W7. Wave 2 (parallel, consumes `ui/`):
W2, W5.

## 10. Host deployer GUI look & feel (W5)

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

## 11. Design system — shadcn/ui, ported to Qt (NORMATIVE)

**Every user-facing element** — the on-target HMI shell, the demo app, the
fallback screen and the host deployer tool — is built from a Qt port of
[shadcn/ui](https://github.com/shadcn-ui/ui). No ad-hoc colours, radii,
paddings or hand-rolled buttons anywhere. If a screen needs a widget the kit
does not have, add it *to the kit* in the shadcn idiom.

W7 owns `ui/` and produces the single source of truth:

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

### 11.1 Tokens (shadcn default "slate" theme, verbatim)

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
  W7 downloads the needed SVGs from
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
