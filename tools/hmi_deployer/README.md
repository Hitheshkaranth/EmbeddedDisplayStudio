# Host Deployer GUI (W5)

**Layer:** 3 (Deploy)
**Owner:** W5

This tool is the "Bring Your Own App" (BYOA) HMI system deployer for the Toradex Verdin i.MX8M Plus. 
It provides a commercial-grade desktop experience for engineers to import their Qt application, view a live preview, and deploy it to the target panel.

## Installation

```bash
pip install PySide6
```

## Running the Deployer

```bash
python -m tools.hmi_deployer.app
```

## Pointing to a Panel

1. Go to the "Target Configuration" panel on the right.
2. Enter the device's IP, SSH user (e.g. `root`), and the path to your SSH key (leave blank to use the default ssh-agent).
3. Click **Connect / Test** to verify the SSH connection, systemd services, and disk space.

**Connect / Test** reports two different things about the GUI service, and both
matter: `hmi-gui now:` is whether the panel is showing an app at this moment,
and `hmi-gui boot:` is whether it will still be showing one after the next power
cycle.

## SSH Key Setup

Ensure your SSH keys are set up. We recommend adding your key to your `ssh-agent` or explicitly providing the path to your private key in the "Key" field.

Connections are made with `BatchMode=yes`, so **password authentication is never
attempted** — a panel that only accepts a password (including an empty one) will
fail with `Permission denied (publickey)`. Install your key first:

```bash
ssh-copy-id root@<panel-ip>
```

## What "Deploy to Target" does

One button, six steps. The app is running on the panel, and set to come back on
its own, before the button re-enables:

1. **Package** the bundle to a `.tar.gz` plus a SHA-256 sidecar. Build outputs,
   caches and VCS metadata are excluded automatically; see *Excluding files*.
2. **Upload** both files to `/tmp/hmi_upload`, which is tmpfs — a failed upload
   never touches flash.
3. **Verify and stage** on the target: checksum, extract, re-validate the
   manifest against the same rules the host applied.
4. **Swap** `/opt/hmi_apps/current` onto the new release with a single atomic
   `rename(2)`.
5. **Restart and prove** the UI came up, rolling back automatically if it did
   not.
6. **Make it the boot default** — `hmi-gui.service` is enabled, so the panel
   starts this application on power-on. Reported as `STEP enable-boot`.

Step 6 runs only after step 5 has proven the release renders: only an app that
has been seen to work is worth booting into. If it fails, the deploy still
succeeds — the app is installed and running — but the console says so
explicitly, because that panel will come up blank after the next power cycle.

### Watching a deployment

A progress bar under the button reports real percentage, not a guess:

* **Upload** is exact — the bundle is streamed over SSH and the bar follows
  bytes actually sent, with live throughput. This is also why the upload is
  fast: `scp` prints its meter only to a terminal, so through a pipe it is both
  silent *and* slower than streaming into `cat`.
* **Install** is driven by the installer's own `STEP` lines, so the caption
  names what the panel is really doing — verifying the checksum, switching the
  symlink, waiting for the UI to render — rather than interpolating a timer.

Percentages are weighted by how long each phase takes, not by how many phases
there are: on any real bundle the upload dominates, so it owns most of the bar.

If anything fails the bar turns **red**, stops advancing, and the caption names
the step that broke (`Verifying checksum failed: ...`). A later step cannot
paint over a failure. The panel is safe regardless — the installer rolls itself
back — but the tool says plainly that this attempt did not land.

## Excluding files

The deployer packages the bundle directory, minus anything matching the built-in
excludes (`.git`, `__pycache__`, `build`, `dist`, `node_modules`, `*.egg-info`,
virtualenvs, test and type-checker caches).

Real application folders usually hold more than the application: source
archives, packaged installers, capture logs. List those in a `.hmiignore` file
in the bundle root, one glob per line, `#` for comments:

```
# not part of what runs on the panel
*.zip
release
docs/datasheets
```

A bundle larger than the 500 MB the target accepts is refused **before** the
upload starts, with the largest files named, rather than after a long transfer
the panel then rejects.

## Failed Deployment & Self-Rollback

Deployments are atomic. The tool sends the bundle to a tmpfs location (`/tmp/hmi_upload`), and the target installer extracts, validates, and performs an atomic symlink swap. If the new UI fails to signal readiness within 25 seconds, the target installer automatically rolls back to the previous release and restarts the UI.

## Offline Simulator

If you are not connected to a panel, the deployer will automatically run an offline simulator. This simulator generates plausible, smoothly varying values for the tags your app declares in `tags_required`, allowing you to see your app react in the WYSIWYG preview as if it were running on real hardware.

## Your First App in Five Minutes

1. Click **New App...** in the top bar.
2. Choose a folder where you want to scaffold your project.
3. The tool generates a valid `manifest.json` and a `main.qml` with the mandatory Shadcn kit already imported.
4. The app is automatically loaded in the WYSIWYG preview panel.
5. Click **Deploy to Target** to upload it to the real panel.

---

## Tag Lab

Tag Lab is the signal injection tool built into the deployer.  It lets you drive
any tag your app declares with a deterministic waveform, pin a sensor to a
constant, or replay a complex multi-tag scenario — all without physical hardware.

### Opening Tag Lab

Switch to the **Tag Lab** tab in the right-hand panel.  If a bundle is already
loaded, its `tags_required` tags are pre-populated.

### Available Waveforms

| Kind | Description | Key Parameters |
|------|-------------|----------------|
| **Constant** | Fixed value (pin / override mode) | `value` |
| **Sine** | Sinusoidal oscillation | `amplitude`, `period` (s), `offset` |
| **Square** | Pulse / square wave | `high`, `low`, `period` (s), `duty` (0–1] |
| **Ramp** | Linear sawtooth | `low`, `high`, `period` (s) |
| **Noise** | Uniform white noise | `amplitude`, `mean` |

All period and frequency values are validated to be finite and positive.  Infinite
or NaN inputs are rejected immediately.

### Using Tag Lab

1. Open a bundle (the bundle's `tags_required` tags are bound automatically).
2. Optionally click **Add Tag…** to inject tags not in the manifest.
   *These are marked "Unknown" and start disabled; they must be explicitly enabled.*
3. Click **Edit** on any row to choose a waveform and set its parameters.
4. Click **Start Sending** to begin UDP injection on port 5001 (TagEngine's default).
   The simulator and any live relay are stopped automatically — only one source
   drives TagEngine at a time.
5. Click **Stop** to halt injection.  The offline simulator restarts automatically.

### Mutual Exclusion

Tag Lab Sender, the offline Simulator, and the live SSH Relay are mutually exclusive.
Starting any one of them stops the others.  This ensures TagEngine always receives a
coherent single stream of telemetry frames.

### Saving and Loading Scenarios

Click **Save Scenario…** / **Load Scenario…** to persist and restore the full tag
configuration as a JSON file (schema version 1).  Scenario files are written
atomically (write-to-temp + rename) and survive process crashes.

```json
{
  "schema": 1,
  "entries": [
    {
      "tag": "ai.pot",
      "enabled": true,
      "known": true,
      "waveform": { "kind": "sine", "amplitude": 1.5, "period": 2.0, "offset": 0.5 }
    }
  ]
}
```

### Running Tag Lab Tests

```bash
# Focused Tag Lab tests only
python -m pytest tests/test_taglab.py -v

# Full suite
python tests/run_all.py
```
