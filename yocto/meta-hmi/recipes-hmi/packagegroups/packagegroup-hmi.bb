# recipes-hmi/packagegroups/packagegroup-hmi.bb
#
# Aggregates the core HMI components, GUI loader, UI component kit,
# and runtime utilities required by the BYOA deployment pipeline
# for Toradex Verdin i.MX8M Plus running the native Toradex Reference
# Multimedia Image (Wayland/Weston, systemd).
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
# Every package listed below is required for the full on-target BYOA experience.
# Explanations for each group:
#
# 1. BYOA HMI Core Packages (meta-hmi):
#    - hmi-core: Hardware abstraction daemon (hmi_hwd.py), config (hwd.json),
#      installer (/usr/bin/hmi-install), launcher (/usr/bin/hmi-gui-launch),
#      systemd units (hmi-hwd.service, hmi-gui.service), and tmpfiles config.
#    - hmi-gui: PySide6/Qt6 GUI application loader and shell.
#    - hmi-ui-kit: Shadcn QML component kit, token definitions, and Tabler icons.
#
# 2. Host-to-Target Deployment Pipeline Dependencies:
#    - openssh-sftp-server: Enables sftp subsystem required by modern OpenSSH scp
#      implementations during bundle upload. (Note: The base Toradex Reference
#      Multimedia image includes ssh-server-dropbear by default, which lacks full
#      sftp; including openssh-sftp-server or switching to ssh-server-openssh
#      ensures scp transfers to /tmp/hmi_upload succeed reliably).
#    - util-linux: Provides the standalone 'flock' binary used by /usr/bin/hmi-install
#      to serialize concurrent deployments on /run/hmi/install.lock.
#    - coreutils: Provides standard POSIX file utilities, sha256sum, and realpath
#      used during package verification and atomic symlink validation.
#
# 3. Compositor and Windowing Infrastructure:
#    - weston: Wayland reference compositor; native graphical display server.
#      Already provided by tdx-reference-multimedia-image, but declared here to
#      formally bind the dependency.
#    - weston-init: Systemd service scripts and configuration for Weston startup.
#    - wayland: Core Wayland protocol libraries and display server interface.
#
# 4. Python3 Runtime Extensions:
#    - python3-core: Python 3 base runtime interpreter.
#    - python3-json: JSON parsing and serialization for hwd.json, telemetry, and manifest.json.
#    - python3-logging: Logging library used by hmi_hwd.py and the GUI loader
#      (gui/hmi_loader/main.py, installed as /usr/lib/hmi/gui/main.py).
#    - python3-threading: Background reader thread support for UART.
#    - python3-subprocess: Process invocation support for launcher and diagnostics.
#    - python3-pathlib: Object-oriented filesystem path manipulation.
#    - python3-signal: POSIX signal handling for clean SIGTERM/SIGINT shutdown.
#    - python3-fcntl: File control and locking primitives.
# ---------------------------------------------------------------------------
RDEPENDS:${PN} = " \
    hmi-core \
    hmi-gui \
    hmi-ui-kit \
    openssh-sftp-server \
    util-linux \
    coreutils \
    weston \
    weston-init \
    wayland \
    python3-core \
    python3-json \
    python3-logging \
    python3-threading \
    python3-subprocess \
    python3-pathlib \
    python3-signal \
    python3-fcntl \
"
