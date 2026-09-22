#!/usr/bin/env bash
# deploy/provision_native.sh -- install the native hmi-gui loader on a panel.
#
# LEGACY. The platform GUI is now native/hmi-ui (Qt-free), installed by
# deploy/provision_panel.py, which removes what this script installs. Keep
# this only for a panel that must run an existing Qt bundle (runtime qml/
# python); its unit and launcher live under native/hmi-gui/target/.
#
# WHY THIS EXISTS
#   The native loader (native/hmi-gui, C++/Qt 6) replaces the PySide6 loader
#   on the panel, but the Toradex image carries only a GLES Qt 5.15 and has no
#   package feed. Until the image is rebuilt with yocto/meta-hmi's Qt 6
#   recipe, this ships the binary together with a private Qt 6 runtime under
#   /usr/lib/hmi/qt6 -- the same arrangement provision_pyside2.sh uses for
#   Qt 5 -- and leaves the panel's own Qt untouched. Both loaders can stay
#   installed: hmi-gui-launch prefers /usr/lib/hmi/gui/hmi-gui when present
#   and HMI_GUI_NATIVE=0 forces the Python one.
#
# WHAT LANDS ON THE PANEL
#   /usr/lib/hmi/gui/hmi-gui         sh wrapper: sets the runtime paths, execs
#   /usr/lib/hmi/gui/hmi-gui.bin     the aarch64 binary
#   /usr/lib/hmi/qt6/{lib,plugins,qml}   the private Qt 6.4 runtime
#
# USAGE
#   bash deploy/provision_native.sh --host <panel-ip> [--user root] [--key <path>]
#   bash deploy/provision_native.sh --build-only            # chroot -> build -> runtime
#   bash deploy/provision_native.sh --host <ip> --no-build  # ship what out/aarch64 has
#   bash deploy/provision_native.sh --host <ip> --remove    # back to the Python loader
#
# REQUIREMENTS
#   Build: WSL Ubuntu as root (native/hmi-gui/arm64/*.sh: mmdebstrap + qemu-user).
#   Install: ssh/scp access to the panel as root (BatchMode, key auth).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO/native/hmi-gui/out/aarch64"
ARM64="$REPO/native/hmi-gui/arm64"

HOST=""; USER_="root"; KEY=""; BUILD=1; INSTALL=1; REMOVE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --user) USER_="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --build-only) INSTALL=0; shift ;;
        --no-build) BUILD=0; shift ;;
        --remove) REMOVE=1; BUILD=0; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ "$INSTALL" = 1 ] && [ -z "$HOST" ] && { echo "--host required (or --build-only)" >&2; exit 2; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)
SCP=(scp -q -o BatchMode=yes)
[ -n "$KEY" ] && { SSH+=(-i "$KEY"); SCP+=(-i "$KEY"); }
T="$USER_@$HOST"

if [ "$BUILD" = 1 ]; then
    echo "== build (bookworm arm64 root under qemu)"
    bash "$ARM64/chroot.sh"
    bash "$ARM64/build.sh"
    bash "$ARM64/runtime.sh"
fi
[ "$INSTALL" = 1 ] || exit 0

if [ "$REMOVE" = 1 ]; then
    echo "== removing the native loader from $HOST"
    "${SSH[@]}" "$T" 'rm -rf /usr/lib/hmi/gui/hmi-gui /usr/lib/hmi/gui/hmi-gui.bin /usr/lib/hmi/qt6 && systemctl restart hmi-gui.service && echo removed'
    exit 0
fi

[ -f "$OUT/hmi-gui" ] || { echo "no binary at $OUT/hmi-gui" >&2; exit 1; }   # -f: an ELF has no exec bit under Git Bash
[ -f "$OUT/hmi-qt6-runtime.tar.gz" ] || { echo "no runtime tarball in $OUT" >&2; exit 1; }

echo "== survey $HOST"
"${SSH[@]}" "$T" 'uname -m; ldd --version | head -1; ls /usr/local/lib/libGL.so.1 /usr/lib/hmi/gui/main.py /usr/lib/hmi/qml/Shadcn/qmldir' \
    | sed 's/^/  /'

echo "== upload"
"${SCP[@]}" "$OUT/hmi-gui" "$OUT/hmi-qt6-runtime.tar.gz" "$T:/tmp/"

echo "== install"
"${SSH[@]}" "$T" 'set -e
    rm -rf /usr/lib/hmi/qt6
    tar -C / -xzf /tmp/hmi-qt6-runtime.tar.gz
    install -m 0755 /tmp/hmi-gui /usr/lib/hmi/gui/hmi-gui.bin
    cat > /usr/lib/hmi/gui/hmi-gui <<"WRAP"
#!/bin/sh
# Native hmi-gui loader with its private Qt 6 runtime (deploy/provision_native.sh).
# The binary itself adds /usr/lib/hmi/qml; the Qt modules live under qt6/qml.
QT6=/usr/lib/hmi/qt6
export LD_LIBRARY_PATH="$QT6/lib:/usr/local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="$QT6/plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
export QML_IMPORT_PATH="$QT6/qml${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}"
exec /usr/lib/hmi/gui/hmi-gui.bin "$@"
WRAP
    chmod 0755 /usr/lib/hmi/gui/hmi-gui
    rm -f /tmp/hmi-gui /tmp/hmi-qt6-runtime.tar.gz
    echo "  installed: $(du -sh /usr/lib/hmi/qt6 | cut -f1) runtime, $(ls -la /usr/lib/hmi/gui/hmi-gui.bin | awk "{print \$5}") byte binary"
    echo "== smoke (offscreen, 3 s)"
    QT_QPA_PLATFORM=offscreen /usr/lib/hmi/gui/hmi-gui --help >/dev/null && echo "  --help ok"
    missing=$(LD_LIBRARY_PATH=/usr/lib/hmi/qt6/lib:/usr/local/lib ldd /usr/lib/hmi/gui/hmi-gui.bin | grep "not found" || true)
    [ -z "$missing" ] && echo "  all libraries resolve" || { echo "  MISSING:"; echo "$missing"; exit 1; }
'

echo "== restart hmi-gui"
"${SSH[@]}" "$T" 'systemctl restart hmi-gui.service; sleep 8; systemctl is-active hmi-gui; journalctl -u hmi-gui -b --since "-30s" --no-pager -o cat | grep -E "native loader|hmi-gui -|ready|rror" | tail -12' \
    | sed 's/^/  /'
