#!/usr/bin/env bash
# deploy/provision_ui.sh -- update the panel GUI runtime (native/hmi-ui) on a panel.
#
# The developer fast path: builds hmi-ui for aarch64, ships the binary, the
# kit (fonts, icons) and hmi-ui.service, and restarts the service. It does
# not touch the daemon, the installer or the configuration -- that is what
# deploy/provision_panel.py does, and a panel must have been provisioned by
# it (or built with yocto/meta-hmi) once before this script is useful.
#
#   bash deploy/provision_ui.sh --host <ip> [--key <path>]        build + ship + restart
#   bash deploy/provision_ui.sh --host <ip> --no-build            ship what out/aarch64 has
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$REPO/native/hmi-ui/out/aarch64/hmi-ui"
HOST=""; USER_="root"; KEY=""; BUILD=1
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --user) USER_="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --no-build) BUILD=0; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "$HOST" ] || { echo "--host required" >&2; exit 2; }
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)
SCP=(scp -q -o BatchMode=yes)
[ -n "$KEY" ] && { SSH+=(-i "$KEY"); SCP+=(-i "$KEY"); }
T="$USER_@$HOST"

if [ "$BUILD" = 1 ]; then
    bash "$REPO/native/hmi-ui/arm64/build.sh"
fi
[ -f "$BIN" ] || { echo "no binary at $BIN" >&2; exit 1; }

echo "== upload"
"${SSH[@]}" "$T" 'install -d /tmp/hmi-ui-up/kit/fonts /tmp/hmi-ui-up/kit/icons'
"${SCP[@]}" "$BIN" "$T:/tmp/hmi-ui-up/hmi-ui"
"${SCP[@]}" "$REPO/target/systemd/hmi-ui.service" "$T:/tmp/hmi-ui-up/hmi-ui.service"
"${SCP[@]}" "$REPO"/ui/qml/Shadcn/fonts/*.ttf "$T:/tmp/hmi-ui-up/kit/fonts/"
"${SCP[@]}" "$REPO"/ui/qml/Shadcn/icons/*.png "$T:/tmp/hmi-ui-up/kit/icons/"
echo "== install"
"${SSH[@]}" "$T" 'set -e
    install -d /usr/lib/hmi/ui /usr/lib/hmi/kit/fonts /usr/lib/hmi/kit/icons
    install -m 0755 /tmp/hmi-ui-up/hmi-ui /usr/lib/hmi/ui/hmi-ui
    install -m 0644 /tmp/hmi-ui-up/kit/fonts/* /usr/lib/hmi/kit/fonts/
    install -m 0644 /tmp/hmi-ui-up/kit/icons/* /usr/lib/hmi/kit/icons/
    install -m 0644 /tmp/hmi-ui-up/hmi-ui.service /etc/systemd/system/hmi-ui.service
    rm -rf /tmp/hmi-ui-up
    systemctl daemon-reload
    echo "  installed /usr/lib/hmi/ui/hmi-ui, /usr/lib/hmi/kit and hmi-ui.service"
    /usr/lib/hmi/ui/hmi-ui --apps-dir /opt/hmi_apps/current --headless /tmp/hmi-ui-check.png 2>&1 | tail -2 | sed "s/^/  /"
    rm -f /tmp/hmi-ui-check.png
'
echo "== restart"
"${SSH[@]}" "$T" 'systemctl enable --now hmi-ui.service >/dev/null 2>&1; systemctl restart hmi-ui.service; sleep 4; systemctl is-active hmi-ui; journalctl -u hmi-ui -b --since "-20s" --no-pager -o cat | grep -E "hmi-ui -|Started|rror" | tail -8' | sed 's/^/  /'
