# recipes-hmi/hmi-core/hmi-core_1.0.bb
#
# Packages the HMI hardware daemon (hmi_hwd.py), its runtime configuration,
# the installer and launcher scripts, the systemd units, the tmpfiles.d
# fragment, and the top-level application directories.
#
# Target paths (CONTRACT section 3):
#   /usr/lib/hmi/hmi_hwd.py          hardware daemon
#   /etc/hmi/hwd.json                runtime pin/bus configuration
#   /usr/bin/hmi-install             application installer helper
#   /usr/bin/hmi-gui-launch          GUI launcher wrapper
#   /etc/default/hmi-gui             GUI launcher environment defaults
#   /usr/lib/tmpfiles.d/hmi.conf     tmpfiles.d fragment
#   ${systemd_unitdir}/system/hmi-hwd.service
#   ${systemd_unitdir}/system/hmi-gui.service
#   /opt/hmi_apps/                   runtime app root (created by tmpfiles)
#   /opt/hmi_apps/releases/          versioned app slots

DESCRIPTION = "BYOA HMI hardware daemon, installer, and systemd integration"
HOMEPAGE = "https://example.com/byoa-hmi"
SECTION = "hmi"

# MIT licence declared here; LIC_FILES_CHKSUM points at the canonical copy
# shipped by the base layer so no extra source fetch is required.
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# ---------------------------------------------------------------------------
# Source files
#
# We use file:// URIs so the recipe can be built from a workspace checkout
# without a network connection.  Each files/ entry is a symlink (or copy)
# to the matching path in the repository tree; see yocto/README.md for the
# ln -s commands.
#
# For production, replace these with a git:// URI plus SRCREV.
#
# Listing individual files rather than a tarball means bitbake hashes each
# file independently - a change to hwd.json does NOT force a rebuild of
# the daemon binary.
# ---------------------------------------------------------------------------
SRC_URI = " \
    file://hmi_hwd.py \
    file://hwd.json \
    file://hmi-install \
    file://hmi-gui-launch \
    file://hmi-gui.default \
    file://hmi.conf \
    file://hmi-hwd.service \
    file://hmi-gui.service \
"

# S = "${WORKDIR}" is correct for file:// sources up to and including
# scarthgap (Yocto 5.0).  In styhead (Yocto 5.1) the unpacker writes files
# into UNPACKDIR instead; WORKDIR still works but triggers a deprecation
# warning.  Use the version-guarded form below to stay clean on both:
#
#   S:styhead = "${UNPACKDIR}"
#   S         = "${WORKDIR}"
#
# The override uses the release codename as the machine/distro override key
# so no Python version-comparison is needed.
S:styhead = "${UNPACKDIR}"
S         = "${WORKDIR}"

# ---------------------------------------------------------------------------
# Architecture decision: do NOT inherit allarch.
#
# allarch is only correct when the package has zero arch-specific
# RDEPENDS.  This recipe depends on python3-libgpiod / libgpiod-python
# (see HMI_GPIOD_PYTHON below) which is an arch-dependent native extension.
# Marking the recipe as allarch while carrying arch-specific RDEPENDS would
# cause a QA failure ("RPROVIDES_allarch").  We therefore build as a normal
# noarch recipe (the Python source is architecture-neutral) but let bitbake
# assign the correct PACKAGE_ARCH via the RDEPENDS mechanism.
# ---------------------------------------------------------------------------

# inherit systemd pulls in the systemd bbclass which sets up
# SYSTEMD_SERVICE, do_install:append for unit files, and pkg_postinst.
# features_check enforces that the DISTRO_FEATURES list includes "systemd"
# so the recipe fails early with a clear error on a sysvinit-only image
# rather than silently installing orphaned unit files.
inherit systemd features_check

# Abort if systemd is not in the distro feature set.
REQUIRED_DISTRO_FEATURES = "systemd"

