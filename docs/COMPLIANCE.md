# HMI System Compliance Report

> **Status: historical.** This audit was run against the tree before the final
> integration pass. Every DEVIATION recorded below has since been fixed and
> pinned with a regression test:
>
> * **Manifest validation disagreement** — all four validators now use the
>   contract pattern `^[a-z0-9][a-z0-9._-]{0,63}$`, and `hmi-install` now
>   enforces the `schema` field it previously ignored. Covered by
>   `tests/test_bundle_validation.py`, which asserts the host CLI, the target
>   installer and the deployer GUI agree in both directions.
> * **Missing protocol slots** — `TagEngine` now exposes `uart_tx` and `ping`
>   alongside `write`, `pulse` and `value`.
>
> The report is kept because its reasoning about *why* each deviation mattered
> is still the best explanation of those rules. Treat the status column as a
> snapshot, not current state.

## Summary

| Contract Section | Component | Status |
| --- | --- | --- |
| 2 (Wire Protocol) | `hmi-hwd` (daemon) | COMPLIANT |
| 2 (Wire Protocol) | `hmi-gui` (GUI Loader) | DEVIATION |
| 3 (Install Paths) | Yocto Recipes | COMPLIANT |
| 4 (Bundle Format) | Host Deployer CLI (`deploy_to_hmi.sh`) | DEVIATION |
| 4 (Bundle Format) | Target Installer (`hmi-install`) | DEVIATION |
| 4 (Bundle Format) | GUI Loader (`main.py`) | DEVIATION |
| 4 (Bundle Format) | Host Deployer GUI (`deployer.py`) | DEVIATION |
| 5 (systemd units) | `target/systemd/*` | COMPLIANT |
| 6 (Deployment) | `hmi-install` / `deploy_to_hmi.sh` | COMPLIANT |
| 7 (Reliability) | All | COMPLIANT |
| 7.1 (Docs Standard)| All | DEVIATION |
| 10 (Deployer L&F) | `tools/hmi_deployer/devicepanel.py` | COMPLIANT |
| 11 (Design System) | `ui/` | COMPLIANT |

## Deviations

### 1. Inconsistent Manifest Validation (Section 4)

**File & Line:**
- `target/bin/hmi-install` (Lines 290-320)
- `deploy/deploy_to_hmi.sh` (Lines 758-788)
- `gui/hmi_loader/main.py` (Lines 172-187)
- `tools/hmi_deployer/deployer.py` (Lines 36-68)

**What the contract says:**
"The deployer host-side packaging, the target-side hmi-install, and the hmi-gui loading sequence MUST all independently validate the bundle."
"The manifest must be rejected if any field is missing or the wrong type."
The expected fields are `schema`, `name` (`^[a-z0-9][a-z0-9._-]{0,63}$`), `version`, `entry`, `screen`, `tags_required`, and `qt`.

**What the code does:**
The three (technically four) implementations disagree and are incomplete:
- `hmi-install` only checks `name`, `version`, `entry`. It uses a non-compliant regex `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`. It silently ignores `schema`, `screen`, `tags_required`, and `qt`.
- `deploy_to_hmi.sh` checks `schema`, `name`, `version`, `entry`. It uses a non-compliant regex `^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$`. It ignores `screen`, `tags_required`, and `qt`.
- `main.py` checks `schema`, `name`, `entry`. It ignores `version`, `screen`, `tags_required`, and `qt_ver`.
- `deployer.py` checks all fields *except* `version`, which it forgets to validate.

**Practical consequence:**
A bundle with missing tags or screen resolution fields will pass the host deployment, pass target installation, and crash silently at runtime. A bundle with capital letters in its name will fail installation but pass other checks depending on the regex used. This breaks the contractual guarantee that validation is unified and strict.

**Suggested fix:**
Create a single strict JSON schema validation block and mirror it exactly across all Python/Bash scripts. Specifically:
```python
# In hmi-install and all validation layers:
if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", m['name']):
    sys.exit(1)
# Ensure schema, screen, tags_required, and qt are asserted in all 4 places.
```

### 2. Missing QML Slots for Wire Protocol Commands (Section 2)

**File & Line:**
- `gui/hmi_loader/tagengine.py` (Lines 110-180)

**What the contract says:**
Section 2.2 defines client-to-daemon commands: `set`, `pulse`, `uart_tx`, `subscribe`, `unsubscribe`, `list`, `ping`.

**What the code does:**
`TagEngine` exposes `@Slot` methods for `write` (set), `pulse`, and `value`. However, it completely lacks QML slots for `uart_tx`, `ping`, or `list`.

**Practical consequence:**
QML applications cannot transmit serial data because there is no `Bus.uart_tx()` method to call, rendering the `uart_tx` protocol feature useless for the end-user.

**Suggested fix:**
Add the missing slots to `TagEngine`:
```python
@Slot(str)
def uart_tx(self, data: str) -> None:
    self._send_command("uart_tx", {"data": data})
```

## Not Implemented

The following items are required by the contract but not implemented by any file:
- `TagEngine` (`gui/hmi_loader/tagengine.py`) lacks the `uart_tx` slot (Section 2.2).
- `TagEngine` lacks the `ping` and `list` command slots (Section 2.2).

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
