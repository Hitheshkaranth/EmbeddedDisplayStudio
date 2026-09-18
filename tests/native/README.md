# Conformance Test Suite

Black-box loader conformance suite that drives any HMI GUI loader
(Python or native binary) through the probe bundle and asserts
identical observable behaviour.

**Environment:** `HMI_GUI_CMD` — unset uses the Python loader; set
to the native binary path to test the native loader.

**Run against the Python loader (Windows, repo root):**
```
python -m unittest discover -s tests/native -t . -v
```

**Run against the native binary (WSL):**
```
wsl -d Ubuntu -u root -- bash -c "cd /mnt/c/Users/hithe/Documents/MIL-HMI-PROJ/swarm/<WORKTREE> && HMI_GUI_CMD=native/hmi-gui/out/hmi-gui QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests/native -t . -v"
```