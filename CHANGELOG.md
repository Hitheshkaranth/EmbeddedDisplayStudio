# Changelog

## Unreleased

**AI Design follows a reference picture**

* Attach a picture to a brief: paste it, drop it on the composer, or use
  the paperclip (up to four). Each request of the run sends it in the
  provider's own image format.
* With a picture, the plan prompt asks the model to reproduce it:
  * every block of the picture, region by region;
  * each block as a section with a `region` (top strip, left rail, left,
    center, right column, bottom row) and the picture's colours;
  * the closest kit widget for each, from a mapping table (gear selector,
    compass and attitude, tyre diagram, vitals bars, arcs, a picture slot).
* The **reference layout** lays such a plan out the way the picture is:
  * a status strip with the clock centred and big;
  * a gear rail at the left edge;
  * frameless dials and a hero picture in the body, a bottom row;
  * a column of cards on the right.

  The regions are kept on the widgets, so Tidy up rebuilds the same screen.
* Widgets for a vehicle cockpit:
  * `ShGearIndicator` `orientation: vertical`;
  * `ShVehicleStatus` `axles: 3` (six tyres);
  * `ShClusterGauge` `accentColor`;
  * `ShEngineBar` `orientation: horizontal` with `barColor`;
  * `ShSegmentBar` `barColor`.

  Status-strip icons: signal bars, map pin, cloud, user, truck.