# List both managed units.  The systemd bbclass wires these into
# pkg_postinst / pkg_prerm automatically.
SYSTEMD_SERVICE:${PN} = "hmi-hwd.service hmi-gui.service"

# Enable both units at image-build time (equivalent to `systemctl enable`).
# Set to "disable" in local.conf overrides if you want the service
# opt-in on the target.
SYSTEMD_AUTO_ENABLE = "enable"

# ---------------------------------------------------------------------------
# libgpiod Python bindings - generation-dependent recipe name
#
# libgpiod 1.x shipped the Python bindings as a separate package called
# "libgpiod-python".  libgpiod 2.x restructured the tree; the bitbake
# recipe is now "python3-libgpiod".  The correct choice depends on which
# version your BSP layer carries:
#
#   Toradex BSP 5 / kirkstone : libgpiod 1.x  -> HMI_GPIOD_PYTHON = "libgpiod-python"
#   Toradex BSP 6+ / scarthgap: libgpiod 2.x  -> HMI_GPIOD_PYTHON = "python3-libgpiod"
#
# The default below targets BSP 6/7 (scarthgap).  Override in local.conf:
#   HMI_GPIOD_PYTHON = "libgpiod-python"
# ---------------------------------------------------------------------------
HMI_GPIOD_PYTHON ?= "python3-libgpiod"

# ---------------------------------------------------------------------------
# RDEPENDS - runtime dependencies
#
# Only packages that the daemon actually imports at runtime are listed here.
# Packages that are guaranteed to be present in the Toradex reference
# multimedia image (python3-core, python3-json, etc.) are still listed
# explicitly so the recipe is portable to a minimal image.
#
# python3-core       - Python interpreter and built-ins
# python3-json       - json module (used to parse hwd.json)
# python3-logging    - logging module (used throughout the daemon)
# python3-threading  - threading module (watchdog thread)
# python3-subprocess - subprocess module (used by hmi-install to run apps)
# python3-pathlib    - pathlib module (Path objects in installer)
# python3-signal     - signal module (SIGTERM / SIGHUP handler)
# python3-fcntl      - fcntl module (advisory lock in hmi-install via flock)
# ${HMI_GPIOD_PYTHON} - GPIO control; see comment above for version note
# ---------------------------------------------------------------------------
RDEPENDS:${PN} = " \
    python3-core \
    python3-json \
    python3-logging \
    python3-threading \
    python3-subprocess \
    python3-pathlib \
    python3-signal \
    python3-fcntl \
    ${HMI_GPIOD_PYTHON} \
"

# ---------------------------------------------------------------------------
# FILES - packaging paths
#
# Bitbake automatically includes everything under ${bindir}, ${sysconfdir},
# ${libdir}, ${systemd_unitdir}, and ${prefix}/lib/tmpfiles.d in the main
# package.  /opt is NOT in the default packaging path, so we must list it
# explicitly; otherwise the directories would be created by do_install but
# silently dropped from the .ipk/.rpm.
# ---------------------------------------------------------------------------
FILES:${PN} += " \
    /opt/hmi_apps \
    /opt/hmi_apps/releases \
"

# Mark the two runtime config files as CONFFILES.  bitbake (and the package
# manager on the target) will then refuse to overwrite them during an
# upgrade if the integrator has edited them, and will instead leave a .rpmnew
# / .dpkg-old file alongside.  This prevents a firmware update from
# silently resetting the integrator's pin map.
CONFFILES:${PN} = " \
    ${sysconfdir}/hmi/hwd.json \
    ${sysconfdir}/default/hmi-gui \
"

