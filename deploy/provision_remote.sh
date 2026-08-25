#!/bin/sh
# install.sh -- target half of panel provisioning
# =====================================================================
#
# PURPOSE
#   Install the EmbeddedDisplay platform (Layer 1 daemon, Layer 2 loader,
#   the atomic installer and the systemd units) onto a panel that is
#   already running a Linux image, without reflashing it.
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
#   HMI_FORCE_CONFIG  -- "1" overwrites /etc/hmi/hwd.json and
#                        /etc/default/hmi-gui. Default is to leave an
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
install_file "usr/bin/hmi-gui-launch" 0755
install_file "usr/bin/hmi-hwd-launch" 0755
step "install-bin" "ok" "/usr/bin/hmi-install, /usr/bin/hmi-gui-launch, /usr/bin/hmi-hwd-launch"

# ---- Layer 2: GUI loader, shell QML, shared component kit -------------
# The loader resolves its shell as <its own dir>/../shell/Shell.qml and adds
# /usr/lib/hmi/qml to the QML import path, so these three trees have to keep
# this exact relative arrangement.

install_tree "usr/lib/hmi/gui"   0644
install_tree "usr/lib/hmi/shell" 0644
install_tree "usr/lib/hmi/qml"   0644
chmod 0755 /usr/lib/hmi/gui/main.py
step "install-gui" "ok" "/usr/lib/hmi/gui, /usr/lib/hmi/shell, /usr/lib/hmi/qml"

# ---- Layer 1: hardware daemon ----------------------------------------

install_file   "usr/lib/hmi/hmi_hwd.py" 0755
# The shared CONTRACT section 4 validator, called by hmi-install.
install_file   "usr/lib/hmi/manifest.py" 0644
install_config "etc/hmi/hwd.json"       0644
step "install-hwd" "ok" "/usr/lib/hmi/hmi_hwd.py, /usr/lib/hmi/manifest.py"

# ---- Configuration ---------------------------------------------------

install_config "etc/default/hmi-gui" 0644
step "install-config" "ok" "/etc/default/hmi-gui"

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

install_file "etc/systemd/system/hmi-gui.service" 0644
install_file "etc/systemd/system/hmi-hwd.service" 0644
systemctl daemon-reload
step "install-units" "ok" "hmi-gui.service, hmi-hwd.service"

# ---- Autostart -------------------------------------------------------
# hmi-gui.service is enabled but NOT started: there is no application
# installed yet, and starting it now would put the unit into a restart loop
# against an empty /opt/hmi_apps/current. The first deploy starts it.

if systemctl enable hmi-gui.service >/dev/null 2>&1; then
    step "enable-boot" "ok" "hmi-gui.service enabled (starts on the first deploy)"
else
    step "enable-boot" "fail" "could not enable hmi-gui.service"
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
