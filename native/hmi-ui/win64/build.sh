#!/usr/bin/env bash
# native/hmi-ui/win64/build.sh -- cross-compile the headless preview binary for Windows.
#
# Run from WSL Ubuntu as root:
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
# win64/check.sh is the gate: it builds, renders through WSL's
# Windows interop, and compares against the Linux renders.
#
#   build.sh --clean     wipe the build directory first
# Build dir: $HMI_UI_BUILD_DIR_WIN64 or /root/.cache/hmi-ui-build-win64/<path-derived>
# (off /mnt/c for speed; one per checkout, like build.sh).
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${HMI_UI_BUILD_DIR_WIN64:-/root/.cache/hmi-ui-build-win64/$(echo "$SRC" | tr '/ ' '__')}"
for arg in "$@"; do
    case "$arg" in
        --clean) rm -rf "$BUILD" ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

missing=()
command -v x86_64-w64-mingw32-gcc >/dev/null || missing+=(mingw-w64)
command -v cmake >/dev/null || missing+=(cmake)
command -v ninja >/dev/null || missing+=(ninja-build)
if [ "${#missing[@]}" -gt 0 ]; then
    echo "installing: ${missing[*]}" >&2
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" >/dev/null
fi
[ -d "$SRC/lvgl/src" ] || { echo "lvgl submodule is empty: git submodule update --init native/hmi-ui/lvgl" >&2; exit 1; }

mkdir -p "$BUILD"
TOOLCHAIN="$BUILD/mingw-w64.cmake"
# -static: no libgcc/libwinpthread DLL next to the exe. __USE_MINGW_ANSI_STDIO
# routes printf through mingw's C99 implementation instead of msvcrt's, so
# "%g"/"%.1f" (widget readouts) format exactly as glibc does: the renders
# are compared pixel for pixel with the Linux ones. (gcc's -Wformat still
# checks against msvcrt's rules, so it warns about "%zu"; the output is right.)
cat > "$TOOLCHAIN" <<'EOF'
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR x86_64)
set(CMAKE_C_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_CXX_COMPILER x86_64-w64-mingw32-g++)
set(CMAKE_ASM_COMPILER x86_64-w64-mingw32-gcc)
set(CMAKE_RC_COMPILER x86_64-w64-mingw32-windres)
set(CMAKE_FIND_ROOT_PATH /usr/x86_64-w64-mingw32)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_C_FLAGS_INIT "-D__USE_MINGW_ANSI_STDIO=1")
set(CMAKE_EXE_LINKER_FLAGS_INIT "-static -static-libgcc")
EOF

cmake -S "$SRC" -B "$BUILD" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN" \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DHMI_UI_WITH_DRM=OFF >/dev/null
cmake --build "$BUILD" --parallel --target hmi-ui
mkdir -p "$SRC/out/win64"
cp "$BUILD/hmi-ui.exe" "$SRC/out/win64/hmi-ui.exe"
echo "built: $SRC/out/win64/hmi-ui.exe"