# ---------------------------------------------------------------------------
# do_install
# ---------------------------------------------------------------------------
do_install() {
    # -----------------------------------------------------------------------
    # /usr/lib/hmi/ - private library directory for HMI Python modules.
    # We use ${libdir} (resolves to /usr/lib on aarch64) rather than a
    # hard-coded path so that multilib builds (/usr/lib64) stay correct.
    # -----------------------------------------------------------------------
    install -d ${D}${libdir}/hmi

    # Install the hardware daemon.  Mode 0644 is correct: systemd runs it
    # via `ExecStart=/usr/bin/python3 /usr/lib/hmi/hmi_hwd.py` so the
    # execute bit is not needed on the .py file itself.
    install -m 0644 ${S}/hmi_hwd.py ${D}${libdir}/hmi/hmi_hwd.py

    # -----------------------------------------------------------------------
    # /etc/hmi/ - runtime configuration (pinned to ${sysconfdir}).
    # This directory is not in the default CONFFILES path, so we create it
    # explicitly and install hwd.json with mode 0640 to prevent world-read
    # of the pin/bus mapping (may contain hardware security parameters).
    # -----------------------------------------------------------------------
    install -d ${D}${sysconfdir}/hmi
    install -m 0640 ${S}/hwd.json ${D}${sysconfdir}/hmi/hwd.json

    # -----------------------------------------------------------------------
    # /usr/bin/ - public executables.
    # ${bindir} resolves to /usr/bin; mode 0755 required for executables.
    # -----------------------------------------------------------------------
    install -d ${D}${bindir}
    install -m 0755 ${S}/hmi-install     ${D}${bindir}/hmi-install
    install -m 0755 ${S}/hmi-gui-launch  ${D}${bindir}/hmi-gui-launch

    # -----------------------------------------------------------------------
    # /etc/default/hmi-gui - environment defaults for the GUI launcher.
    # Installed under ${sysconfdir}/default/ (the Debian/systemd convention
    # for EnvironmentFile= entries) with mode 0644 so non-root users can
    # read it (the GUI may run as a dedicated hmi user).
    # -----------------------------------------------------------------------
    install -d ${D}${sysconfdir}/default
    install -m 0644 ${S}/hmi-gui.default ${D}${sysconfdir}/default/hmi-gui

    # -----------------------------------------------------------------------
    # /usr/lib/tmpfiles.d/hmi.conf - tmpfiles.d fragment.
    # systemd-tmpfiles reads this at boot to create /run/hmi and apply
    # correct ownership on /opt/hmi_apps.  We install under ${libdir} because
    # bitbake's systemd class expects tmpfiles fragments in ${prefix}/lib/
    # (i.e. the non-arch libdir); on a standard aarch64 build both resolve
    # to /usr/lib so there is no practical difference, but using the variable
    # is correct for future multilib scenarios.
    # -----------------------------------------------------------------------
    install -d ${D}${nonarch_libdir}/tmpfiles.d
    install -m 0644 ${S}/hmi.conf ${D}${nonarch_libdir}/tmpfiles.d/hmi.conf

    # -----------------------------------------------------------------------
    # Systemd unit files.
    # The systemd bbclass provides ${systemd_unitdir} (= /usr/lib/systemd)
    # and will create the symlinks in /etc/systemd/system/multi-user.target.
    # wants/ automatically when SYSTEMD_AUTO_ENABLE = "enable".
    # We create the system/ subdirectory explicitly in case the bbclass
    # does not do so before do_install runs.
    # -----------------------------------------------------------------------
    install -d ${D}${systemd_unitdir}/system
    install -m 0644 ${S}/hmi-hwd.service ${D}${systemd_unitdir}/system/hmi-hwd.service
    install -m 0644 ${S}/hmi-gui.service ${D}${systemd_unitdir}/system/hmi-gui.service

    # -----------------------------------------------------------------------
    # /opt/hmi_apps/ and /opt/hmi_apps/releases/ - application root.
    # These directories are owned by the recipe at install time; at runtime
    # systemd-tmpfiles (via hmi.conf) sets the correct ownership for the
    # hmi system user.  We create them here so the package manager can track
    # them; the tmpfiles.d fragment re-creates them on a fresh target with
    # the right permissions.
    # -----------------------------------------------------------------------
    install -d ${D}/opt/hmi_apps
    install -d ${D}/opt/hmi_apps/releases
}