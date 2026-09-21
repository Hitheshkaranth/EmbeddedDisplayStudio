#!/usr/bin/env bash
# native/hmi-gui/arm64/chroot.sh -- create the aarch64 build root for hmi-gui.
#
# WHY A CHROOT AND NOT A CROSS TOOLCHAIN
#   The panel (Verdin i.MX8M Plus, Toradex scarthgap image, glibc 2.39) has no
#   Qt 6 of its own and no package feed. Cross-compiling Qt code needs a host
#   Qt of exactly the target's version for moc/qmlcachegen (QT_HOST_PATH),
#   which no distribution gives us for an arbitrary pair. Building natively
#   inside a Debian bookworm arm64 root under qemu-user removes the problem:
#   bookworm's Qt 6.4.2 is the oldest version CMakeLists.txt accepts, it is
#   built against glibc 2.36 (older than the panel's, the direction that
#   works), and the same root is the source of the private runtime that
#   deploy/provision_native.sh ships to /usr/lib/hmi/qt6. This is the Qt 6
#   counterpart of deploy/provision_pyside2.sh.
#
# USAGE (WSL Ubuntu, as root; one-time, ~10 min, ~1.5 GB)
#   bash native/hmi-gui/arm64/chroot.sh [ROOT]        default ROOT=/srv/hmi-arm64
#
# The root is then used by build.sh (compile) and runtime.sh (package).
set -euo pipefail

ROOT="${1:-/srv/hmi-arm64}"
SUITE="bookworm"
MIRROR="https://deb.debian.org/debian"

# Everything the loader links or loads at runtime, plus the toolchain.
# qml6-module-* are what the shell, the Shadcn kit and generated bundles
# import (QtQuick, Window, Layouts, Shapes, Controls/Basic, Templates).
PACKAGES=(
    build-essential cmake ninja-build pkg-config
    qt6-base-dev qt6-base-dev-tools qt6-declarative-dev qt6-declarative-dev-tools
    libqt6test6 qt6-wayland libqt6svg6
    qml6-module-qtqml qml6-module-qtqml-workerscript
    qml6-module-qtquick qml6-module-qtquick-window qml6-module-qtquick-layouts
    qml6-module-qtquick-shapes qml6-module-qtquick-controls
    qml6-module-qtquick-templates
    python3
)

if [ "$(id -u)" != 0 ]; then
    echo "run as root (wsl -d Ubuntu -u root)" >&2
    exit 2
fi

echo "== host tools"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq mmdebstrap qemu-user qemu-user-binfmt debian-archive-keyring >/dev/null
if [ ! -e /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    update-binfmts --enable qemu-aarch64 || true
fi
test -e /proc/sys/fs/binfmt_misc/qemu-aarch64 || { echo "qemu-aarch64 binfmt not registered" >&2; exit 1; }

if [ -x "$ROOT/usr/bin/g++" ] && [ -d "$ROOT/usr/lib/aarch64-linux-gnu/cmake/Qt6" ]; then
    echo "== $ROOT already provisioned"
    exit 0
fi

echo "== creating $ROOT ($SUITE arm64)"
IFS=, eval 'INCLUDE="${PACKAGES[*]}"'
rm -rf "$ROOT"
mmdebstrap --architectures=arm64 --variant=apt --mode=root \
    --keyring=/usr/share/keyrings/debian-archive-keyring.gpg \
    --include="$INCLUDE" \
    "$SUITE" "$ROOT" "$MIRROR"

echo "== sanity"
chroot "$ROOT" /usr/bin/g++ --version | head -1
chroot "$ROOT" /usr/bin/qmake6 -query QT_VERSION
echo "ready: $ROOT"
