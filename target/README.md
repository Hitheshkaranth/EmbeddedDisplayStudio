# Target Subsystem (target/)

Layer 3 target-side integration and execution scripts for the BYOA HMI system.

This directory contains target installation scripts, launcher wrappers, systemd service unit files, tmpfiles configuration, and environment defaults that execute natively on the Toradex Verdin i.MX8M Plus running the Toradex Yocto Reference Multimedia Image.

---

## 1. File Inventory and Target Installation Layout

Per CONTRACT section 3, the files in this directory are packaged into the root filesystem at the following paths:

| Repository Source File | Target Filesystem Destination | Permissions | Owner | Purpose |
|---|---|---|---|---|
| `target/bin/hmi-install` | `/usr/bin/hmi-install` | `0755` (`rwxr-xr-x`) | `root:root` | Target-side atomic installer, validator, and self-rollback engine. |
| `target/bin/hmi-gui-launch` | `/usr/bin/hmi-gui-launch` | `0755` (`rwxr-xr-x`) | `root:root` | Wayland environment detection wrapper and GUI loader exec script. |
| `target/systemd/hmi-hwd.service` | `/usr/lib/systemd/system/hmi-hwd.service` | `0644` (`rw-r--r--`) | `root:root` | Systemd service unit managing Layer 1 hardware abstraction daemon (`Type=notify`). |
| `target/systemd/hmi-gui.service` | `/usr/lib/systemd/system/hmi-gui.service` | `0644` (`rw-r--r--`) | `root:root` | Systemd service unit managing Layer 2 GUI loader (`Type=simple`). |
| `target/etc/default/hmi-gui` | `/etc/default/hmi-gui` | `0644` (`rw-r--r--`) | `root:root` | Environment overrides for the GUI launcher (`XDG_RUNTIME_DIR`, `QT_SCALE_FACTOR`, etc.). |
| `target/tmpfiles/hmi.conf` | `/usr/lib/tmpfiles.d/hmi.conf` | `0644` (`rw-r--r--`) | `root:root` | Systemd-tmpfiles rules to create `/run/hmi` and `/tmp/hmi_upload` on tmpfs at boot. |

### Target Runtime Directory Structure

* `/opt/hmi_apps/releases/<id>/`: Persistent directories containing extracted application bundles.
* `/opt/hmi_apps/current`: Symlink pointing to the currently active application release directory.
* `/opt/hmi_apps/previous`: Symlink pointing to the previously active application release directory (for rollback).
* `/tmp/hmi_upload/`: Mode `0700` tmpfs directory where uploaded `.tar.gz` bundles and `.sha256` sidecars land during deployment.
* `/run/hmi/gui-ready`: Sentinel file touched by the GUI loader when QML initialization succeeds.
* `/run/hmi/install.lock`: File lock descriptor used by `flock(2)` to serialize concurrent installations.

---

## 2. Machine-Readable STEP Tag Vocabulary (`hmi-install`)

`hmi-install` emits structured machine-readable progress lines to `stdout` in the format:

```
STEP <tag> <ok|fail> [detail]
```

Host deployment tools (`deploy_to_hmi.sh` and `HMI App Studio`) parse these lines to track progress and detect failure stages. The table below lists the complete set of STEP tags emitted by `target/bin/hmi-install`:

