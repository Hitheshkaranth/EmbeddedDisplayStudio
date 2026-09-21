#!/usr/bin/env bash
# native/hmi-gui/arm64/runtime.sh -- package the private Qt 6 runtime for the panel.
#
# Collects, from the bookworm arm64 root (chroot.sh), everything the native
# loader loads at run time -- the Qt 6 libraries, the wayland platform plugin
# and its shell integrations, the QML modules the shell/kit/bundles import,
# and the non-Qt shared libraries in their dependency closure -- into one
# tarball rooted at usr/lib/hmi/qt6/{lib,plugins,qml}. deploy/provision_native.sh
# unpacks it on the panel and installs a launcher wrapper that points
# LD_LIBRARY_PATH / QT_PLUGIN_PATH / QML_IMPORT_PATH at it.
#
# Deliberately NOT shipped (the panel's own are newer and must win): the glibc
# family, libstdc++/libgcc, and the GL/EGL/wayland client libraries (glvnd's
# libGL/libGLX/libGLdispatch are already installed for PySide6; the loader
# runs the software scene graph anyway, so no GL call is ever made). glvnd's
# libOpenGL.so.0 IS shipped: the panel lacks it and it is only a dispatch
# stub over libGLdispatch.
#
# USAGE (WSL Ubuntu, as root; after build.sh)
#   bash native/hmi-gui/arm64/runtime.sh [OUT.tar.gz]
#   default OUT = native/hmi-gui/out/aarch64/hmi-qt6-runtime.tar.gz
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${HMI_ARM64_ROOT:-/srv/hmi-arm64}"
OUT="${1:-$SRC/out/aarch64/hmi-qt6-runtime.tar.gz}"
BIN="$SRC/out/aarch64/hmi-gui"
LIBDIR="usr/lib/aarch64-linux-gnu"
QTBASE="$LIBDIR/qt6"

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 2; }
[ -x "$BIN" ] || { echo "no aarch64 binary at $BIN; run arm64/build.sh" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
P="$STAGE/usr/lib/hmi/qt6"
mkdir -p "$P/lib" "$P/plugins" "$P/qml"

# 1. Plugins and QML modules. Only the wayland platform (what the panel
#    runs) and offscreen (so tests/native can run on the panel itself);
#    xcb/eglfs/linuxfb would drag X11, libinput and udev into the closure.
mkdir -p "$P/plugins/platforms"
for f in libqwayland-generic.so libqoffscreen.so libqminimal.so; do
    cp -a "$ROOT/$QTBASE/plugins/platforms/$f" "$P/plugins/platforms/"
done
for d in wayland-shell-integration wayland-decoration-client imageformats iconengines tls networkinformation; do
    [ -d "$ROOT/$QTBASE/plugins/$d" ] && cp -a "$ROOT/$QTBASE/plugins/$d" "$P/plugins/"
done
for m in QtQml QtQuick; do
    cp -a "$ROOT/$QTBASE/qml/$m" "$P/qml/"
done
# All Controls styles stay: Qt picks Fusion by default on Linux and a bundle
# that imports QtQuick.Controls fails to load when that style is missing.

# 2. Shared-library closure of the binary, the plugins and the QML modules,
#    resolved inside the root (ldd there sees the arm64 libraries).
NEEDED="$STAGE/needed.txt"
{
    echo "/work-bin/hmi-gui"
    find "$P" -name '*.so*' -type f | sed "s|^$STAGE/usr/lib/hmi/qt6|/hmi-qt6|"
} > "$STAGE/roots.txt"
mkdir -p "$ROOT/work-bin" "$ROOT/hmi-qt6"
cp "$BIN" "$ROOT/work-bin/hmi-gui"
mount --bind "$P" "$ROOT/hmi-qt6"
cleanup() { umount "$ROOT/hmi-qt6" 2>/dev/null || true; rm -rf "$ROOT/work-bin" "$ROOT/hmi-qt6"; rm -rf "$STAGE"; }
trap cleanup EXIT
chroot "$ROOT" /bin/bash -c '
    export LD_LIBRARY_PATH=/hmi-qt6/lib
    while read -r f; do ldd "$f" 2>/dev/null | awk "/=> \\// {print \$3}"; done
' < "$STAGE/roots.txt" | sort -u > "$NEEDED"

# 3. Copy the closure, minus what must come from the panel itself.
SKIP='^(libc|libm|libdl|libpthread|librt|libresolv|libutil|ld-linux|libstdc\+\+|libgcc_s|libGL|libGLX|libEGL|libGLdispatch|libwayland-client|libwayland-egl|libwayland-cursor|libxkbcommon)([.-]|$)'
while read -r lib; do
    base="$(basename "$lib")"
    if echo "$base" | grep -Eq "$SKIP"; then continue; fi
    case "$lib" in /hmi-qt6/*) continue ;; esac      # already staged
    real="$(chroot "$ROOT" readlink -f "$lib")"
    cp -L "$ROOT$real" "$P/lib/$(basename "$real")"
    [ "$base" != "$(basename "$real")" ] && ln -sf "$(basename "$real")" "$P/lib/$base"
done < "$NEEDED"
# Qt's own libraries come via the closure too; make sure every libQt6*.so.6
# soname symlink exists (ldd resolves to the versioned file).
for f in "$P"/lib/libQt6*.so.6.*; do
    so="${f%%.so.*}.so.6"
    [ -e "$so" ] || ln -s "$(basename "$f")" "$so"
done

echo "== runtime contents"
du -sh "$P/lib" "$P/plugins" "$P/qml" | sed 's/^/  /'
ls "$P/lib" | grep -c '\.so' | sed 's/^/  libraries: /'

mkdir -p "$(dirname "$OUT")"
tar -C "$STAGE" -czf "$OUT" usr/lib/hmi/qt6
ls -la "$OUT"
