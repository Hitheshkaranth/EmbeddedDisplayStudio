# BYOA HMI Test Suite

This directory contains the automated integration and regression tests for the BYOA HMI project, validating the system against `CONTRACT.md`.

## How to run the suite

To execute all tests (including any tests in `ui/tests/`):

```bash
python tests/run_all.py
```

The script discovers tests automatically, runs them, prints a summary table indicating modules, failures, and skipped tests with their reasons, and exits non-zero if any test failed.

## Module Coverage & Requirements

- `test_daemon_protocol.py`: Starts the hardware daemon (`hmi_hwd.py`) as a subprocess using its simulation mode (`--sim`). It verifies the UDP wire protocol (CONTRACT 2), testing acknowledgements, malformed JSON handling, missing tags, and telemetry frames. It requires `python3` to execute the subprocess.
- `test_tagengine_integration.py`: Tests the end-to-end telemetry path. It starts the simulated hardware daemon, constructs the `TagEngine` from the GUI layer, exposes it to a `QQmlApplicationEngine`, and loads a real QML component from disk to assert that variables bind and update correctly. It requires `PySide6` and runs the UI in offscreen mode.
- `test_bundle_validation.py`: Verifies that all three implementations of the bundle validator (`deployer.py`, `deploy_to_hmi.sh`, and `hmi-install`) agree on valid and invalid app bundles (missing manifest, malformed JSON, etc.). It requires `bash` and `flock` to exercise the shell scripts; otherwise, those specific checks are gracefully skipped.

## Important Note on Windows / WSL

The atomic swap and rollback functionality of the installer (`hmi-install`) **cannot** be effectively exercised directly on Windows. This is due to several environmental differences:
- Lack of a native `flock` command for locking.
- Python 3 is often named `python` instead of `python3`.
- MSYS/MinGW path translation corrupts absolute Unix paths.
- Creating symlinks requires elevated privileges on Windows.

To run the full deployment pipeline and test the atomic swap, you must run it on Linux or via WSL (Windows Subsystem for Linux).

### Running under WSL

Open your WSL terminal and execute:

```bash
cd /mnt/c/Users/hithe/Documents/MIL-HMI-PROJ/EmbeddedDisplay
python3 tests/run_all.py
```