| STEP Tag | Status | Description and Detail Content |
|---|---|---|
| `install-start` | `ok` | Emitted at the start of `cmd_install`. Detail contains `bundle=<path>`. |
| `validate-path` | `ok` / `fail` | Verifies bundle exists, is a regular file (not a symlink), resolves under `UPLOAD_DIR`, and size is $\le 500\text{ MB}$ (`MAX_BUNDLE_SIZE`). |
| `verify-sha256` | `ok` / `fail` | Verifies the computed SHA-256 matches the `<bundle>.sha256` sidecar file. Detail contains the SHA-256 digest on success or mismatch error on failure. |
| `extract` | `ok` / `fail` | Extracts the tarball into staging directory (`/opt/hmi_apps/releases/<release_name>`). Detail contains the staging path. |
| `validate-manifest` | `ok` / `fail` | Validates `manifest.json` schema, required fields (`name`, `version`, `entry`), name format, entry path safety (no `..` or absolute paths), and entry file existence. |
| `save-previous` | `ok` | Atomically points the `previous` symlink to the current active release before the new swap occurs. |
| `swap-symlink` | `ok` / `fail` | Atomically replaces `/opt/hmi_apps/current` using Python `os.replace()` on a temporary symlink (invokes POSIX `rename(2)`). |
| `restart-gui` | `ok` / `fail` | Removes `/run/hmi/gui-ready`, executes `HMI_RESTART_CMD`, and polls for the readiness sentinel up to 25 seconds (`GUI_READY_TIMEOUT`). |
| `auto-rollback-start` | `ok` | Emitted when `restart-gui` fails or times out, immediately prior to restoring the previous release. |
| `rollback` | `ok` / `fail` | Restores `/opt/hmi_apps/current` to point at the target of `/opt/hmi_apps/previous` and restarts the GUI service. |
| `enable-boot` | `ok` / `fail` | Runs `HMI_ENABLE_CMD` (`systemctl enable hmi-gui.service`) so the installed release is the application the panel starts at boot, then confirms the result with `HMI_ENABLE_CHECK_CMD` (`systemctl is-enabled hmi-gui.service`) -- a command that reports success without linking the unit is treated as a failure, and the `ok` detail says `(confirmed)`. Emitted only after readiness has been verified. A `fail` does **not** trigger rollback: the release is installed and running, but will not come back after a power cycle until the unit is enabled by hand. It does set the install's exit status to `4` (see 3.2), so an unattended caller can tell the case apart without parsing this line. |
| `prune` | `ok` | Removes older releases from `/opt/hmi_apps/releases/`, retaining the 3 newest releases plus `current` and `previous`. Detail contains count of pruned releases. |
| `install-complete` | `ok` / `fail` | Terminal step of deployment. Success reports the active release path; failure indicates deployment failed and rolled back. Stays `ok` when only `enable-boot` failed -- the install itself succeeded -- but the detail then reads `deployed and running, autostart NOT configured: <path>` and the exit status is `4`. |
| `rollback-start` | `ok` | Emitted at the start of manual `cmd_rollback`. |
| `rollback-complete` | `ok` / `fail` | Emitted at the conclusion of manual `cmd_rollback`. |
| `list` | `ok` | Emitted at the conclusion of `cmd_list`. |
| `status` | `ok` | Emitted at the conclusion of `cmd_status`. |
| `lock` | `fail` | Emitted if another instance holds `/run/hmi/install.lock` (`flock -n` fails with exit code 3). |
| `usage` | `fail` | Emitted when command-line syntax is invalid (exit code 2). |

---

## 3. Subcommands and Environment Overrides

### 3.1 Subcommand Reference

```bash
/usr/bin/hmi-install <subcommand> [arguments]
```

* **`install <bundle.tar.gz>`**: Executes the complete verification, extraction, atomic swap, GUI restart, watchdog wait, auto-rollback, and release pruning pipeline.
* **`rollback`**: Manually reverts the `/opt/hmi_apps/current` symlink to the target of `/opt/hmi_apps/previous` and restarts the GUI.
* **`list`**: Enumerate all directories under `/opt/hmi_apps/releases/`, annotating which is `[current]` and `[previous]`.
* **`status`**: Displays the resolved paths of `current` and `previous`, and whether the GUI readiness sentinel `/run/hmi/gui-ready` exists.
* **`help`**: Displays command synopsis and exit codes.

### 3.2 Exit Codes

* `0`: Success.
* `1`: General validation or runtime failure (e.g. SHA-256 mismatch, invalid manifest, GUI timeout).
* `2`: Command-line usage or syntax error.
* `3`: Lock contention (`flock` failed because another installation is in progress).
* `4`: Installed, running and verified, but **not** made the boot default — `HMI_ENABLE_CMD` failed. This is not a failed deployment: the release is live and was deliberately *not* rolled back, because replacing a working UI with an older one is worse than the problem. It will not come back after a power cycle until `systemctl enable hmi-gui.service` is run on the panel. Callers that treat any non-zero status as "roll back and page someone" must special-case this one.

### 3.3 Environment Overrides

