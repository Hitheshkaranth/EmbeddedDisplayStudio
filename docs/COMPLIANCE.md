# HMI System Compliance Report

## Summary

| Contract Section | Component | Status |
| --- | --- | --- |
| 2 (Wire Protocol) | `hmi-hwd` (daemon) | COMPLIANT |
| 2 (Wire Protocol) | `hmi-gui` (GUI Loader) | COMPLIANT |
| 3 (Install Paths) | Yocto Recipes | COMPLIANT |
| 4 (Bundle Format) | All validators (shared) | COMPLIANT |
| 5 (systemd units) | `target/systemd/*` | COMPLIANT |
| 6 (Deployment) | `hmi-install` / `deploy_to_hmi.sh` | COMPLIANT |
| 7 (Reliability) | All | COMPLIANT |
| 7.1 (Docs Standard)| All | DEVIATION |
| 10 (Deployer L&F) | `tools/hmi_deployer/devicepanel.py` | COMPLIANT |
| 11 (Design System) | `ui/` | COMPLIANT |

## Deviations

### 1. Manifest Validation (Section 4)

All bundle validators now use the single shared implementation in `schema/manifest.py`:

- **Host CLI** (`deploy_to_hmi.sh`): Calls `python3 schema/manifest.py <bundle_dir>` at line 692, which exits 1 on any validation failure.
- **Target installer** (`hmi-install`): Calls the same validator at line 629, enforcing all fields including `schema`.
- **GUI loader** (`main.py`): Uses `validate_manifest()` which enforces schema version 1, the exact `^[a-z0-9][a-z0-9._-]{0,63}$` name regex, version, and entry.
- **Deployer GUI** (`deployer.py`): Delegates to `schema/manifest.py` for validation.

This eliminates the previous four-way disagreement where each validator enforced different fields and used different regexes. Regression test: `tests/test_bundle_validation.py` asserts all four validators agree.

### 2. QML Slots for Wire Protocol Commands (Section 2)

All seven protocol commands now have QML slots in `TagEngine` (`gui/hmi_loader/tagengine.py`):

- `write(tag, value)` → `set` (CONTRACT 2.2)
- `pulse(tag, ms)` → `pulse` (CONTRACT 2.2)
- `uart_tx(data)` → `uart_tx` (CONTRACT 2.2)
- `ping()` → `ping` (CONTRACT 2.2)
- `list_tags()` → `list` (CONTRACT 2.2, returns `QVariantList` of tag names)
- `unsubscribe()` → `unsubscribe` (CONTRACT 2.2)
- `subscribe` is internal (automatically maintained by subscription timer)
- `value(name, fallback)` reads from the tag map (not a protocol command, but provides safe tag lookup)

## Not Implemented

None. All seven protocol commands (`set`, `pulse`, `uart_tx`, `subscribe`, `unsubscribe`, `list`, `ping`) are now implemented in `TagEngine`.

## Documentation Standard (7.1) Coverage

The contract demands: "Every function, method, class and signal: a docstring/comment block... Every declared variable, constant, property and config key gets a comment... anything carrying a magic number is not exempt."

We ran an AST parser to count missing docstrings across the codebase. The worst offenders are:

1. `tools/hmi_deployer/mainwindow.py` (24 missing docstrings)
2. `tools/hmi_deployer/devicepanel.py` (12 missing docstrings)
3. `tools/hmi_deployer/telemetry.py` (8 missing docstrings)
4. `daemon/hmi_hwd.py` (5 missing docstrings)
5. `tools/hmi_deployer/app.py` (2 missing docstrings)

W5 (Deployer GUI) is the primary violator, failing to document classes and methods like `update_geometry()`, `paintEvent()`, and `__init__()`.

## Known-Good

The following sections were verified as fully compliant:
- **Section 3 (Install Paths):** All files are placed precisely where required via `yocto/meta-hmi/recipes-hmi/*` and `tmpfiles.d`.
- **Section 5 (Systemd Units):** Dependencies, Type (`notify` vs `simple`), and restart policies accurately match the contract.
- **Section 6 (Deployment):** Target-side atomic swap leverages `os.replace` correctly over temporary symlinks. GUI restart timeout (25s) and automatic rollback function correctly.
- **Section 10 (Deployer L&F):** `devicepanel.py` executes the exact geometric inset margins (9.5%), LED states (dim blue/amber/red/blue), and forces the dark preview theme as mandated.
- **Section 11 (Design System):** `Theme.qml` strictly mirrors the Tailwind "slate" color tokens and radii values. SVG vendoring in `tabler_icons.py` works robustly.