#!/usr/bin/env bash
# native/hmi-gui/arm64/build.sh -- build hmi-gui for the panel (aarch64).
#
# Runs cmake + ninja *inside* the bookworm arm64 root made by chroot.sh, under
# qemu-user, so no cross toolchain or host Qt is involved. The checkout is
# bind-mounted into the root at /work; the build directory stays on the
# root's own filesystem (compiling on /mnt/c is an order of magnitude
# slower). Output: native/hmi-gui/out/aarch64/hmi-gui, plus tests/ when
# --test is given (the QTest suite is then also run under qemu, offscreen --
# slow, but it proves the faces on the target architecture and Qt 6.4).
#
# USAGE (WSL Ubuntu, as root)
#   bash native/hmi-gui/arm64/build.sh [--test] [--clean]
#   HMI_ARM64_ROOT=/srv/hmi-arm64 (default)
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"          # native/hmi-gui
REPO="$(cd "$SRC/../.." && pwd)"
ROOT="${HMI_ARM64_ROOT:-/srv/hmi-arm64}"
RUN_TESTS=0
CLEAN=0
for arg in "$@"; do
    case "$arg" in
        --test)  RUN_TESTS=1 ;;
        --clean) CLEAN=1 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
[ -x "$ROOT/usr/bin/g++" ] || { echo "no build root at $ROOT; run arm64/chroot.sh" >&2; exit 1; }

# One build dir per checkout, keyed like build.sh does.
BUILD_NAME="$(echo "$REPO" | tr '/ ' '__')"
BUILD_IN_ROOT="/build/$BUILD_NAME"
[ "$CLEAN" = 1 ] && rm -rf "$ROOT$BUILD_IN_ROOT"
mkdir -p "$ROOT$BUILD_IN_ROOT" "$ROOT/work"

cleanup() { umount "$ROOT/work" 2>/dev/null || true; }
trap cleanup EXIT
mountpoint -q "$ROOT/work" || mount --bind "$REPO" "$ROOT/work"

# Everything below runs as aarch64 code under qemu.
chroot "$ROOT" /bin/bash -e <<EOF
export QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software
cmake -S /work/native/hmi-gui -B "$BUILD_IN_ROOT" -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$BUILD_IN_ROOT" --parallel
if [ "$RUN_TESTS" = 1 ]; then
    (cd "$BUILD_IN_ROOT" && ctest --output-on-failure --timeout 1800)
fi
EOF

mkdir -p "$SRC/out/aarch64"
cp "$ROOT$BUILD_IN_ROOT/hmi-gui" "$SRC/out/aarch64/hmi-gui"
file "$SRC/out/aarch64/hmi-gui" | sed 's/^/built: /'