`hmi-install` and `hmi-gui-launch` support these environment variables, for developer testing and for images whose stock tooling is not sufficient:

| Variable | Default Value | Purpose |
|---|---|---|
| `HMI_ROOT` | *(empty)* | Filesystem path prefix prepended to all paths (`${HMI_ROOT}/opt/hmi_apps`, `${HMI_ROOT}/run/hmi`, etc.). Enables running the installer inside a temporary directory on a dev host. |
| `HMI_RESTART_CMD` | `systemctl restart hmi-gui.service` | Shell command executed to restart the user interface. Can be overridden with a mock command (e.g. `true` or a test script) when systemd is unavailable. |
| `HMI_ENABLE_CMD` | `systemctl enable hmi-gui.service` | Command run after a verified install to make the release the panel's boot default. See the `enable-boot` step. |
| `HMI_ENABLE_CHECK_CMD` | `systemctl is-enabled hmi-gui.service` | Command that confirms `HMI_ENABLE_CMD` took effect. Exit 0 means enabled; anything else is treated as not enabled, whatever the enable command reported. |
| `HMI_SKIP_GUI_WAIT` | `0` | When set to `"1"`, skips executing `HMI_RESTART_CMD`, skips waiting for `/run/hmi/gui-ready`, and skips `HMI_ENABLE_CMD`. |
| `HMI_PYTHON` | *(auto)* | Python interpreter used by both scripts. See below. |

#### Interpreter resolution (`HMI_PYTHON`)

Both scripts need a Python with a **complete standard library**: `hmi-install`
uses `json`, `os`, `re` and `tempfile` for manifest validation and the atomic
symlink swap, and the loader needs far more.

`/usr/bin/python3` is not a safe assumption on Yocto. The stdlib is split into
subpackages there, and a base image can legitimately ship `python3-core` alone —
no `json`, no `logging`, no `socket`, no `ctypes`, no `datetime`. On such an
image every python step in the installer fails, and no Qt application can run at
all. This is not hypothetical: the stock **TDX Wayland** image ships
`python3-core` and `python3-compression` only.

Both scripts therefore resolve an interpreter in this order:

1. `$HMI_PYTHON`, if set and executable.
2. `/opt/hmi-python/bin/python3` — the interpreter installed by provisioning on
   images whose own Python is not usable.
3. `/usr/bin/python3` (`python3` on `PATH` for `hmi-install`).

`hmi-gui-launch` logs which one it chose, and re-resolves after sourcing
`/etc/default/hmi-gui`, so `HMI_PYTHON` can be set there.

### 3.4 Internal Constants

* `MAX_BUNDLE_SIZE`: `524288000` bytes (500 MB). Bundles exceeding this limit are rejected to protect flash storage.
* `GUI_READY_TIMEOUT`: `25` seconds. Maximum time allowed for `/run/hmi/gui-ready` to be touched after GUI restart.
* `KEEP_RELEASES`: `3`. Number of recent releases retained during pruning (in addition to `current` and `previous`).

---

## 4. Testing the Installer on a Development Host

You can test `hmi-install` on Linux, macOS, or WSL without requiring target hardware or root permissions by using a temporary directory and the environment overrides:

```bash
# 1. Create a temporary root filesystem tree
export HMI_ROOT="/tmp/hmi_test_root"
mkdir -p "${HMI_ROOT}/tmp/hmi_upload"
mkdir -p "${HMI_ROOT}/opt/hmi_apps/releases"
mkdir -p "${HMI_ROOT}/run/hmi"

# 2. Package a test bundle
tar -czf "${HMI_ROOT}/tmp/hmi_upload/demo-app-1.0.0.tar.gz" -C apps/demo-app .
sha256sum "${HMI_ROOT}/tmp/hmi_upload/demo-app-1.0.0.tar.gz" | awk '{print $1 "  demo-app-1.0.0.tar.gz"}' > "${HMI_ROOT}/tmp/hmi_upload/demo-app-1.0.0.tar.gz.sha256"

# 3. Execute installation with mock restart
HMI_SKIP_GUI_WAIT=1 HMI_RESTART_CMD="true" ./target/bin/hmi-install install "${HMI_ROOT}/tmp/hmi_upload/demo-app-1.0.0.tar.gz"

# 4. Inspect status and release symlinks
./target/bin/hmi-install status
./target/bin/hmi-install list
ls -la "${HMI_ROOT}/opt/hmi_apps"
```

