#!/bin/sh
# install.sh -- target half of panel provisioning
# =====================================================================
#
# PURPOSE
#   Install the EmbeddedDisplay Studio platform (Layer 1 daemon, the Qt-free
#   Layer 2 GUI runtime hmi-ui, the atomic installer and the systemd units)
#   onto a panel that is already running a Linux image, without reflashing it.
#
#   The GUI is native/hmi-ui: C + LVGL drawing to DRM/KMS. No Qt, no
#   compositor. A panel provisioned by an earlier version for the Qt loader
#   is converted here: the loader, its private Qt6 runtime and the Weston
#   background configuration are removed (HMI_KEEP_QT=1 keeps them, disabled).
#
#   This is the same file set the meta-hmi bitbake layer puts into an
#   image; provisioning exists for boards that are already in the field
#   or on a bench, where rebuilding and reflashing an image to try a
#   deployment is not a reasonable ask.
#
# USAGE
#   Not run by hand. deploy/provision_panel.py uploads a tarball
#   containing this script plus a files/ tree and runs:
#       sh install.sh
#
# EXIT CODES
#   0  -- success
#   1  -- installation error
#   2  -- unmet prerequisite
#
# MACHINE-READABLE OUTPUT
#   Every step prints:  STEP <tag> <ok|fail> [detail]
#   matching the vocabulary hmi-install uses, so the host driver parses
#   one format for both.
#
# ENVIRONMENT
#   HMI_KEEP_QT       -- "1" leaves the Qt loader files, the Qt6 runtime and
#                        the weston units on disk (disabled) instead of
#                        removing them. Default is to remove them.
#                        /opt/hmi-python is never removed: it is the complete
#                        CPython the installer and the daemon run on (a Yocto
#                        image's own python3 can be python3-core alone); only
#                        the PySide6/shiboken6 packages inside it go.
#   HMI_FORCE_PYTHON  -- "1" replaces an existing /opt/hmi-python with the
#                        interpreter in the payload (files/opt/hmi-python.tar.gz,
#                        added by provision_panel.py --python). Default is to
#                        install it only when /opt/hmi-python is absent.
#   HMI_FORCE_CONFIG  -- "1" overwrites /etc/hmi/hwd.json and
#                        /etc/default/hmi-ui. Default is to leave an
#                        existing config alone: those two files are how
#                        a board is matched to its carrier, and silently
#                        replacing them turns a provisioning run into a
#                        hardware reconfiguration.
#   HMI_ENABLE_HWD    -- "1" enables and starts hmi-hwd.service. Default
#                        is off: the daemon drives GPIO outputs from a
#                        pin map that is board specific, and the shipped
#                        hwd.json is a Dahlia carrier default. Starting
#                        it against an unverified pin map can assert real
#                        outputs on real hardware.
#
# =====================================================================

set -eu

STAGE_FILES="./files"

HMI_FORCE_CONFIG="${HMI_FORCE_CONFIG:-0}"
HMI_ENABLE_HWD="${HMI_ENABLE_HWD:-0}"

step() {
    _tag="$1"; shift
    _stat="$1"; shift
    printf 'STEP %s %s %s\n' "$_tag" "$_stat" "$*"
}

log() {
    _sev="$1"; shift
    printf '[provision] %s: %s\n' "$_sev" "$*" >&2
}

die() {
    _rc="$1"; shift
    _tag="$1"; shift
    step "$_tag" "fail" "$*"
    log "ERROR" "$*"
    exit "$_rc"
}

##
# install_file -- copy one payload file into place with an explicit mode
#
# Args:
#   $1  relative path under files/ (also the absolute target path)
#   $2  mode, e.g. 0755
# Returns: 0
# Exits:   1 if the source is missing or the copy fails
##
install_file() {
    _rel="$1"
    _mode="$2"
    _src="${STAGE_FILES}/${_rel}"
    _dst="/${_rel}"

    [ -f "$_src" ] || die 1 "install" "payload is missing ${_rel}"

    mkdir -p "$(dirname "$_dst")"
    # Copy to a temporary name in the destination directory and rename, so a
    # file that is currently executing (hmi-install can be provisioning itself
    # on a re-run) is replaced rather than written through.
    _tmp="${_dst}.provision.$$"
    cp "$_src" "$_tmp"
    chmod "$_mode" "$_tmp"
    mv -f "$_tmp" "$_dst"
}

##
# install_config -- install a config file only if it is not already present
#
# Args:
#   $1  relative path under files/
#   $2  mode
# Returns: 0
##
install_config() {
    _rel="$1"
    _mode="$2"
    if [ -f "/${_rel}" ] && [ "$HMI_FORCE_CONFIG" != "1" ]; then
        log "INFO" "keeping existing /${_rel} (HMI_FORCE_CONFIG=1 to replace)"
        return 0
    fi
    install_file "$_rel" "$_mode"
}

