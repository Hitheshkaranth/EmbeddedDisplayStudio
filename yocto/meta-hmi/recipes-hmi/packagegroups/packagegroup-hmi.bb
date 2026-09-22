# recipes-hmi/packagegroups/packagegroup-hmi.bb
#
# Aggregates the core HMI components, the Qt-free GUI runtime, its kit,
# and runtime utilities required by the deployment pipeline for Toradex
# Verdin i.MX8M Plus (systemd; the GUI draws to DRM/KMS itself, so no
# compositor is part of the stack).
#
# Implements CONTRACT.md section 3 (filesystem layout) and section 6
# (deployment pipeline requirements).

DESCRIPTION = "Packagegroup for BYOA HMI runtime stack and deployment tools"
HOMEPAGE = "https://example.com/byoa-hmi"
SECTION = "hmi"

# Standard MIT licence matching the meta-hmi layer declaration.
# LIC_FILES_CHKSUM references the common licence file in OE core.
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# Inherit the standard Yocto packagegroup class.
# This bbclass automatically sets PACKAGE_ARCH = "${MACHINE_ARCH}" (or "all" if allarch),
# disables packaging tasks like do_compile and do_install, and configures
# package splitting and dependencies appropriate for packagegroups.
inherit packagegroup

# ---------------------------------------------------------------------------
# RDEPENDS:${PN} - runtime package aggregation
#
# 1. HMI packages (meta-hmi):
#    - hmi-core: hardware daemon (hmi_hwd.py), config (hwd.json), installer
#      (/usr/bin/hmi-install), launcher (/usr/bin/hmi-hwd-launch), systemd
#      units (hmi-hwd.service, hmi-ui.service), tmpfiles config.
#    - hmi-ui: the panel GUI (native/hmi-ui, C + LVGL on DRM/KMS).
#    - hmi-ui-kit: the fonts and icon PNGs hmi-ui renders with.
#
# 2. Host-to-target deployment pipeline:
#    - openssh-sftp-server: sftp subsystem for scp uploads to /tmp/hmi_upload.
#    - util-linux: the standalone 'flock' hmi-install serialises installs with.
#    - coreutils: sha256sum, realpath, install.
#
# 3. Graphics: libdrm only. There is no compositor, no Wayland and no Qt in
#    this stack; the reference image's weston may stay installed but
#    hmi-ui.service declares Conflicts=weston.service and takes the display.
#
# 4. Python3 runtime for the daemon and the installer (see hmi-core for the
#    full closure of stdlib subpackages).
# ---------------------------------------------------------------------------
RDEPENDS:${PN} = " \
    hmi-core \
    hmi-ui \
    hmi-ui-kit \
    openssh-sftp-server \
    util-linux \
    coreutils \
    libdrm \
    python3-core \
    python3-json \
    python3-logging \
    python3-threading \
    python3-subprocess \
    python3-pathlib \
    python3-signal \
    python3-fcntl \
"