---

## 5. Hardening with Forced SSH Commands (`authorized_keys`)

To secure the deployment channel on production HMI panels, restrict the deployer's SSH public key so it can **only** execute `hmi-install` and cannot open interactive shells or access arbitrary files.

### 5.1 Security Rationale
`hmi-install` enforces strict path validation (`validate_bundle_path`):
1. Rejects any bundle path whose canonical realpath falls outside `/tmp/hmi_upload`.
2. Rejects symbolic links.
3. Automatically wipes `/tmp/hmi_upload/*` upon installation completion or failure.

### 5.2 `/root/.ssh/authorized_keys` Configuration

Add the deployer public key with the forced command wrapper and privilege restrictions:

```
command="/usr/bin/hmi-install install /tmp/hmi_upload/app.tar.gz",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... deploy-key-production
```

For full pipeline compatibility (allowing SCP uploads followed by SSH execution), use standard key authentication with restricted permissions:
```bash
chmod 700 /root/.ssh
chmod 600 /root/.ssh/authorized_keys
```

---

## 6. Diagnosing Failed Deployments from the Journal

When a deployment fails and triggers an automatic rollback, diagnose the root cause using `journalctl` and `systemctl` on the target:

### 6.1 Inspecting Service Logs
```bash
# View combined logs for the GUI and hardware daemon
journalctl -u hmi-gui -u hmi-hwd -n 100 --no-pager

# Follow logs live during a deployment
journalctl -u hmi-gui -u hmi-hwd -f
```

### 6.2 Common Failure Signatures

1. **QML Syntax or Missing Module Error (`hmi-gui.service`):**
   * *Log symptom:* `QQmlApplicationEngine failed to load component`, `module "Shadcn" is not installed`, or `SyntaxError: Unexpected token`.
   * *Outcome:* GUI loader crashes before creating `/run/hmi/gui-ready`. After 25 seconds, `hmi-install` times out, rolls back `/opt/hmi_apps/current` to the previous release, and restarts the GUI.

2. **Missing Wayland Socket (`hmi-gui-launch`):**
   * *Log symptom:* `[hmi-gui-launch] ERROR: no Wayland socket found under /run/user/*/wayland-* after 30s -- is weston running?`
   * *Remedy:* Check compositor status via `systemctl status weston.service`.

3. **Lock Contention:**
   * *Log symptom:* `[hmi-install] ERROR: another hmi-install is already running (lock: /run/hmi/install.lock)`
   * *Remedy:* Check for hung installer processes with `ps aux | grep hmi-install`.

4. **Checksum Mismatch:**
   * *Log symptom:* `[hmi-install] ERROR: checksum mismatch: expected=... actual=...`
   * *Remedy:* Verify network integrity and ensure the `.sha256` sidecar was uploaded alongside the tarball.

---

## 7. Known Deviations and Implementation Notes

1. **Manifest Name Regex:**
   * *Contract Section 4* specifies `^[a-z0-9][a-z0-9._-]{0,63}$` (lowercase, allows dots).
   * *Code Implementation (`target/bin/hmi-install` line 385):* Python regex checks `^[a-zA-Z0-9][a-zA-Z0-9_-]*$` (allows uppercase, disallows dots).
   * *Deploy CLI (`deploy/deploy_to_hmi.sh` line 52):* Uses `^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$` (lowercase alphanumeric and hyphens).
2. **Staging Directory Path:**
   * *Contract Section 6* states extraction goes to `releases/.stage.$$` before renaming to `releases/<id>`.
   * *Code Implementation (`target/bin/hmi-install` line 308):* Extracts directly to `releases/<release_name>` (derived from tarball name), cleaning up any previous stale directory before extraction.
3. **GUI Loader Path in Launcher Script:**
   * `target/bin/hmi-gui-launch` defaults `GUI_LOADER` to `/usr/lib/hmi/gui/main.py`. When packaging via BitBake (`hmi-gui_1.0.bb`), ensure the installed entrypoint matches or is symlinked.
