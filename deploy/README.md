# Host Deployment CLI (deploy_to_hmi.sh)

Layer 3 host-side command-line deployment tool for the BYOA HMI system.

`deploy/deploy_to_hmi.sh` automates the validation, packaging, cryptographic verification, transport, installation, verification, and monitoring of Qt/QML application bundles targeted at a Toradex Verdin i.MX8M Plus panel.

---

## 1. Usage Synopsis

```bash
deploy_to_hmi.sh [ACTION] -H HOST [OPTIONS] [-b BUNDLE]
```

### 1.1 Supported Actions

| Action | Description |
|---|---|
| `deploy` *(default)* | Client-side validation, deterministic tarball packaging, SHA-256 sidecar generation, upload over SSH/SCP, execution of `hmi-install`, and live progress monitoring. |
| `rollback` | Instructs the target to revert `/opt/hmi_apps/current` to the previous release generation and restart the GUI. |
| `list` | Lists all installed application release directories on the target, marking `[current]` and `[previous]`. |
| `status` | Displays the current and previous release paths and the live GUI readiness status (`ready` / `not ready`). |
| `logs` | Tails `journalctl` entries for both `hmi-gui` and `hmi-hwd` units live over SSH (`Ctrl-C` exits cleanly). |
| `check` | Verifies target readiness (TCP reachability, SSH login, `hmi-install` presence, and systemd units) without deploying anything. |

---

## 2. Options and Command-Line Flags

### 2.1 Connection Flags (Required for Network Actions)

* **`-H, --host HOST`**: Target hostname or IPv4/IPv6 address (e.g. `-H 192.168.1.50`). Mandatory for all network actions.
* **`-u, --user USER`**: SSH login username (default: `root`).
* **`-p, --port PORT`**: SSH port number, valid range: `1` to `65535` (default: `22`).
* **`-i, --identity FILE`**: Path to the private SSH key file (e.g. `-i ~/.ssh/id_ed25519`).
* **`--insecure`**: Disables `StrictHostKeyChecking` and redirects known hosts to a temporary throwaway file for the duration of the run.
  > [!WARNING]
  > Use `--insecure` only on isolated laboratory networks. It disables host-key verification and exposes the deployment session to Man-in-the-Middle (MITM) attacks.

### 2.2 Bundle Flags (Used with `deploy`)

* **`-b, --bundle PATH`**: Path to the application bundle. Accepts either a directory containing `manifest.json` or a pre-packaged `.tar.gz` archive.
* **`--name NAME`**: Overrides the `name` attribute declared in `manifest.json` during packaging and directory creation.
* **`--no-restart`**: Passed to `hmi-install` to skip restarting `hmi-gui.service` after a successful install.
* **`--keep N`**: Passed to `hmi-install` to retain the `N` newest release generations (default: 3), pruning older unreferenced releases.

### 2.3 General Flags

* **`--dry-run`**: Prints every local and remote command (SSH, SCP, tar, sha256) that would be executed without modifying local files or target state.
* **`-v, --verbose`**: Enables debug output (`[DBG]`), logs SSH command strings, and displays raw remote stdout streams.
* **`-h, --help`**: Displays command synopsis and exits.

### 2.4 SSH ControlMaster Connection Multiplexing

To prevent repetitive password prompts and reduce connection latency during deployment, `deploy_to_hmi.sh` establishes an OpenSSH `ControlMaster` connection:

```bash
-o ControlMaster=auto -o ControlPath=${TMPWORK}/ssh_ctl.sock -o ControlPersist=60s -o ConnectTimeout=15
```

1. The initial connection (`open_master_connection`) authenticates the user once and maintains a multiplexed Unix domain socket.
2. All subsequent `ssh` and `scp` commands reuse the open socket.
3. Upon script completion or termination (via `trap cleanup EXIT INT TERM HUP`), the master socket sends an exit command (`ssh -O exit`) and cleans up the temporary socket file.

---

## 3. Worked Examples

### 3.1 First Deployment to a New Panel
Validate and deploy an application directory directly from the development repository:

```bash
./deploy/deploy_to_hmi.sh -H 192.168.1.50 -b ./apps/demo-app
```

### 3.2 Iterate and Redeploy with Release Retention
Redeploy modified code, retain only the 3 most recent releases, and specify an SSH private key:

```bash
./deploy/deploy_to_hmi.sh -H 192.168.1.50 -i ~/.ssh/id_ed25519 -b ./apps/demo-app --keep 3
```

### 3.3 Verify Target Readiness
Run pre-flight checks before scheduling automated deployments:

```bash
./deploy/deploy_to_hmi.sh check -H 192.168.1.50
```

*Output:*
```
==> Checking target readiness: 192.168.1.50:22
  [PASS] TCP port 22 reachable
  [PASS] SSH login as root
  [PASS] hmi-install at /usr/bin/hmi-install
  [PASS] hmi-gui.service unit
  [PASS] hmi-hwd.service unit
[OK] Target is ready for deployment.
```

### 3.4 Emergency Rollback
Immediately revert the panel to the previous working release:

```bash
./deploy/deploy_to_hmi.sh rollback -H 192.168.1.50
```

### 3.5 Live Log Inspection
Monitor GUI rendering and hardware tag updates in real time:

