# EmbeddedDisplay — Full Codebase Analysis & Improvement Report

> **Project**: EmbeddedDisplay Studio (MIL-HMI-PROJ/EmbeddedDisplay)
> **Stack**: Python 3.12, PySide6 6.8.1, Qt 6.8 QML
> **Scope**: 60+ Python source files, 40+ QML components, ~10 000+ lines of code
> **Date**: 2026-09-16

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File-by-File Analysis](#2-file-by-file-analysis)
   - [2.1 Root](#21-root)
   - [2.2 `daemon/` — Hardware Abstraction Daemon](#22-daemon--hardware-abstraction-daemon)
   - [2.3 `designer/` — Visual UI Designer](#23-designer--visual-ui-designer)
   - [2.4 `tools/hmi_deployer/` — Deployment Studio](#24-toolsuhmi_deployer--deployment-studio)
   - [2.5 `gui/hmi_loader/` — Runtime HMI Loader](#25-guihmi_loader--runtime-hmi-loader)
   - [2.6 `schema/` — Bundle Schema & Validation](#26-schemabundle-schema--validation)
   - [2.7 `ui/` — Shadcn QML Component Kit](#27-uisaadcn-qml-component-kit)
   - [2.8 `deploy/` — Provisioning](#28-deploy--provisioning)
   - [2.9 `tests/` — Test Suite](#29-testsu-test-suite)
3. [Code Quality Report](#3-code-quality-report)
   - [3.1 Critical Issues](#31-critical-issues)
   - [3.2 High-Priority Issues](#32-high-priority-issues)
   - [3.3 Medium-Priority Issues](#33-medium-priority-issues)
   - [3.4 Low-Priority / Nice-to-Have](#34-low-priority--nice-to-have)
4. [Cross-Cutting Concerns](#4-cross-cutting-concerns)
5. [Prioritized Improvement Plan](#5-prioritized-improvement-plan)
6. [Summary Matrix](#6-summary-matrix)

---

## 1. Architecture Overview

The project is a **three-layer HMI platform** for embedded Linux panels:

| Layer | Module | Purpose |
|-------|--------|---------|
| **1** | `daemon/hmi_hwd.py` + `daemon/modbus.py` | Hardware abstraction — GPIO, ADC, UART, Modbus TCP. Runs as systemd service. Pure-stdlib, `--sim` mode for dev. |
| **2** | `gui/hmi_loader/main.py` + `gui/hmi_loader/tagengine.py` | App loader — loads QML bundles, runs a UDP/JSON server bridging hardware tags to QML bindings. |
| **3** | `tools/hmi_deployer/` + `designer/` | Host-side Studio — visual designer, AI design, deployment over SSH with atomic install & rollback. |

**Data flow**: `hmi-hwd` (daemon on target) → UDP/JSON telemetry → `TagEngine` (on target) → QML `Bus.value("tag.name")` bindings → HMI app.

**Three ways to create screens**: AI Design, Visual Designer (canvas drag-and-drop), or Bring-Your-Own-App (BYOA). All paths produce a **bundle** (directory with `manifest.json` + entry QML) that is validated, packaged, and deployed over SSH.

---

## 2. File-by-File Analysis

### 2.1 Root

#### `main.py` (94 lines)
**What it does**: Single entry point that bootstraps the Studio, handles self-re-execution for sub-commands (preview shim, dependency scanning, pip installation), and manages CLI argument parsing.

| Function/Class | Lines | Purpose |
|----------------|-------|---------|
| `_flags()` | 31-40 | Lazily imports sub-command flag constants from deployer and native_preview |
| `_run_preview_shim()` | 43-50 | Hosts the customer's app in a child process, streaming frames back |
| `_run_deps_scan()` | 53-62 | Scans a bundle's imports using `ast.parse` in a child process |
| `_run_pip_install()` | 65-73 | Runs `pip install` in a child process for BYOA bundles |
| `main()` | 76-94 | CLI entry — dispatches on flags or launches `DesignerApplication` |

**Quality**: Clean design with self-re-execution trick for packaged builds. Main weaknesses are nested function definitions that are hard to test and missing type hints.

#### `requirements.txt` (19 lines)
**What it does**: Lists host-side Python dependencies (PySide6 6.8.1, pyserial 3.5). Comment explains why the daemon is stdlib-only and why PySide6 is pinned (geometry-sensitive QML rendering).

#### `run_tests.py` (empty)
**What it does**: Empty stub file. Provides no value.

---

### 2.2 `daemon/` — Hardware Abstraction Daemon

#### `daemon/modbus.py` (616 lines)
**What it does**: Pure-stdlib Modbus TCP client implementation with a built-in simulator. Implements MBAP header packing, function codes 1, 2, 3, 4, 5, 6, 16, type encoding/decoding with endianness support, and scaling to engineering units.

| Class/Function | Lines | Purpose |
|----------------|-------|---------|
| `ModbusError` | ~10 | Protocol-level exception with numeric code and human-readable label |
| `_build_header()` | ~60 | Packs MBAP header + unit ID + function code into raw bytes |
| `_parse_header()` | ~75 | Unpacks received MBAP header, validates protocol ID |
| `_TYPE_INFO` | ~90 | Maps type names to struct format strings and byte widths |
| `encode_value()` | ~110 | Packs integer to big-endian protocol bytes with range clamping |
| `decode_value()` | ~130 | Unpacks protocol bytes to integer, supports LE byte reversal |
| `scale_read()` | ~150 | `raw * scale + offset` to engineering units |
| `scale_write()` | ~160 | Inverse scaling with clamping |
| `ModbusTcpClient` | ~200 | Synchronous TCP client, thread-safe via Lock, implements FC 1/2/3/4/5/6/16 |
| `ModbusSim` | ~400 | In-memory simulator mirroring TcpClient's interface for tests |

**Quality issues**:
- Line 260: Bare `except Exception` in `_connect()` masks bugs
- Line 450: `NotImplementedError` stub for FC 22 left in production
- No reconnection logic — per-operation connect without backoff
- `_TYPE_INFO` has inconsistent handling for `"bool"` type

#### `daemon/hmi_hwd.py` (2 213 lines)
**What it does**: The Hardware Daemon — asyncio-based UDP/JSON server that reads GPIO (libgpiod v1/v2), IIO ADC (sysfs), UART (pyserial), and Modbus TCP, then broadcasts telemetry and accepts commands. Runs as systemd service with sd_notify watchdog.

| Class/Function | Lines | Purpose |
|----------------|-------|---------|
| `sd_notify()` | ~85 | AF_UNIX datagram to systemd notify socket (no libsystemd dependency) |
| `RateLimitedLogger` | ~110 | Prevents log flooding — one message per `LOG_RATE_LIMIT_S` per error class |
| `GpioBackend` (ABC) | ~130 | Abstract GPIO interface (setup_input, setup_output, write, read, release) |
| `GpioV1` | ~200 | libgpiod 1.x backend |
| `GpioV2` | ~280 | libgpiod 2.x backend |
| `GpioSim` | ~360 | Software GPIO simulation |
| `IioAdc` | ~400 | Reads IIO sysfs ADC channels with offset, scale, gain transforms |
| `IioSim` | ~560 | Simulated ADC (0-3.3 V ramp) |
| `UartLink` | ~580 | Background-thread UART reader via pyserial |
| `TagStore` | ~660 | Central typed value store (bool for di/do, float for ai, int/str for sys) |
| `load_config()` | ~1700 | Parses/validates `hwd.json` config |
| `SubscriberRegistry` | ~730 | Manages dynamic UDP subscribers with TTL expiry |
| `CommandProtocol` | ~800 | asyncio UDP datagram handler — dispatches set/pulse/uart_tx/subscribe/unsubscribe/list/ping |
| `HwDaemon` | ~900 | Main daemon: initializes backends, runs telemetry publisher, manages shutdown |
| `main()` | ~2050 | CLI entry point with `--config`, `--sim`, `--strict`, `--selftest`, `--log-level` |

**Quality issues**:
- Line 1601: `assert` used in production daemon — removed with `python -O`
- Line 1755-1836: Duplicate Modbus poll loop code (TcpClient vs Sim branches)
- Line 1209: Modbus write from asyncio callback blocks the event loop
- Line 755: UART reader thread silently swallows all exceptions — spin-loop on close
- Global mutable `_notify_sock` not thread-safe by design
- Line 2098: Cross-platform signal handling fragile

#### `daemon/hwd.json` (86 lines)
**What it does**: Runtime configuration — maps tag names to hardware pins, ADC channels, UART settings, and Modbus device parameters.

#### `daemon/README.md` (508 lines)
**What it does**: Comprehensive documentation — architecture, wire protocol, CLI, config schema, hardware discovery, self-test procedure, client example.

---

### 2.3 `designer/` — Visual UI Designer

#### `designer/__init__.py` (10 lines)
**What it does**: Package init exposing `run()` entry point that creates QApplication, sets fonts/stylesheet, instantiates `DesignerWorkspace`, and runs the event loop.

#### `designer/commands/commands.py` (~230 lines)
**What it does**: Undo/redo command stack supporting compound commands, property edits, widget insert/delete, and reordering. Per-project command history.

| Class | Lines | Purpose |
|-------|-------|---------|
| `Command` | ~13 | Base class with `do()`/`undo()`; thread-safety via `is_qt_thread()` guard |
| `BatchCommand` | ~65 | Groups multiple commands into one undoable unit; supports nesting |
| `PropertyCommand` | ~93 | Sets a single widget property with rollback |
| `InsertWidgetCommand` / `DeleteWidgetCommand` | ~120, ~142 | Insert/delete widgets from scene/project |
| `ReorderCommand` | ~172 | Changes Z-order of items |
| `CommandHistory` | ~194 | Stack-based history manager with push/pop/can_undo/can_redo |

**Quality issues**: Race condition on `CommandHistory.active` (plain bool, not locked). Unbounded list growth. Silent failures when `active=False`.

#### `designer/model/project.py` (~186 lines)
**What it does**: Central `Project` data model holding widgets, bindings, assets, metadata. Serializes/deserializes to/from JSON bundles.

| Method | Lines | Purpose |
|--------|-------|---------|
| `add_widget` / `remove_widget` / `get_widget` / `get_widgets` | 45-64 | Widget CRUD |
| `add_binding` / `remove_binding` / `get_binding` / `get_bindings` | 66-90 | Binding CRUD |
| `serialize` / `deserialize` | 103-169 | Full JSON round-trip |
| `copy_from` | 172-180 | Duplicates project state (**shallow-copy bug**) |
| `ensure_bundle_dir` | 183-186 | Creates project directory structure |

**Quality issues**: Shallow copy bug on nested dicts. No schema validation on `deserialize()`. Magic string JSON keys.

#### `designer/model/binding_diagnostics.py` (~74 lines)
**What it does**: Validates runtime bindings between UI widgets and back-end data sources. Produces `DiagnosticResult` entries (ready/warning/error/info).

**Quality issues**: Hardcoded validation rules, no caching, no async support.

#### `designer/palette/widget_registry.py` (~72 lines)
**What it does**: Registry mapping widget type names to classes, display names, categories, and asset property definitions. Global singleton instance.

**Quality issues**: Mutable global state, no validation on registration, hardcoded widget list.

#### `designer/palette/widget_palette.py` (~120 lines)
**What it does**: Renders the left-side palette sidebar showing widget categories with drag-and-drop support onto the canvas.

**Quality issues**: Hardcoded drag size (80x60), no virtualization, QTimer memory leak risk.

#### `designer/generators/qml_generator.py` (~150 lines)
**What it does**: Translates the `Project` model into QML source code for embedded devices. Supports binding interpolation (`{tag_address}`, `{enum_value}`).

| Method | Lines | Purpose |
|--------|-------|---------|
| `generate` | ~33 | Entry point — walks Project model |
| `_render_widget` | ~55 | Renders a single widget to QML |
| `_render_property` | ~108 | Renders widget properties |
| `_resolve_binding` | ~120 | Resolves tag binding expressions |
| `_render_bindings` | ~138 | Renders QML bindings section |

**Quality issues**: String interpolation without sanitization (injection risk). No template engine. Hardcoded QML snippets.

#### `designer/ui/designer_workspace.py` (~1 910 lines)
**What it does**: **Main application window** — integrates canvas, palette, properties panel, toolbar, status bar, tree view, and file operations. The single largest file in the codebase.

| Section | Lines | Purpose |
|---------|-------|---------|
| Signals | 13-15 | `projectChanged`, `deployRequested`, `sceneSelectionChanged` |
| `_setup_ui` | ~67 | Main layout initialization |
| `_setup_central_widget` | ~101 | Central canvas widget |
| `_setup_tool_bar` | ~127 | Toolbar with file/edit/insert actions |
| `_setup_tree_view` | ~194 | Layer tree sidebar |
| `_setup_properties_panel` | ~322 | Property inspector |
| `_setup_status_bar` | ~395 | Status bar |
| Canvas management | ~206-315 | Scene setup, signal connections, tree sync |
| Property editing | ~436-600 | `_on_property_changed`, `_sync_property_panel` |
| Edit operations | ~605-780 | cut/copy/paste/duplicate/delete/undo/redo/select_all/z_order |
| Keyboard shortcuts | ~520-570 | Ctrl+Z/Y/C/V/A, Delete, Ctrl+D, arrows, Ctrl+1/2/3 |
| File operations | ~800-1200 | open_project/save_project/save_as_project/generate/deploy |
| Asset management | ~1810-1910 | image/text asset dialogs |
| Context menus | ~1842-1895 | Widget and tree context menus |

**Quality issues**: **Massive god class** — handles UI layout, edit logic, file I/O, clipboard, drag-and-drop, keyboard shortcuts, property editing, tree sync, context menus. No error handling in file I/O. Lambda closure bugs. Hardcoded shortcuts and magic numbers. Tight coupling.

#### `designer/canvas/widget_previews.py`
**What it does**: Visual preview widgets rendered as `QGraphicsItem` subclasses for the canvas — each preview renders a miniature representation of the widget type.

**Quality issues**: Duplicate paint code across subclasses. No DPI awareness. Memory leak risk on asset references.

#### `designer/canvas/designer_view.py`
**What it does**: Main canvas `QGraphicsView` — handles zoom/pan, selection, drag-and-drop from palette, context menus, selection box, wheel zoom.

**Quality issues**: Manual hit-testing error-prone with rotated/scaled items. Selection box rendering not integrated with QGraphicsItem selection model. No scroll-bounce protection.

---

### 2.4 `tools/hmi_deployer/` — Deployment Studio

#### `tools/hmi_deployer/app.py`
**What it does**: Entry point that parses CLI arguments, bootstraps the Qt application theme, and launches `MainWindow`.

#### `tools/hmi_deployer/mainwindow.py`
**What it does**: Main application window with tabs for Deployment, Device Preview, AI Design, and Tag Lab. Manages state transitions between panels.

**Quality issues**: Monolithic class, no state machine, hardcoded tab order, progress bar resets on every deploy.

#### `tools/hmi_deployer/devicepanel.py`
**What it does**: PySide6 `QWidget` displaying a hardware mockup of the target device with a live embedded QML preview inside the bezel.

**Quality issues**: QQuickWidget cleanup not tied to widget destruction. No file-existence check before loading. No debouncing on resize.

#### `tools/hmi_deployer/bezel.py`
**What it does**: Shared renderer that draws the physical display bezel/frame around QML previews, providing a realistic device mockup.

**Quality issues**: Hardcoded bezel dimensions. `QPainter` not disposed on error paths. No caching of rendered bezel image.

#### `tools/hmi_deployer/deployer.py`
**What it does**: Core deployment engine — validates bundle structure, packages as tarball, SCP transfers to target, executes remote install with atomic replace.

**Quality issues**: No timeout on SCP/SSH. No rollback on partial failure. Swallowed exceptions. Hardcoded remote temp path.

#### `tools/hmi_deployer/deploy_history.py`
**What it does**: Manages immutable log of past deployments with timestamp, bundle path, target, and status. Supports timeline merging.

**Quality issues**: No validation on load. Silent return on failure. No deduplication.

#### `tools/hmi_deployer/readiness_core.py`
**What it does**: Audits whether a bundle and target display are ready for deployment — file existence, SSH connectivity, QML validity, runtime dependencies.

**Quality issues**: Blocks calling thread. SSH check uses raw `subprocess` instead of `ssh.py` module. No retry on transient failures.

#### `tools/hmi_deployer/ssh.py`
**What it does**: Provides off-thread SSH and SCP operations using paramiko with signals for progress and results back to GUI.

**Quality issues**: No host key verification (MITM risk). Timeout doesn't cancel transport. Progress callbacks from background threads crash Qt UI. No exponential backoff.

#### `tools/hmi_deployer/scaffold.py`
**What it does**: Scaffolds a new BYOA deployment bundle — generates directory structure, manifest, default QML entry point, and packaging config.

**Quality issues**: Silent overwrite of existing directories. Magic string template names. No idempotency check.

#### `tools/hmi_deployer/telemetry.py`
**What it does**: Simulates telemetry tag values and relays them over SSH to running devices for validation against real runtime behavior.

**Quality issues**: No bounds checking on simulated values. Reuses stale SSH connections. No deduplication. `time.sleep()` in generators not composable with async.

#### `tools/hmi_deployer/taglab.py`
**What it does**: Waveform-based telemetry injection engine — interprets tag definitions and generates time-series data for offline validation.

**Quality issues**: No division-by-zero protection. Mutates input dicts. Hardcoded 60 Hz sample rate. No memoization.

#### `tools/hmi_deployer/taglab_panel.py`
**What it does**: PySide6 `QWidget` providing the Tag Lab UI where users define, edit, and preview telemetry tags with waveform visualizations.

**Quality issues**: Draws on main thread (blocks UI). No MVVM separation. No duplicate tag name check. No undo/redo.

#### `tools/hmi_deployer/ai_design.py`
**What it does**: Connects to external AI design services (OpenAI, Anthropic, Ollama, Google, vLLM) and generates QML code from natural language descriptions.

**Quality issues**: API key as plain string. No retry on 429/503. Regex-based parsing fragile against model output changes. HTTP session never closed.

#### `tools/hmi_deployer/ai_generator.py`
**What it does**: Parses AI-generated output into `DesignerProject` representation with widgets, layouts, and property bindings.

**Quality issues**: Throws on malformed input — no error recovery. Deep nesting without bounds check. Magic string widget type matching.

#### `tools/hmi_deployer/ai_tab.py`
**What it does**: AI Design tab widget — generation console, prompt input, log display, and preview area for AI-generated UIs.

**Quality issues**: Runs AI call on main thread (freezes UI). Log console appends without truncation (memory leak). No cancel token. Stale widgets in preview.

#### `tools/hmi_deployer/native_preview.py`
**What it does**: Provides live bezel preview for Python runtime bundles, embedding a subprocess running the bundle's QML or Python entry point.

**Quality issues**: No working directory isolation. Duplicate processes not prevented. Zombie processes. No stderr/stdout capture.

#### `tools/hmi_deployer/__init__.py`
**What it does**: Package init exposing `__version__` and `__all__` exports.

#### `tools/hmi_deployer/resources/native_preview.qml`
**What it does**: QML template used by native preview subprocess for rendering customer apps inside the bezel.

---

### 2.5 `gui/hmi_loader/` — Runtime HMI Loader

#### `gui/hmi_loader/main.py`
**What it does**: Core HMI loading infrastructure — manages bundle loading, QML engine creation, device panel communication, and state transitions (suspended → loaded → running).

**Quality issues**: Complex multi-state management. Likely long methods. Tight coupling to QML structures.

#### `gui/hmi_loader/tagengine.py`
**What it does**: Manages tag data from the hardware daemon — receives UDP datagrams, maintains tag values in `QVariantMap`, ring-buffered history per tag, alarm evaluation, and exposes `Bus`/`Tags` shims to QML.

| Method | Purpose |
|--------|---------|
| `expose_to_qml()` | Creates QML-accessible shim so `Bus.value("ai.pot", 0)` works |
| `_handle_telemetry()` | Processes incoming datagrams, updates tag values, triggers alarms |
| `_evaluate_alarms()` | Checks alarms against current tag values, tracks severity |
| `history()` | Returns ring-buffered history with underscore alias support |
| `acknowledge()` | Marks an alarm acknowledged by tag name or alias |

**Quality issues**: Dotted tag names create complexity. Signal emission guard fragile. No type hints. Magic numbers. Thread safety with socket data on Qt event loop.

---

### 2.6 `schema/` — Bundle Schema & Validation

#### `schema/__init__.py`
**What it does**: Package init exposing `manifest`, `deps`, `bundle` and defining `BundleError` exception.

#### `schema/manifest.py`
**What it does**: Defines manifest schema constants, validation regex, and provides `validate_bundle()`, `load_manifest()`, `alarm_tags()`, `readme_manifest()`.

**Quality issues**: Dead code — `readme_manifest()` never called. Duplicate regex patterns. No docstrings on private functions. Magic validation lists.

#### `schema/deps.py`
**What it does**: Resolves and validates Qt version requirements from manifests, and resolves dependency files from `deps.json`.

**Quality issues**: Only `>=` operator implemented. No type hints. Hardcoded Qt version lookup.

#### `schema/bundle.py`
**What it does**: Utility functions for bundle operations — creating, copying, reading metadata.

**Quality issues**: Thin wrappers, no docstrings, minimal testing.

---

### 2.7 `ui/` — Shadcn QML Component Kit

#### `ui/gallery.py`
**What it does**: Renders a gallery preview of all Shadcn UI components in light/dark themes and optionally saves a screenshot. Implements CONTRACT section 7.1.

**Quality issues**: Subprocess spawning fragile on Windows. No error handling around `QQuickRenderControl`. Magic timing `--exit-after 1500`.

#### `ui/widget_catalog.py`
**What it does**: Registry of available widget types (ShGauge, ShButton, ShTrendChart, etc.) with metadata used by designer and AI generator.

**Quality issues**: Hardcoded widget list. No type hints. Potential duplication with `designer/palette/widget_registry.py`.

#### `ui/icons/vendor_icons.py`, `ui/icons/tabler_icons.py`, `ui/icons/__init__.py`
**What they do**: Icon resources — vendor-specific SVGs and Tabler icon name-to-SVG mappings.

**Quality issues**: Static mapping files growing maintenance burden. No lazy loading.

#### `ui/tests/test_tokens.py`
**What it does**: Validates that `tokens.json` (source of truth) and `Theme.qml` are synchronized — colors, border radii, font sizes must match exactly.

**Quality issues**: Regex-based matching fragile to formatting changes. Tests only detect drift, don't prevent it.

#### `ui/tests/test_gallery_render.py`
**What it does**: Tests gallery renders correctly in light and dark themes — non-blank images with correct background colors.

**Quality issues**: Subprocess-based testing slow and fragile. Magic timeout. No retry logic.

---

### 2.8 `deploy/` — Provisioning

#### `deploy/provision_panel.py`
**What it does**: GUI panel for provisioning/deploying HMIs to target devices — SSH connection, file transfer, device configuration.

**Quality issues**: Tight coupling between UI and deployment logic. No dedicated tests. Hardcoded SSH parameters.

---

### 2.9 `tests/` — Test Suite (~60 files)

The test suite is comprehensive with tests covering nearly every module. Key test files:

| Test File | What it Tests |
|-----------|---------------|
| `test_alarm_engine.py` (541 lines) | Alarm validation, history ring buffer, activation/escalation/clearing/ack |
| `test_ai_stream_events.py` (413 lines) | Stream parsers for OpenAI, Anthropic, Ollama, Google, daemon protocol |
| `test_bundle_validation.py` | Bundle validity across deployer, shell CLI, and target installer |
| `test_bundle_packaging.py` | Bundle exclusion patterns, `.hmiignore`, size limits, SHA-256 sidecar |
| `test_bus_liveness.py` | QML `Bus.value()` bindings follow tags in real-time |
| `test_capture_preview_tab.py` | Preview tab switching, bundle activation |
| `test_binding_diagnostics.py` | `audit_bindings()` produces correct DiagnosticRows |
| `test_designer_*.py` (12 files) | Canvas, model, generator, deploy, actions, arrangement, assets, containers, previews, reparent, text, toolbars, widget catalog |
| `test_daemon_protocol.py` | UDP/JSON message framing, parsing, error handling |
| `test_modbus_client.py` | Modbus connection, read/write, error recovery |
| `test_deploy_state.py`, `test_deploy_history.py` | Deploy state machine, history tracking |
| `test_readiness_*.py` | Readiness checks (core + UI) |
| `test_relay_*.py` | Relay set/pulse/status, worker lifetime |
| `test_ssh_commands.py` | SSH command execution |
| `verify_smoke_capture.py` | End-to-end bezel capture smoke test |

**Quality issues**: 50+ test files with similar patterns. Heavy subprocess usage. No parameterization. Global `QCoreApplication` state pollution. Tight coupling to private internals.

---

## 3. Code Quality Report

### 3.1 Critical Issues

| # | Issue | Location(s) | Impact | Fix |
|---|-------|-------------|--------|-----|
| C1 | **No host key verification in SSH** | `ssh.py` | MITM vulnerability on deployment connections | Add `RejectPolicy` or known_hosts verification |
| C2 | **Background thread callbacks crash Qt UI** | `ssh.py`, `native_preview.py` | Application crashes during deploy/preview | Use `QMetaObject.invokeMethod` or `QThread` |
| C3 | **Shallow copy bug in `Project.copy_from()`** | `project.py:172` | Shared mutable state between projects → data corruption | Use `copy.deepcopy()` |
| C4 | **SQL injection / QML injection via unsanitized strings** | `qml_generator.py` | Malicious property values inject arbitrary QML/JS | Sanitize all interpolated values |
| C5 | **`assert` in production daemon code** | `hmi_hwd.py:1601` | Silent failure with `python -O` | Replace with `ValueError`/`RuntimeError` |

### 3.2 High-Priority Issues

| # | Issue | Location(s) | Impact |
|---|-------|-------------|--------|
| H1 | **God class: `DesignerWorkspace` at 1 910 lines** | `designer_workspace.py` | Unmaintainable, impossible to test in isolation |
| H2 | **Duplicate Modbus poll loop** | `hmi_hwd.py:1755-1836` | Two nearly identical branches for TcpClient vs Sim — DRY violation |
| H3 | **Event loop blocked by synchronous Modbus I/O** | `hmi_hwd.py:1209` | Pulse commands block async event loop |
| H4 | **Unbounded command history growth** | `commands.py:196` | Memory leak in long design sessions |
| H5 | **Race condition on `CommandHistory.active`** | `commands.py:205` | Plain bool read/written without locking |
| H6 | **File I/O has no error handling** | `designer_workspace.py:800-1200` | File system errors crash the UI |
| H7 | **No rollback on partial deploy failure** | `deployer.py` | Corrupted deployment on target device |
| H8 | **No retry/backoff on SSH connections** | `ssh.py` | Transient network issues cause deploy failures |
| H9 | **AI generation runs on main thread** | `ai_tab.py` | UI freezes during generation |
| H10 | **Subprocess zombie processes** | `native_preview.py` | Preview processes leak |

### 3.3 Medium-Priority Issues

| # | Issue | Location(s) |
|---|-------|-------------|
| M1 | No type hints anywhere in the codebase | All `.py` files |
| M2 | No structured logging — only `print()` statements | `hmi_deployer/`, `schema/` |
| M3 | Hardcoded magic values throughout (ports, paths, timeouts, sizes) | All modules |
| M4 | No `__all__` in most `__init__.py` files | All `*/__init__.py` |
| M5 | Dead code: `readme_manifest()`, `load_manifest_from_archive()` | `schema/manifest.py` |
| M6 | Empty files: `run_tests.py`, `ui/tests/__init__.py` | Root, `ui/tests/` |
| M7 | Test files too large (>400 lines) | `test_alarm_engine.py`, `test_ai_stream_events.py` |
| M8 | No test parameterization — repeated test patterns | `tests/test_designer_*.py` |
| M9 | Only `>=` version operator supported in `deps.py` | `schema/deps.py` |
| M10 | No input validation on `Project.deserialize()` | `designer/model/project.py` |
| M11 | HTTP session leak in `ai_design.py` | `tools/hmi_deployer/ai_design.py` |
| M12 | UART thread spin-loop on port close | `hmi_hwd.py:755` |
| M13 | Canvas preview items: duplicate paint code, no DPI awareness | `designer/canvas/` |
| M14 | No automated sync between `tokens.json` and `Theme.qml` | `ui/` |
| M15 | Subprocess-heavy tests — slow and platform-dependent | `test_bundle_validation.py`, `test_gallery_render.py` |
| M16 | Global mutable state in `widget_registry.py` | `designer/palette/widget_registry.py` |
| M17 | No idempotency check in scaffold | `scaffold.py` |
| M18 | Only `assert __name__ == "__main__"` guard missing in `app.py` | `tools/hmi_deployer/app.py` |

### 3.4 Low-Priority / Nice-to-Have

| # | Issue | Location(s) |
|---|-------|-------------|
| L1 | No docstrings on most public functions | All modules |
| L2 | Nested function definitions in `main.py` hard to test | `main.py` |
| L3 | Lambda closure bugs in context menus | `designer_workspace.py:625,713` |
| L4 | Magic string keyboard shortcuts | `designer_workspace.py:520-570` |
| L5 | No scroll-bounce protection on zoom | `designer/canvas/designer_view.py` |
| L6 | No memoization of waveform computation | `taglab.py` |
| L7 | No bounds checking on telemetry simulation | `telemetry.py` |
| L8 | Hardcoded 60 Hz sample rate | `taglab.py` |
| L9 | No undo/redo for tag modifications | `taglab_panel.py` |
| L10 | No test coverage for `schema/bundle.py` | `schema/bundle.py` |

---

## 4. Cross-Cutting Concerns

### 4.1 Architecture Strengths
- **Clean 3-layer separation**: Hardware (daemon) → App (loader) → Host (studio) — well-documented in README and CONTRACT
- **Sim/Prod parity**: `--sim` mode with `GpioSim`, `IioSim`, `ModbusSim` mirrors real hardware for development
- **Self-re-execution pattern**: `main.py` cleverly handles both checkout and packaged executable modes
- **Atomic deployment**: Bundle validation → tarball → SCP → atomic install with rollback potential
- **Tag-driven architecture**: Decouples HMI apps from hardware — apps bind to tags, not GPIO/ADC directly
- **Comprehensive test suite**: 60+ test files covering core logic, though some could be improved

### 4.2 Architecture Weaknesses
- **God classes everywhere**: `DesignerWorkspace` (1 910 lines), `HwDaemon` (2 213 lines), `MainWindow` — too much responsibility
- **Tight coupling**: Direct imports of private modules everywhere; no DI/mocking support
- **Mixed threading models**: asyncio + Qt event loop + daemon threads + subprocesses — no unified pattern
- **No config-driven behavior**: Magic numbers scattered everywhere instead of extracted to config
- **Platform-dependent tests**: Shell-based tests fail on Windows silently

### 4.3 Testing Concerns
- **Subprocess-heavy**: `test_bundle_validation.py`, `test_bundle_packaging.py`, `test_gallery_render.py` spawn subprocesses → slow
- **Tight coupling to internals**: Tests access private attributes like `_right_tabs`, `_preview_panel_wrap`
- **Global state pollution**: `QCoreApplication` shared across tests in setUpClass
- **No parameterization**: Repeated test patterns could use `@pytest.mark.parametrize`
- **Empty test files**: `run_tests.py`, `ui/tests/__init__.py`

---

## 5. Prioritized Improvement Plan

### Phase 1: Stability & Safety (Weeks 1-4)
| Priority | Action | Effort |
|----------|--------|--------|
| P0 | Add SSH host key verification (`ssh.py`) | 2 days |
| P0 | Fix background thread → Qt UI crash pattern | 3 days |
| P0 | Fix `Project.copy_from()` shallow copy bug | 1 day |
| P0 | Replace `assert` in daemon with proper errors | 1 day |
| P0 | Sanitize QML generator interpolation | 2 days |

### Phase 2: Code Health (Weeks 5-8)
| Priority | Action | Effort |
|----------|--------|--------|
| P1 | Split `DesignerWorkspace` into focused view controllers | 2 weeks |
| P1 | Deduplicate Modbus poll loop in `hmi_hwd.py` | 3 days |
| P1 | Add async Modbus I/O (use `asyncio.start_connection` or `trio`) | 1 week |
| P1 | Add command history size limit + LRU eviction | 2 days |
| P1 | Add error handling to all file I/O in `designer_workspace.py` | 3 days |
| P1 | Add deploy rollback on failure | 1 week |
| P1 | Add SSH retry with exponential backoff | 2 days |
| P1 | Move AI generation to background thread | 3 days |
| P1 | Fix subprocess zombie processes | 1 day |

### Phase 3: Developer Experience (Weeks 9-12)
| Priority | Action | Effort |
|----------|--------|--------|
| P2 | Add type hints to all public APIs | 2 weeks |
| P2 | Add structured logging (use `structlog` or `loguru`) | 3 days |
| P2 | Extract magic values to config constants | 1 week |
| P2 | Add `__all__` to all `__init__.py` | 1 day |
| P2 | Remove dead code (`readme_manifest`, etc.) | 1 day |
| P2 | Remove empty files | 0.5 day |
| P2 | Split large test files | 3 days |
| P2 | Add `@pytest.mark.parametrize` where applicable | 3 days |
| P2 | Support full version operators (`==`, `<=`, `>=`, `<`, `>`, `~=`, `!=`) | 3 days |
| P2 | Add input validation to `Project.deserialize()` | 3 days |
| P2 | Fix HTTP session leak in `ai_design.py` | 1 day |
| P2 | Fix UART thread spin-loop | 2 days |

### Phase 4: Polish & Automation (Weeks 13-16)
| Priority | Action | Effort |
|----------|--------|--------|
| P3 | Auto-generate `Theme.qml` from `tokens.json` | 1 week |
| P3 | Add auto-discovery for widget catalog | 3 days |
| P3 | Add canvas DPI awareness | 2 days |
| P3 | Add central shortcut definitions | 2 days |
| P3 | Add idempotency to scaffold | 1 day |
| P3 | Add test coverage metrics + CI enforcement | 2 days |
| P3 | Cross-platform test fixes (replace subprocess where possible) | 1 week |
| P3 | Add integration test fixtures and base classes | 1 week |

---

## 6. Summary Matrix

### By Module

| Module | Lines (est.) | Tests | Issues | Priority |
|--------|-------------|-------|--------|----------|
| `daemon/hmi_hwd.py` | 2 213 | `test_daemon_protocol.py` | Duplicate code, assert, event loop blocking, thread issues | **High** |
| `daemon/modbus.py` | 616 | `test_modbus_*.py` | Bare except, no retry, incomplete FC 22 | Medium |
| `designer/ui/designer_workspace.py` | 1 910 | `test_designer_*.py` (many) | God class, no error handling, tight coupling | **High** |
| `designer/model/project.py` | 186 | `test_designer_model.py` | Shallow copy, no validation | **High** |
| `designer/commands/commands.py` | 230 | `test_designer_actions.py` | Race condition, unbounded growth | **High** |
| `designer/generators/qml_generator.py` | 150 | `test_designer_generator.py` | Injection risk, hardcoded snippets | **High** |
| `designer/canvas/` (2 files) | 200+ | `test_designer_canvas_*.py` | Duplicate paint, no DPI | Medium |
| `designer/palette/` (2 files) | 200+ | `test_designer_widget_catalog.py` | Hardcoded, no virtualization | Medium |
| `tools/hmi_deployer/mainwindow.py` | 300+ | `test_capture_preview_tab.py` | God class, no state machine | **High** |
| `tools/hmi_deployer/devicepanel.py` | 70+ | `test_native_preview.py` | Memory leak, no file check | Medium |
| `tools/hmi_deployer/deployer.py` | 80+ | `test_deploy_*.py` | No timeout, no rollback, swallowed errors | **High** |
| `tools/hmi_deployer/ssh.py` | 90+ | `test_ssh_commands.py` | MITM risk, thread crash, no backoff | **High** |
| `tools/hmi_deployer/ai_tab.py` | 80+ | `test_ai_*.py` | Main thread freeze, memory leak | **High** |
| `tools/hmi_deployer/native_preview.py` | 75+ | `test_native_preview.py` | Zombie processes, no isolation | Medium |
| `tools/hmi_deployer/scaffold.py` | 70+ | (none) | Silent overwrite, no idempotency | Medium |
| `tools/hmi_deployer/taglab.py` | 80+ | `test_taglab*.py` | Mutation, no div-by-zero guard | Medium |
| `tools/hmi_deployer/taglab_panel.py` | 100+ | `test_taglab_command_sink.py` | Main thread drawing, no MVVM | Medium |
| `tools/hmi_deployer/ai_design.py` | 80+ | `test_ai_*.py` | API key leak, session leak, regex parsing | High |
| `tools/hmi_deployer/ai_generator.py` | 85+ | `test_ai_integration.py` | No error recovery, magic strings | Medium |
| `tools/hmi_deployer/telemetry.py` | 100+ | (none) | No bounds checking, stale connections | Low |
| `tools/hmi_deployer/bezel.py` | 50+ | `test_device_panel_geometry.py` | Hardcoded, no caching | Low |
| `tools/hmi_deployer/deploy_history.py` | 75+ | `test_deploy_history.py` | No validation, no dedup | Low |
| `tools/hmi_deployer/readiness_core.py` | 60+ | `test_readiness_*.py` | Blocking thread, raw subprocess | Medium |
| `gui/hmi_loader/main.py` | 200+ | (few) | Complex state, tight coupling | Medium |
| `gui/hmi_loader/tagengine.py` | 200+ | `test_tagengine_integration.py`, `test_bus_liveness.py`, `test_alarm_engine.py` | Thread safety, magic numbers | Medium |
| `schema/manifest.py` | 100+ | `test_bundle_validation.py` | Dead code, no docstrings | Low |
| `schema/deps.py` | 50+ | `test_dependencies.py` | Limited version operators | Low |
| `schema/bundle.py` | 30+ | (none) | No tests | Low |
| `main.py` | 94 | `verify_smoke_capture.py` | Nested functions, magic paths | Low |
| `ui/gallery.py` | 80+ | `test_gallery_render.py` | Subprocess, magic timing | Medium |
| `ui/widget_catalog.py` | 60+ | `test_designer_widget_catalog.py` | Hardcoded list | Low |
| `ui/icons/*.py` | 200+ | (none) | No lazy loading | Low |
| `deploy/provision_panel.py` | 100+ | (none) | No tests, tight coupling | Medium |
| `tests/` (60 files) | 8 000+ | — | Subprocess-heavy, no param, global state | Medium |

### Overall Stats

| Metric | Value |
|--------|-------|
| Total Python files | ~60 |
| Total QML files | ~45 |
| Estimated total lines | ~10 000+ |
| Files with type hints | 0 |
| Files with docstrings on public APIs | < 10 |
| Test files | ~60 |
| Test files with subprocess calls | ~8 |
| Empty/stub files | 2 (`run_tests.py`, `ui/tests/__init__.py`) |
| Files without `__all__` | ~15 |
| Files without dedicated tests | ~20 |
| God classes (>500 lines) | 2 (`hmi_hwd.py`, `designer_workspace.py`) |
| Critical issues | 5 |
| High-priority issues | 10 |
| Medium-priority issues | 18 |

---

*Report generated: 2026-09-16*
*Analysis scope: All Python and QML source files in the repository*