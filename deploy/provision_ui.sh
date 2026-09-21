#!/usr/bin/env bash
# deploy/provision_ui.sh -- install the Qt-free runtime (native/hmi-ui) on a panel.
#
# Ships the aarch64 binary to /usr/lib/hmi/ui/hmi-ui and installs
# hmi-ui.service, which draws straight to DRM/KMS: it conflicts with
# weston.service and hmi-gui.service and takes their place. The kit
# (fonts) and the deployed bundle are the ones already on the panel
# (/usr/lib/hmi/qml/Shadcn, /opt/hmi_apps/current); hmi-ui reads the
# bundle's project.edsui and ignores its generated QML.
#
#   bash deploy/provision_ui.sh --host <ip> [--key <path>]           install + switch to hmi-ui
#   bash deploy/provision_ui.sh --host <ip> --restore                back to weston + hmi-gui
#   bash deploy/provision_ui.sh --host <ip> --no-build               ship what out/aarch64 has
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$REPO/native/hmi-ui/out/aarch64/hmi-ui"
HOST=""; USER_="root"; KEY=""; BUILD=1; RESTORE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --user) USER_="$2"; shift 2 ;;
        --key) KEY="$2"; shift 2 ;;
        --no-build) BUILD=0; shift ;;
        --restore) RESTORE=1; BUILD=0; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done
[ -n "$HOST" ] || { echo "--host required" >&2; exit 2; }
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10)
SCP=(scp -q -o BatchMode=yes)
[ -n "$KEY" ] && { SSH+=(-i "$KEY"); SCP+=(-i "$KEY"); }
T="$USER_@$HOST"

if [ "$RESTORE" = 1 ]; then
    "${SSH[@]}" "$T" 'systemctl disable --now hmi-ui.service 2>/dev/null; systemctl enable weston.service hmi-gui.service >/dev/null 2>&1; systemctl start weston.service; sleep 2; systemctl start hmi-gui.service; systemctl is-active weston hmi-gui' | sed 's/^/  /'
    exit 0
fi

if [ "$BUILD" = 1 ]; then
    bash "$REPO/native/hmi-ui/arm64/build.sh"
fi
[ -f "$BIN" ] || { echo "no binary at $BIN" >&2; exit 1; }

echo "== upload"
"${SCP[@]}" "$BIN" "$T:/tmp/hmi-ui"
echo "== install"
"${SSH[@]}" "$T" 'set -e
    install -d /usr/lib/hmi/ui
    install -m 0755 /tmp/hmi-ui /usr/lib/hmi/ui/hmi-ui
    rm -f /tmp/hmi-ui
    cat > /etc/systemd/system/hmi-ui.service <<"UNIT"
[Unit]
Description=HMI GUI (Qt-free runtime, DRM/KMS)
# Conflicts= stops the compositor and the Qt loader; After= makes systemd
# wait for those stops to finish, so the first DRM modeset never races
# Weston for the device (a race left the screen blank once).
After=network.target hmi-hwd.service weston.service hmi-gui.service
Conflicts=weston.service hmi-gui.service

[Service]
Type=simple
EnvironmentFile=-/etc/default/hmi-gui
ExecStartPre=/bin/mkdir -p /run/hmi
ExecStartPre=/bin/sh -c 'for i in $(seq 1 50); do systemctl is-active -q weston.service || exit 0; sleep 0.1; done; exit 0'
ExecStart=/usr/lib/hmi/ui/hmi-ui --apps-dir /opt/hmi_apps/current --display /dev/dri/card1 --ready-file /run/hmi/gui-ready
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical.target
UNIT
    systemctl daemon-reload
    echo "  installed /usr/lib/hmi/ui/hmi-ui and hmi-ui.service"
    QT_QPA_PLATFORM=offscreen /usr/lib/hmi/ui/hmi-ui --apps-dir /opt/hmi_apps/current --headless /tmp/hmi-ui-check.png 2>&1 | tail -2 | sed "s/^/  /"
'
echo "== switch to hmi-ui"
"${SSH[@]}" "$T" 'systemctl disable weston.service hmi-gui.service >/dev/null 2>&1; systemctl stop hmi-gui.service weston.service; systemctl enable --now hmi-ui.service; sleep 4; systemctl is-active hmi-ui; journalctl -u hmi-ui -b --since "-20s" --no-pager -o cat | grep -E "hmi-ui -|Started|rror" | tail -8' | sed 's/^/  /'