```bash
./deploy/deploy_to_hmi.sh logs -H 192.168.1.50
```

---

## 4. SSH Key Authentication Setup

For passwordless, secure deployments from CI servers or developer workstations:

1. **Generate an Ed25519 SSH Key Pair:**
   ```bash
   ssh-keygen -t ed25519 -C "hmi-deployer" -f ~/.ssh/hmi_deploy_key
   ```

2. **Copy the Public Key to the Target Panel:**
   ```bash
   ssh-copy-id -i ~/.ssh/hmi_deploy_key.pub root@192.168.1.50
   ```

3. **Verify File Permissions on Target:**
   ```bash
   ssh root@192.168.1.50 "chmod 700 /root/.ssh && chmod 600 /root/.ssh/authorized_keys"
   ```

4. **Deploy using the Identity File:**
   ```bash
   ./deploy/deploy_to_hmi.sh -H 192.168.1.50 -i ~/.ssh/hmi_deploy_key -b ./apps/demo-app
   ```

---

## 5. Atomic Deployments and Self-Rollback Mechanism

In industrial HMI panels, a failed software update must **never leave the screen blank, non-responsive, or showing a terminal**. The deployment pipeline guarantees safety through strict atomic operations:

```
[Host System]                                  [Target System]
1. Validate manifest & bundle local
2. Deterministic tar + SHA-256
3. SCP tarball & .sha256 sidecar -----------> /tmp/hmi_upload (tmpfs)
                                               4. flock(/run/hmi/install.lock)
                                               5. Verify SHA-256 sidecar
                                               6. Extract to releases/<name>-<ver>
                                               7. Validate manifest on target
                                               8. Update 'previous' symlink
                                               9. Atomic rename(2) -> 'current'
                                              10. rm /run/hmi/gui-ready
                                              11. systemctl restart hmi-gui.service
                                              12. Poll /run/hmi/gui-ready (<=25s)
                                                    |
                       +----------------------------+----------------------------+
                       | (Success)                                               | (Failure / Timeout)
                       v                                                         v
             Wipe /tmp/hmi_upload                                      Restore 'previous' symlink
             Prune old releases                                        Restart hmi-gui.service
             Exit 0                                                    Wipe /tmp/hmi_upload
                                                                       Exit 1 (Non-zero)
```

### Why the Panel Never Shows a Broken UI:
1. **Tmpfs Landing Zone (`/tmp/hmi_upload`):** Bundles are written to RAM disk. Network disconnects or partial uploads never write incomplete data to persistent flash.
2. **Deterministic Validation:** `manifest.json` is validated twice: once on the host before upload, and once on the target before the symlink is modified.
3. **Atomic Symlink Swap (`os.replace` / `rename(2)`):** The script never executes `rm current && ln -s ...` (which leaves a window where no UI exists). Instead, a temporary symlink (`.current_swap_XXXX`) is created and atomically swapped over `/opt/hmi_apps/current` using POSIX `rename(2)`.
4. **Health Check & Self-Rollback:** After restarting `hmi-gui.service`, `hmi-install` monitors `/run/hmi/gui-ready` for up to 25 seconds. If the application crashes on boot, throws a QML error, or fails to render, `hmi-install` automatically swaps the symlink back to `/opt/hmi_apps/previous`, restarts the GUI with the known-good release, and exits with code 1.

---

## 6. Troubleshooting Guide

| Symptom / Error | Root Cause | Resolution |
|---|---|---|
| `Cannot connect to <HOST>:22 as root` | Target is offline, network cable disconnected, or SSH service is not running. | Verify target power and IP address. Ensure `ssh-server-openssh` is installed and running on the target. |
| `manifest.json not found in bundle` | Bundle path does not contain a valid `manifest.json` at the archive root. | Ensure `manifest.json` sits at the top level of the bundle directory, not in a subdirectory. |
| `checksum mismatch: expected=... actual=...` | Corrupted upload or modified tarball during transport. | Check network stability. Run `deploy_to_hmi.sh` again to re-upload. |
| `another hmi-install is already running` | Stale or concurrent installation holding `/run/hmi/install.lock`. | Check running processes on the target (`ps aux \| grep hmi-install`). The lock automatically releases when the process terminates. |
| `GUI did not become ready within 25s` | Customer QML application threw a syntax error or missing component exception at startup. | Run `deploy_to_hmi.sh logs -H <HOST>` to inspect QML engine error logs. Correct QML errors in your app. |
| `bundle too large: ... bytes (max 524288000)` | Bundle exceeds 500 MB limit. | Remove unnecessary assets, videos, or build artifacts from the bundle folder before packaging. |
| `Permission denied (publickey)` | SSH key not authorized on target. | Install the public key using `ssh-copy-id` or specify the correct key with `-i <keyfile>`. |

---

## 7. Known Deviations and Implementation Notes

1. **Progress Output Formatting:**
   * `deploy/deploy_to_hmi.sh` (line 913) includes a progress parser expecting `^STEP [0-9]+/[0-9]+ <desc>` lines.
   * `target/bin/hmi-install` emits named tags in the format `STEP <tag> <ok|fail> [detail]`.
   * *Behavior:* Non-matching STEP lines fall through safely to the default output handler and are printed verbatim to standard output.
