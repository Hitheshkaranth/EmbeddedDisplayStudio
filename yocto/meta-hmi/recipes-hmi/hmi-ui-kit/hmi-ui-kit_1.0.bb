# recipes-hmi/hmi-ui-kit/hmi-ui-kit_1.0.bb
#
# Packages what the panel GUI (hmi-ui) renders with: the Inter fonts and
# the Tabler icons rasterised to PNG by native/hmi-ui/schema/gen_icons.py.
# Both come from ui/qml/Shadcn/{fonts,icons} in the repository; the QML
# components beside them are the Studio's preview and the parity spec for
# the C widgets, and never reach the panel.
#
# Target path (CONTRACT section 3):
#   /usr/lib/hmi/kit/fonts/   Inter-*.ttf + LICENSE.inter
#   /usr/lib/hmi/kit/icons/   <name>.png (96 px, white on transparent)
#
# Separate from hmi-ui so the assets can be updated without a rebuild of
# the runtime, and so a design's icon additions ship as data.

DESCRIPTION = "HMI kit runtime assets for hmi-ui: the Inter fonts and the rasterised Tabler icons"
HOMEPAGE = "https://example.com/byoa-hmi"
SECTION = "hmi"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# ---------------------------------------------------------------------------
# Source files
#
# The ui/qml/Shadcn tree, ui/tokens.json, and the icon license are
# installed from the repository via file:// URIs.  See yocto/README.md for
# the cp commands that populate files/.
#
# We copy the entire Shadcn directory as a source entry so
# that adding new QML components does not require editing this recipe.
#
# For production, switch to a git:// URI with SRCREV pointing at the UI
# repo tag.
# ---------------------------------------------------------------------------
SRC_URI = " \
    file://fonts \
    file://icons \
    file://LICENSE.tabler \
"

# S override for styhead (Yocto 5.1+): see hmi-core_1.0.bb for explanation.
S:styhead = "${UNPACKDIR}"
S         = "${WORKDIR}"

# Fonts and PNGs: no architecture, no runtime dependency. The QML components
# the kit is generated from stay on the desktop (the Studio's preview and the
# parity spec); the panel never loads QML.
inherit allarch

FILES:${PN} += "${nonarch_libdir}/hmi/kit"

do_install() {
    # /usr/lib/hmi/kit is where hmi-ui looks for fonts/ and icons/ on a panel
    # (native/hmi-ui/src/theme.c); provision_panel.py installs the same tree.
    install -d ${D}${nonarch_libdir}/hmi/kit/fonts
    install -d ${D}${nonarch_libdir}/hmi/kit/icons
    install -m 0644 ${S}/fonts/*.ttf      ${D}${nonarch_libdir}/hmi/kit/fonts/
    install -m 0644 ${S}/fonts/LICENSE.inter ${D}${nonarch_libdir}/hmi/kit/fonts/
    install -m 0644 ${S}/icons/*.png      ${D}${nonarch_libdir}/hmi/kit/icons/
    install -m 0644 ${S}/LICENSE.tabler   ${D}${nonarch_libdir}/hmi/kit/LICENSE.tabler
}
