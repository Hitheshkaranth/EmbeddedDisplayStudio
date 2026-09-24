# Changelog

## 0.1.1

**Qt applications on a Qt-free panel**

* Deploying a `runtime: python` bundle (PySide2 or PySide6) to a panel that
  runs `hmi-ui` now brings the Qt runtime along, after one confirmation: the
  Qt app launcher, `hmi-gui.service`, a Weston drop-in, and the PySide2
  runtime (`/opt/hmi-python-qt5`) or PySide6 (into `/opt/hmi-python`). The
  PySide2 runtime is assembled on the Studio's own PC from Debian packages --
  no WSL, no `dpkg-deb` -- and cached. The panel needs no internet.
* The application's own packages (pyserial, ...) are fetched as wheels on the
  PC and installed on the panel with `pip --no-index`.
* `hmi-install` starts the service that matches the bundle: `hmi-ui` for a
  Studio design, `hmi-gui` (under Weston) for a Qt application. Boot default,
  rollback and activate follow it, so deploying a Studio design hands the
  display back to `hmi-ui`. Exit 5 when the bundle's service is not
  installed; nothing is changed.
* Weston no longer segfaults at start when `/tmp/.X11-unix` has been cleaned
  away on a long-up panel.

**AI Design**

* Designs that do not fit the screen are split into pages: the instruments,
  alerts and controls that matter most stay on an overview, the rest go to a
  page per engine or system, linked both ways. A page that still overlaps
  after layout moves its least important widget on. The prompt gives the
  model a per-page budget for the actual screen, and a brief that names a
  different resolution from the panel's is reported.
* A **twin** composition for a pair of instruments (two engines, two
  channels), chosen for a page with two dials of one kind or a brief that
  says dual/twin.
* Gauge scales are repaired from what a widget carries: a range too short
  for its own thresholds or value is widened, a 0..1 "fraction" scale with a
  real readout becomes the real scale, a fixed readout that hid the live
  value is cleared, and a pair of instruments shares one scale.
* Sectioned runs are laid out as one page after every section, instead of
  stacking each section's hero in the same slot.
* Model output is made deployable: tags lowercased, actions on signals a
  widget cannot emit and links to pages that do not exist dropped, reused
  widget ids renamed. The Designer applies the same repairs when it opens a
  design saved before.
* The vLLM preset follows the lab server to `:8080` and `qwen3.8-35b-a3b`,
  with an API key; a 401/403 reads "API key required/rejected", not
  "unreachable", and a saved model the server no longer serves is replaced.

**Studio**

* The **Code** workspace is a project editor: the bundle's files and
  folders, a Widgets list with live thumbnails, tabbed editors with undo /
  redo / save, the design pinned first, and an [opencode](https://opencode.ai)
  coding agent that works in the project folder on the configured model.
* A new look, from [Libraries.dev](https://github.com/Jakubantalik/Libraries.dev)
  ported to QPainter: liquid navigation, border beams on work in progress,
  thinking orbs, a bot avatar for the agent, a liquid-metal mark and a
  pixel-mosaic preview loader -- with an **Animations** switch in the header.
* **Mirror the panel** in the Display Console: the panel's own screen at a
  frame a second.
* Live Preview says why a design did not load (the QML error, in the window
  and the console) instead of showing an empty window, and a binding on a
  property a widget does not have no longer breaks the generated file.
* The packaged Studio carries every PySide6 module except WebEngine/WebView,
  and its built-in pip works -- a previewed application that loads a `.ui`
  file, or needs a package installed, now runs.
* Closing the Studio during a package install no longer crashes it.

**Panel runtime**

* `hmi-tagsim`: a bench feed that reads the deployed design and fills every
  tag it binds from one flight, each quantity mapped onto the scale of the
  widget that draws it.
* `hmi-ui` honours the Designer's `z`, builds on LVGL 9.3 with gcc 14, and
  four kit widgets are back to their spec away from the defaults
  (`ShAttitude`, `ShTape`, `ShVSI`, `ShGauge`); `ShTurnCoordinator`'s
  aeroplane sits on its own arc again.

**Earlier in this cycle**

* AI Design: the reasoning pass is off by default -- a thinking model spent
  the whole output budget on it and could return no design at all.
* The packaged Studio ships `designer/templates`, and uncaught exceptions
  reach `studio.log`.
* The Designer's property panel no longer deletes an editor inside its own
  signal, which crashed the Studio when a font size was typed.

## 0.1.0

* The panel is Qt-free: `hmi-ui` (C11 + LVGL, DRM/KMS) is the platform GUI,
  interpreting the design file directly with all 46 widget types, icons,
  touch and the alarm engine. Bundles carry `runtime: edsui` and no
  generated code; provisioning installs `hmi-ui`, converts a Qt panel in
  place and can ship the interpreter (`--python`); the Yocto layer has no
  Qt dependency.
* The Studio previews with `hmi-ui` itself: the Designer canvas, the bezel
  and the Code section are rendered by the panel's own renderer (a
  headless Windows build travels inside the exe).
* The Code section: the `.edsui` design of the selected widget or the whole
  screen, following the selection, with a preview; editable and applied back
  as one undo step.
* `hmi-ui` hardening from review: bounded binding format text, bounded UDP
  drain per poll.

## 0.0.9

* `sim.car.*` drive cycle and the `automotive_cluster_demo` preset: a cluster
  that drives itself on the canvas, in the Live Preview window and on the
  panel.
* Deploy keys: Export verifies the key against the panel and packs the one it
  accepts; the bundle carries the panel's host key; Import installs it,
  verifies the link and explains any failure. Connect offers to forget a
  stale host key.
* Size-like properties have floors: a cleared or negative font size, dot size
  or segment count can no longer blank every widget on the page.
* The gear indicator ignores a numeric gear from a simulator.

## 0.0.8

* Automotive widget set: `ShClusterGauge`, `ShGearIndicator`, `ShAutoLevel`,
  `ShAutoReadout`, `ShDriveMode`, `ShTelltale`, `ShIconTile`, `ShTripInfo`,
  `ShSegmentBar`, `ShVehicleStatus`; 47 Tabler cluster icons vendored.
* Design presets: a brief that reads like a cluster or an EV dashboard gets a
  style guide and a hand-built exemplar in the AI prompt.
* Live Preview window: the design in its own window at the panel's
  resolution on the Studio's tag engine, so controls can be operated.
* Resize from any of the eight handles; **Disconnect** beside Connect;
  **Export / Import key** (`.hmikey`).
* The generator never emits a property or enum a widget does not declare;
  a bound text property falls back to `""`, not `0`.
* Panel: the provisioner ships `modbus.py`; 32-bit Modbus tags read both
  registers.

## 0.0.7

* AI Design -> Designer -> Preview no longer requires an open bundle; the
  Designer provisions one and the Studio adopts it.
* AI project titles are coerced to valid manifest names.
* Sectioned generation: designs are requested in sections of at most eight
  widgets, merged by widget id, and continued automatically until complete.

## 0.0.6

* AI Design tab: Ollama, OpenAI, Anthropic, Google, vLLM and BYOK; streaming
  reasoning, response and usage; canvas diff and multi-turn context.
* The Designer restyled: flat panels, icon-only tools, searchable library
  with favorites, layer tree, paired inspector cells.
* `TagEngine` gained `list_tags` and `unsubscribe` QML slots.
