# recipes-hmi/hmi-ui-kit/hmi-ui-kit_1.0.bb
#
# Packages the Shadcn-derived QML component kit, the design-system token
# file, and the vendored Tabler icon registry so that BYOA application
# packages can declare:
#
#     import Shadcn 1.0
#
# without depending on the HMI loader itself.  This is a deliberately
# separate package because customer application .opk/.rpm packages list
# hmi-ui-kit in their own RDEPENDS; they do not need to carry hmi-gui as a
# dependency (some integrators run a C++ loader that still uses this QML
# kit).
#
# Target paths (CONTRACT section 3 and section 11):
#   /usr/lib/hmi/qml/Shadcn/    QML module directory (all .qml + qmldir)
#   /usr/lib/hmi/qml/Shadcn/tokens.json
#                               design-system colour/spacing tokens
#   /usr/lib/hmi/qml/Shadcn/LICENSE.tabler
#                               MIT license for Tabler icons

DESCRIPTION = "BYOA HMI Shadcn QML component kit and Tabler icon registry"
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
    file://Shadcn \
    file://tokens.json \
    file://LICENSE.tabler \
"

# S override for styhead (Yocto 5.1+): see hmi-core_1.0.bb for explanation.
S:styhead = "${UNPACKDIR}"
S         = "${WORKDIR}"

# ---------------------------------------------------------------------------
# Architecture decision: inherit allarch.
#
# hmi-ui-kit contains only QML source files, JSON, and JS/PATH DATA. There
# are no compiled binaries and no arch-specific RDEPENDS.  allarch tells
# bitbake to produce a single PACKAGE_ARCH=all package that can be shared
# across all target architectures in a multi-arch build farm, saving
# storage and CI time.
# ---------------------------------------------------------------------------
inherit allarch

# ---------------------------------------------------------------------------
# RDEPENDS
#
# qtdeclarative-qmlplugins  - the QML engine must be present to load the
#                             Shadcn module; this is the arch-specific
#                             runtime package.  Note: declaring an
#                             arch-specific RDEPENDS on an allarch recipe
#                             is correct - it does NOT make the package
#                             itself arch-specific.
# qt6-fonts-noto            - Shadcn components reference "Noto Sans" by
#                             name in their style properties; without the
#                             font package the text falls back to an
#                             undefined system font.  Replace with your
#                             brand font package if needed.
# ---------------------------------------------------------------------------
RDEPENDS:${PN} = " \
    qtdeclarative-qmlplugins \
    qt6-fonts-noto \
"

# ---------------------------------------------------------------------------
# FILES
#
# /usr/lib/hmi/qml/ is under ${nonarch_libdir}/hmi/ which is inside the default
# packaging path.  We add an explicit glob anyway so that any future split
# into -dev or -staticdev does not accidentally absorb the files.
# ---------------------------------------------------------------------------
FILES:${PN} += "${nonarch_libdir}/hmi/qml/Shadcn"

do_install() {
    # -----------------------------------------------------------------------
    # Create the module directory.
    # /usr/lib/hmi/qml/Shadcn is the import path registered with the QML
    # engine by hmi-gui. (The GUI loader adds it via engine.addImportPath).
    # The directory name must match the module name in the qmldir file.
    # -----------------------------------------------------------------------
    install -d ${D}${nonarch_libdir}/hmi/qml/Shadcn

    # -----------------------------------------------------------------------
    # Install all QML component files from the copied Shadcn source tree.
    # We use `cp -r` rather than individual `install` calls because the
    # component kit may have subdirectories.
    # The trailing /. on the source copies directory contents, not the
    # directory itself.
    # -----------------------------------------------------------------------
    cp -r ${S}/Shadcn/. ${D}${nonarch_libdir}/hmi/qml/Shadcn/

    # -----------------------------------------------------------------------
    # Install the design-system token file alongside the QML components.
    # tokens.json is read at QML startup via a small JSON loader component
    # inside the Shadcn module; it must live inside the module directory.
    # -----------------------------------------------------------------------
    install -m 0644 ${S}/tokens.json ${D}${nonarch_libdir}/hmi/qml/Shadcn/tokens.json

    # -----------------------------------------------------------------------
    # Install the Tabler icon license.
    # The icons are vendored as PATH DATA within TablerIcons.js, not as SVGs.
    # Only the JS registry is needed on the target, along with its MIT notice.
    # -----------------------------------------------------------------------
    install -m 0644 ${S}/LICENSE.tabler ${D}${nonarch_libdir}/hmi/qml/Shadcn/LICENSE.tabler
}