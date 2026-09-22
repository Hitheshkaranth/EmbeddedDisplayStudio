#!/usr/bin/env bash
# native/hmi-ui/win64/build.sh -- cross-compile the headless preview binary for Windows.
#
# FROZEN CONTRACT (native previews swarm, 2026-09-22). Owner: W1 fills this
# in. Run from WSL Ubuntu as root:
#
#   bash native/hmi-ui/win64/build.sh            -> native/hmi-ui/out/win64/hmi-ui.exe
#
# Requirements it installs when missing: mingw-w64 (x86_64-w64-mingw32-gcc),
# cmake, ninja. The binary is the Studio's preview renderer on Windows: it
# links only libc/kernel32/ws2_32, is built with -DHMI_UI_WITH_DRM=OFF (no
# libdrm, no evdev) and supports exactly the headless CLI:
#   hmi-ui.exe --render-widget TYPE --headless OUT.png [--size WxH] [--props JSON] [--kit DIR] [--theme dark|light]
#   hmi-ui.exe --apps-dir DIR --headless OUT.png [--kit DIR] [--theme dark|light]
# --display is refused on this build with a clear message.
#
# win64/check.sh (frozen) is the gate: it builds, renders through WSL's
# Windows interop, and compares against the Linux renders.
set -euo pipefail
echo "TODO(W1): implement" >&2
exit 1
