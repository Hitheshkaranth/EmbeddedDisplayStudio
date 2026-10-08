#!/usr/bin/env bash
# native/hmi-hwd/arm64/build.sh -- build hmi-hwd for the panel inside the
# bookworm arm64 root (native/hmi-gui/arm64/chroot.sh makes it). Output:
# native/hmi-hwd/out/aarch64/hmi-hwd. Installs libsqlite3-dev into the root
# on first use.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$SRC/../.." && pwd)"
ROOT="${HMI_ARM64_ROOT:-/srv/hmi-arm64}"
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
[ -x "$ROOT/usr/bin/gcc" ] || { echo "no build root at $ROOT; run native/hmi-gui/arm64/chroot.sh" >&2; exit 1; }
if ! chroot "$ROOT" dpkg -s libsqlite3-dev >/dev/null 2>&1; then
    mkdir -p "$ROOT/etc/ssl/certs"
    cp /etc/ssl/certs/ca-certificates.crt "$ROOT/etc/ssl/certs/ca-certificates.crt"
    chroot "$ROOT" bash -c "apt-get update -qq && apt-get install -y -qq libsqlite3-dev pkg-config" >/dev/null
fi
BUILD_IN_ROOT="/build/hmi-hwd-$(echo "$REPO" | tr '/ ' '__')"
mkdir -p "$ROOT$BUILD_IN_ROOT" "$ROOT/work"
cleanup() { umount "$ROOT/work" 2>/dev/null || true; }
trap cleanup EXIT
mountpoint -q "$ROOT/work" || mount --bind "$REPO" "$ROOT/work"
chroot "$ROOT" cmake -S /work/native/hmi-hwd -B "$BUILD_IN_ROOT" -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null
chroot "$ROOT" cmake --build "$BUILD_IN_ROOT" --parallel --target hmi-hwd
mkdir -p "$SRC/out/aarch64"
cp "$ROOT$BUILD_IN_ROOT/hmi-hwd" "$SRC/out/aarch64/"
file "$SRC/out/aarch64/hmi-hwd" | sed 's/^/built: /'