##
# install_tree -- copy a whole directory from the payload, preserving layout
#
# Args:
#   $1  relative directory under files/ (also the absolute target path)
#   $2  mode for regular files
# Returns: 0
##
install_tree() {
    _rel="$1"
    _mode="$2"
    _src="${STAGE_FILES}/${_rel}"

    [ -d "$_src" ] || die 1 "install" "payload is missing directory ${_rel}"

    mkdir -p "/${_rel}"
    # -a would carry over ownership from the tarball; the target wants
    # root:root, which is what a plain copy as root produces.
    (cd "$_src" && find . -type d -exec mkdir -p "/${_rel}/{}" \;)
    (cd "$_src" && find . -type f -exec cp {} "/${_rel}/{}" \;)
    find "/${_rel}" -type f -exec chmod "$_mode" {} \;
    find "/${_rel}" -type d -exec chmod 0755 {} \;
}

# ---- Prerequisites ---------------------------------------------------
# Checked here as well as on the host: provisioning can be re-run directly
# on the board, and a missing python3 must fail loudly rather than leave a
# half-installed platform behind.

if ! command -v python3 >/dev/null 2>&1; then
    die 2 "prereq" "python3 not found; hmi-install and the GUI loader both require it"
fi
step "prereq" "ok" "python3 $(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"

if ! command -v systemctl >/dev/null 2>&1; then
    die 2 "prereq-systemd" "systemctl not found; this platform installs as systemd units"
fi
step "prereq-systemd" "ok" "systemd present"

# ---- Executables -----------------------------------------------------

install_file "usr/bin/hmi-install"    0755
install_file "usr/bin/hmi-hwd-launch" 0755
step "install-bin" "ok" "/usr/bin/hmi-install, /usr/bin/hmi-hwd-launch"

# ---- Layer 2: the GUI runtime and its kit -----------------------------
# hmi-ui finds the kit (Inter fonts, Tabler icon PNGs) at /usr/lib/hmi/kit.

install_file "usr/lib/hmi/ui/hmi-ui" 0755
install_tree "usr/lib/hmi/kit" 0644
step "install-gui" "ok" "/usr/lib/hmi/ui/hmi-ui, /usr/lib/hmi/kit"

# ---- The Qt loader, if an earlier provisioning left it -----------------
# hmi-ui.service declares Conflicts= on weston.service and hmi-gui.service,
# so even when they stay on disk they cannot take the display back. Removing
# the files frees ~100 MB (the private Qt6 runtime) and leaves nothing that
# could be started by mistake.

HMI_KEEP_QT="${HMI_KEEP_QT:-0}"
_qt_present=0
for _p in /usr/lib/hmi/gui /usr/lib/hmi/shell /usr/lib/hmi/qml /usr/lib/hmi/qt6 \
          /usr/bin/hmi-gui-launch /etc/systemd/system/hmi-gui.service /etc/default/hmi-gui \
          /opt/hmi-python-qt5 /opt/hmi-python/lib/python3*/site-packages/PySide6; do
    [ -e "$_p" ] && _qt_present=1
done
if [ "$_qt_present" = 1 ]; then
    systemctl disable --now hmi-gui.service >/dev/null 2>&1 || true
    systemctl disable --now weston.service weston.socket >/dev/null 2>&1 || true
    if [ "$HMI_KEEP_QT" = "1" ]; then
        step "remove-qt" "ok" "kept (HMI_KEEP_QT=1); hmi-gui.service and weston disabled"
    else
        rm -rf /usr/lib/hmi/gui /usr/lib/hmi/shell /usr/lib/hmi/qml /usr/lib/hmi/qt6 \
               /usr/bin/hmi-gui-launch /etc/systemd/system/hmi-gui.service /etc/default/hmi-gui \
               /opt/hmi-python-qt5 /usr/share/hmi/boot-banner.png \
               /usr/share/hmi/boot-banner-light.png
        # The interpreter stays; the Qt bindings inside it go (~200 MB).
        if [ -x /opt/hmi-python/bin/python3 ]; then
            /opt/hmi-python/bin/python3 -m pip uninstall -y -q PySide6 PySide6-Essentials PySide6-Addons shiboken6 >/dev/null 2>&1 || true
            rm -rf /opt/hmi-python/lib/python3*/site-packages/PySide6* /opt/hmi-python/lib/python3*/site-packages/shiboken6*
        fi
        # The banner line this script once wrote into weston.ini.
        if [ -f /etc/xdg/weston/weston.ini ] && grep -q "boot-banner" /etc/xdg/weston/weston.ini; then
            sed -i '/^background-image=.*boot-banner/d; /^background-type=/d' /etc/xdg/weston/weston.ini
        fi
        systemctl daemon-reload
        step "remove-qt" "ok" "Qt loader, Qt6 runtime and weston autostart removed"
    fi
else
    step "remove-qt" "ok" "no Qt loader on this panel"
fi

# ---- The interpreter ---------------------------------------------------
# hmi-install and hmi-hwd prefer /opt/hmi-python/bin/python3 (target/README.md,
# "Interpreter resolution") because a Yocto image's /usr/bin/python3 may be
# python3-core alone. provision_panel.py --python adds a python-build-standalone
# tarball to the payload; it is installed when the panel has no usable one.

