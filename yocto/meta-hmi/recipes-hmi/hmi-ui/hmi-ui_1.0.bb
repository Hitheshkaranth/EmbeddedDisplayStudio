# recipes-hmi/hmi-ui/hmi-ui_1.0.bb
#
# The panel GUI: native/hmi-ui, C11 + LVGL 9.3, drawing to DRM/KMS with no
# compositor and no Qt. It loads the deployed bundle's project.edsui
# (/opt/hmi_apps/current) and talks to hmi-hwd over the CONTRACT section 2
# UDP protocol. hmi-core ships its systemd unit and /etc/default/hmi-ui;
# hmi-ui-kit ships the fonts and icons it renders with.
#
# Target path (CONTRACT section 3):
#   /usr/lib/hmi/ui/hmi-ui      the binary (hmi-ui.service execs it)
#
# Source: the native/hmi-ui tree, with its pinned LVGL submodule checked
# out (git submodule update --init native/hmi-ui/lvgl). yocto/README.md
# has the command that populates files/. For production, switch to git://
# with SRCREV and a `;submodules=1`-style fetch of the same tree.

DESCRIPTION = "HMI panel GUI runtime (C + LVGL on DRM/KMS, Qt-free)"
HOMEPAGE = "https://example.com/byoa-hmi"
SECTION = "hmi"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

SRC_URI = "file://hmi-ui"

S:styhead = "${UNPACKDIR}/hmi-ui"
S         = "${WORKDIR}/hmi-ui"

# libdrm is the only library beyond libc and libm; LVGL and cJSON are built
# in from the source tree (native/hmi-ui/lvgl, third_party/cjson).
DEPENDS = "libdrm pkgconfig-native"
RDEPENDS:${PN} = "libdrm hmi-ui-kit"

inherit cmake pkgconfig

# CMakeLists.txt installs the binary to ${prefix}/lib/hmi/ui/hmi-ui; the
# unit file hard-codes /usr/lib/hmi/ui/hmi-ui, so pin the prefix.
EXTRA_OECMAKE = "-DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_BUILD_TYPE=Release"

FILES:${PN} += "${nonarch_libdir}/hmi/ui/hmi-ui"

# The spike and the unit tests are host-side tools; the panel gets the runtime only.
do_install:append() {
    rm -f ${D}${nonarch_libdir}/hmi/ui/hmi-ui-spike
}
