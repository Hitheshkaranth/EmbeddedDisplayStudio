#!/usr/bin/env bash
# native/hmi-ui/arm64/build.sh -- build hmi-ui for the panel inside the
# bookworm arm64 root (native/hmi-gui/arm64/chroot.sh makes it). Output:
# native/hmi-ui/out/aarch64/. Installs libdrm-dev into the root on first use.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$SRC/../.." && pwd)"
ROOT="${HMI_ARM64_ROOT:-/srv/hmi-arm64}"
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
[ -x "$ROOT/usr/bin/gcc" ] || { echo "no build root at $ROOT; run native/hmi-gui/arm64/chroot.sh" >&2; exit 1; }
if ! chroot "$ROOT" dpkg -s libdrm-dev >/dev/null 2>&1; then
    # The apt-variant root has no CA bundle; the mirror is HTTPS.
    mkdir -p "$ROOT/etc/ssl/certs"
    cp /etc/ssl/certs/ca-certificates.crt "$ROOT/etc/ssl/certs/ca-certificates.crt"
    chroot "$ROOT" bash -c "apt-get update -qq && apt-get install -y -qq libdrm-dev pkg-config" >/dev/null
fi
BUILD_IN_ROOT="/build/hmi-ui-$(echo "$REPO" | tr '/ ' '__')"
mkdir -p "$ROOT$BUILD_IN_ROOT" "$ROOT/work"
cleanup() { umount "$ROOT/work" 2>/dev/null || true; }
trap cleanup EXIT
mountpoint -q "$ROOT/work" || mount --bind "$REPO" "$ROOT/work"
chroot "$ROOT" cmake -S /work/native/hmi-ui -B "$BUILD_IN_ROOT" -G Ninja -DCMAKE_BUILD_TYPE=Release >/dev/null
chroot "$ROOT" cmake --build "$BUILD_IN_ROOT" --parallel
mkdir -p "$SRC/out/aarch64"
for b in "$ROOT$BUILD_IN_ROOT"/hmi-ui*; do
    [ -f "$b" ] && [ -x "$b" ] && cp "$b" "$SRC/out/aarch64/"
done
file "$SRC"/out/aarch64/hmi-ui* | sed 's/^/built: /'