HMI_FORCE_PYTHON="${HMI_FORCE_PYTHON:-0}"
_py_tar="${STAGE_FILES}/opt/hmi-python.tar.gz"
if [ -f "$_py_tar" ]; then
    if [ -x /opt/hmi-python/bin/python3 ] && [ "$HMI_FORCE_PYTHON" != "1" ]; then
        step "install-python" "ok" "kept existing /opt/hmi-python (HMI_FORCE_PYTHON=1 to replace)"
    else
        rm -rf /opt/hmi-python.new
        mkdir -p /opt/hmi-python.new
        tar -xzf "$_py_tar" -C /opt/hmi-python.new --strip-components=1
        rm -rf /opt/hmi-python.old
        [ -d /opt/hmi-python ] && mv /opt/hmi-python /opt/hmi-python.old
        mv /opt/hmi-python.new /opt/hmi-python
        rm -rf /opt/hmi-python.old
        _wheels="${STAGE_FILES}/opt/hmi-python-wheels"
        if [ -d "$_wheels" ]; then
            /opt/hmi-python/bin/python3 -m pip install -q --no-index --find-links "$_wheels" gpiod pyserial >/dev/null 2>&1 \
                || log "WARN: could not install the daemon's optional packages (gpiod, pyserial)"
        fi
        step "install-python" "ok" "/opt/hmi-python ($(/opt/hmi-python/bin/python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))'))"
    fi
fi
if /opt/hmi-python/bin/python3 -c 'import json, socket, hashlib, ctypes, asyncio' >/dev/null 2>&1 \
   || python3 -c 'import json, socket, hashlib, ctypes, asyncio' >/dev/null 2>&1; then
    step "check-python" "ok" "an interpreter with the full stdlib is available"
else
    step "check-python" "fail" "neither /opt/hmi-python nor python3 has the full stdlib; hmi-install and hmi-hwd cannot run (provision_panel.py --python <tarball>)"
fi

# ---- Layer 1: hardware daemon ----------------------------------------

install_file   "usr/lib/hmi/hmi_hwd.py" 0755
# The Modbus TCP client the daemon imports as a sibling module.
install_file   "usr/lib/hmi/modbus.py"  0644
# The shared CONTRACT section 4 validator, called by hmi-install.
install_file   "usr/lib/hmi/manifest.py" 0644
install_config "etc/hmi/hwd.json"       0644
step "install-hwd" "ok" "/usr/lib/hmi/hmi_hwd.py, /usr/lib/hmi/modbus.py, /usr/lib/hmi/manifest.py"

# ---- Configuration ---------------------------------------------------

install_config "etc/default/hmi-ui" 0644
step "install-config" "ok" "/etc/default/hmi-ui"

# ---- Runtime directories ---------------------------------------------
# tmpfiles.d creates these at every boot; create them now so the first
# deployment does not have to wait for a reboot.

install_file "usr/lib/tmpfiles.d/hmi.conf" 0644
mkdir -p /run/hmi /tmp/hmi_upload /opt/hmi_apps/releases
chmod 0755 /run/hmi /opt/hmi_apps /opt/hmi_apps/releases
chmod 0700 /tmp/hmi_upload
if command -v systemd-tmpfiles >/dev/null 2>&1; then
    systemd-tmpfiles --create /usr/lib/tmpfiles.d/hmi.conf >/dev/null 2>&1 || true
fi
step "install-runtime" "ok" "/run/hmi, /tmp/hmi_upload, /opt/hmi_apps"

# ---- systemd units ---------------------------------------------------

install_file "etc/systemd/system/hmi-ui.service" 0644
install_file "etc/systemd/system/hmi-hwd.service" 0644
systemctl daemon-reload
step "install-units" "ok" "hmi-ui.service, hmi-hwd.service"

# ---- Autostart -------------------------------------------------------
# hmi-ui.service is enabled and (re)started: with no application deployed it
# shows its built-in fallback screen, which is the right thing for a panel
# on a bench to display, and a panel that already has an application picks
# up the new runtime immediately.

if systemctl enable hmi-ui.service >/dev/null 2>&1; then
    if systemctl restart hmi-ui.service >/dev/null 2>&1; then
        step "enable-boot" "ok" "hmi-ui.service enabled and started"
    else
        step "enable-boot" "fail" "hmi-ui.service enabled but did not start; see journalctl -u hmi-ui"
    fi
else
    step "enable-boot" "fail" "could not enable hmi-ui.service"
fi

if [ "$HMI_ENABLE_HWD" = "1" ]; then
    if systemctl enable --now hmi-hwd.service >/dev/null 2>&1; then
        step "enable-hwd" "ok" "hmi-hwd.service enabled and started"
    else
        step "enable-hwd" "fail" "could not enable hmi-hwd.service"
    fi
else
    step "enable-hwd" "ok" "skipped -- verify hwd.json against this carrier first"
fi

# ---- Verify ----------------------------------------------------------

if hmi-install status >/dev/null 2>&1; then
    step "verify" "ok" "hmi-install responds"
else
    die 1 "verify" "hmi-install is installed but did not run cleanly"
fi

step "provision-complete" "ok" "panel is ready to receive a deployment"