* **`ShAnimatedImage`**: an animated GIF on the canvas, in the preview and
  on the panel (LVGL's GIF decoder), with `playing`, `speed` and
  `fillMode`. A dropped .gif becomes one.
* Fixes found on the way:
  * an Image with no picture is a framed placeholder on the panel;
  * a value tile elides its title instead of clipping it under its badge;
  * ShAttitude's ladder moves in QML and stays inside its box on the panel;
  * a speed arc alone no longer makes tagsim treat a design as a train;
  * a sample that already carries its unit is not drawn with it twice.
* Ornith 1.5 is a built-in AI Design provider. Saved connections are shared
  by AI Design and the Code agent ("Manage connections…"). No button is
  taller than Deploy.

**hmi-hwd in C** (`native/hmi-hwd`, CONTRACT §14)

* The panel's hardware daemon is now a C program with no Python underneath.
  It speaks the same §2 wire protocol (set, pulse, uart_tx, subscribe,
  list, ping, history), so the panel runtime, the Studio and tagsim do not
  change. `hmi-hwd-launch` starts `/usr/bin/hmi-hwd-native` when it is
  there. `HMI_HWD_PYTHON_ONLY=1` falls back to `hmi_hwd.py`, and
  `HMI_HWD_ARGS` now reaches both.
* Sources, one backend per `hwd.json` section:
  * GPIO (character device v2, then v1), ADC (IIO), UART and raw serial
    ports (a lost port is reopened within a second of replugging);
  * Modbus TCP and RTU, where `enum` gives a register named states and
    `--modbus-live` polls a real PLC under `--sim`;
  * CAN over SocketCAN with DBC-style signals, periodic transmit and
    `can_tx`; a virtual CAN interface is real even under `--sim`;
  * USB HID (keyboards, scanners) and USB device hot-plug with
    `usb_export`;
  * I2C/SPI sensors with built-in decoders;
  * the SQLite historian.
* Panels answer `{"cmd":"discover"}` on UDP 47800 with a hello, and
  `--selftest` prints one frame without taking the command port, so it
  runs beside a live daemon.
* `daemon/plc_sim.py` is a stdlib Modbus TCP slave that serves a
  `hwd.json`'s registers for bench tests. A CI job builds the daemon, runs
  its ctest suite and exercises CAN on vcan.
* `deploy/provision_panel.py` ships the aarch64 build. `--timesync` sets
  up the panel's clock.

**Connections, the Code agent and Modbus**

* **Manage connections**: one list of model endpoints (vLLM, OpenAI,
  Ollama, Anthropic, Google, any OpenAI-compatible) shared by AI Design's
  provider picker and the Code agent. A connection can be tested,
  fetches its models, and is marked "Use for Design" or "Use for Agent".
  The agent's pick is written into opencode's config.
* The Code agent shows how long a reply has run ("done in 5m 14s"), and
  reads under `daemon/` without asking.
* **Generate Modbus map** (Backend tab, or `designer/ide/modbus_map.py
  --write` from a project folder) gives every bound value a register:
  * numbers become float32;
  * names become enum registers over the line's stations, in route order;
  * flags become discrete inputs, and written values become coils or
    holding registers.

  It rebinds the design to the `mb.` tags and writes `hwd.json`. **Test
  against PLC** runs the daemon over that map against `plc_sim.py`. The
  Python daemon learned `enum` and `--modbus-live` too.

**Designer, simulation and the device**

* An image dropped from Explorer lands on the canvas. A project carries a
  brand (logo, accent), which the cab layout and the plan prompt use.
* A binding can name what tagsim plays on it (`sim`). tagsim reloads when
  the project file changes, and Tag Lab can simulate the open design.
* The panel mirror runs at a chosen rate.
* **Find panels** lists every panel on the network; the device chip
  turns red when the link drops and recovers by itself; **Sync clock**
  sets the panel's clock and RTC from the PC.
* AI Design:
  * Plan requests carry a JSON schema.
  * A reply that loses most of the design is retried once, with a note.
  * Planned readings show one coherent moment of the bench journey.
  * Deploy readiness warns about readings left with no tag.

**AI Design builds cab displays**

* A brief about a train (metro, rail, tram, cab...) gets a cab-display guide
  in the plan prompt, and a plan that holds the Rail widgets is laid out by
  `designer/layout/cab.py` the way drivers read one: the line in its colour,
  the train's fields and a clock across the top; speed and traction on the
  left; the station line and the NEXT card in the middle; the consist, up to
  three system status cards and a platform callout on the right. It scales
  to the screen and recompiles to the same page.
* The compiler puts right what models get wrong on these screens: a car
  count instead of car names, a progress in percent, a whole line of
  stations (a window round the next station is kept), a "current station"
  tile beside the station line, a doors status card instead of the consist,
  long system names (`PEA (Emergency Alarm)`), an unbound clock. What is
  always live on a cab -- speed, target, traction, station line, next
  station, ETA, distance, doors, clock -- is bound even when the plan left
  it static.
* A logo dropped into the header in the Designer is placed by **Tidy up**:
  on a white plate at the end it was dropped at, with the title and clock
  moved aside.
* Lenient JSON intake drops a closer that does not match what is open
  (`}}}}]}` where `}}}]}` closes a widget), so every later section survives.

**tagsim drives a train**

* A design with Rail widgets gets one journey instead of the flight: the
  train pulls away, cruises, brakes into the next station and stands at the
  platform with its doors open, over the stations its own station line
  names. Speed, target, traction, distance to go, ETA, next station, the
  station line, the hop progress, the doors and the cab clock all agree.
* `--start` begins part-way through the journey; `--clock-offset` corrects
  the clock a bench panel shows; on the panel both go in
  `/etc/default/hmi-tagsim` (`TAGSIM_EXTRA_ARGS`).

## 0.1.3

**Studio 2: four modes instead of seven tabs**

* One header row: the project menu (New app..., Open bundle...), a mode
  switch -- **Design**, **Simulate**, **Code**, **Deploy** -- with a view
  switch where a mode has more than one view (Design: Designer and AI
  Design), and a **device chip** whose popover holds the panel address,
  port, Connect and Disconnect. A status bar under the window reads the
  link, the open app and the display.
* **Design**: one toolbar with a File menu; Layers / Widgets / Pages on the
  left; Design / Data / Actions on the right, with **Size on screen**
  (Compact / Normal / Large) for the selected widget; an **AI composer**
  over the canvas replaces Design Chat -- add / set / bind / remove still
  run offline, anything else goes to AI Design with the current design as
  context and lands back on the canvas.
* **Simulate**: Tag Lab beside the panel, with a drawer for its command
  log and the panel's journal (formerly Panel Logs).
* **Deploy**: Display Console and System Profile in one view -- the release
  card (Deploy, Live preview, Mirror, Restart GUI, Rollback), the four
  deploy steps (Validate, Package, Transfer, Activate) moving with the
  progress bar, a readiness checklist, installed releases, the device and
  its health. Health is only measured while a panel is connected.
* **Code**: restyled to match; Outline and Backend unchanged.

**AI Design: the model plans, a compiler lays out**

* The model no longer writes geometry. It returns a title, header items and
  titled sections with roles; `designer/layout/compiler.py` lays them out
  deterministically (header, region search with a cost model, per-kind
  bands, theme tokens) and shrinks widgets below their design size when a
  screen is crowded. Runner-up layouts wait in the variant strip.
  `ai/layoutEngine=polish` restores the old path. See
  [docs/AI_LAYOUT_COMPILER.md](docs/AI_LAYOUT_COMPILER.md).
* `designer/layout/intake.py` repairs the JSON a model actually emits
  (duplicate keys, trailing text) and maps property names, icons and
  invented widget types onto the kit.
* Per-widget size wishes -- from the plan or from **Size on screen** -- and
  **Tidy up** on a compiled page compiles it again.
* A finished turn is no longer shown as "Cancelled" when the panel
  preview's nested event loop delivers the worker's finished signal.

**Designer**

* Object snap: dragging snaps to sibling and parent edges (toggle in the
  canvas bar, Ctrl bypasses).
* Align, match size and distribute act only on selected free siblings,
  never across parents or inside a positioner.

**Kit (hmi-ui and the QML kit alike)**

* ShClusterGauge fits its caption between the scale numbers and keeps the
  step's decimals; ShGearIndicator scales a row wider than its box;
  ShAutoReadout gives a wide value the icon's slot before shrinking;
  ShEngineBar holds its label to the bar; ShTrendChart draws its warning
  band and axis labels; ShValueTile reads `title` on the panel.

**CI**

* The Qt SVG image plugin comes from `libqt6svg6` on Ubuntu 24.04, where
  `qt6-svg-plugins` no longer exists.

**The panel, for an operator** (CONTRACT section 13; everything is additive --
designs and bundles that use none of it are unchanged)

* **Actions**: a signal can run a list of actions; new kinds `toggle`,
  `increment` / `decrement` (step, min, max), `back` (page history), `ack`
  (one alarm or `*`) and `shelve`; any list can ask **Cancel / OK** first.
* **Bindings**: an expression instead of a tag (`eng1.egt > eng2.egt ? "ENG 1"
  : "ENG 2"`, `round(fuel.l + fuel.r, 1)`, ...), fixed decimals, and rules that
  set another property from the reading (a title turns "HOT" above 80). The
  Designer checks expressions as you type.
* **Alarms**: priorities 1-4, latching until acknowledged, on-delay, deadband,
  custom message, shelving; a journal on the panel
  (`/var/lib/hmi/alarm-journal.jsonl`) and an alarm table `history` mode.
* **History**: `hmi-hwd` keeps a SQLite history of the tags `hwd.json` lists;
  trend charts fill from it when a page opens; per-tag quality (`bad`) in every
  frame; `python -m tools.hmi_deployer.history_export` pulls a CSV over SSH.
* **Operator input**: a numeric keypad (range-checked) for numeric inputs, an
  on-screen keyboard for text inputs, a "No connection to controller" banner,
  and screen dim / off after inactivity (Designer: **Screen idle**).

**Fixes**

* The panel never showed a bound Value Tile / Status Dot / Data Field /
  Annunciator value -- only a state colour, even without thresholds.
* Numeric inputs on the panel showed "Text" where their unit belongs.
* The offline tag simulator no longer fights a local daemon or tagsim for the
  Live Preview's values.

## 0.1.2

**Code: the design's widgets and its backend, side by side**

* **Outline** -- every widget of every page as one tree, with its tags and
  binding issues; filter to bound widgets, to issues or to one tag; a click
  selects the widget (switching page), a double-click opens its line in
  `project.edsui`.
* **Backend** -- one row per tag: read/write access, the widgets that use it,
  its live value and status (`ok`, `unused`, `not declared`). Values come
  from the Studio's tag engine while a panel is connected, else from a
  simulator scaled to each widget's range; double-click a writable tag to
  write it.
* **Generate backend...** writes `backend/` into the project: a runnable
  CONTRACT 2 UDP backend with one read/write stub per tag, `tags.json` and
  `tags.h`.
* The coding agent is told about the design -- pages, the selected widget,
  its bindable properties, tags and issues -- with one-click quick actions.

**Panel runtime (`hmi-ui`)**

* A trend chart bound to an ordinary numeric tag draws that tag's recent
  samples; it used to stay empty unless the tag itself carried a list.
* ShToggle flips on a tap and draws `checked` on the right side; alarm tags
  of 64 bytes or more fire; ShTrendChart draws the reference gradient in
  O(width); ShClusterGauge no longer freezes on a tiny `majorStep`.

**Designer**

* Adding, duplicating and deleting pages, and arrow-key nudges, are undo
  steps (a run of nudges is one); a multi-widget paste is one step. Before,
  a later undo could replay geometry the design no longer had.
* Arrange is 9x faster on busy pages; text alignment applies to every
  selected text widget; image widgets are no longer decoded on every paint.

**Daemon and deployment**

* Commands with `NaN`/`Infinity` are rejected; subscribe TTL is capped at
  60 s; a dead Modbus server is retried every `reconnect_s`, not at the poll
  rate.
* An upload the panel aborted reports the panel's own error; following panel
  logs no longer repaints the whole view per line.
* The Yocto layer installs `hwd.json` 0640.

**CI** is green again: the Linux job builds `hmi-ui` and runs its C tests and
the conformance and parity suites against it; the shell and native-loader
jobs find their scripts.

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
