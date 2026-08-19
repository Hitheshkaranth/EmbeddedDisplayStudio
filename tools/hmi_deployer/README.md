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

## SSH Key Setup

Ensure your SSH keys are set up. We recommend adding your key to your `ssh-agent` or explicitly providing the path to your private key in the "Key" field.

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
