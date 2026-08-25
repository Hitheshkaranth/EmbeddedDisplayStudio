# recipes-hmi/hmi-gui/hmi-gui_1.0.bb
#
# Packages the GUI loader Python entry-point and the shell QML file that
# hosts dynamically-loaded BYOA application views.
#
# Target paths (CONTRACT section 3):
#   /usr/lib/hmi/gui/               directory for the GUI loader
#   /usr/lib/hmi/gui/main.py        Python/PySide6 GUI loader
#   /usr/lib/hmi/gui/tagengine.py   Python/PySide6 TagEngine for daemon comms
#   /usr/lib/hmi/shell/             directory for the QML shell
#   /usr/lib/hmi/shell/Shell.qml    top-level QML shell
#   /usr/lib/hmi/shell/Fallback.qml fallback QML screen
#
# The shell lives beside gui/, not inside it: main.py resolves it as
# Path(__file__).parent.parent / "shell" / "Shell.qml".
#
# ---------------------------------------------------------------------------
# DEPENDENCY NOTE - PySide6 / meta-qt6
# ---------------------------------------------------------------------------
# This recipe depends on python3-pyside6 which is provided by meta-qt6
# (https://code.qt.io/cgit/yocto/meta-qt6.git).  PySide6 is NOT present
# in the Toradex Reference Multimedia Image by default.  Integrators who
# cannot take the meta-qt6 dependency (licence constraints, image-size
# budgets, or corporate policy) should replace this loader with a C++
# Qt6/QML executable that embeds a QQmlEngine and calls
# QQmlComponent::loadUrl() dynamically.  The contract's install path
# (/usr/lib/hmi/gui/) remains unchanged; only the files inside change.
# ---------------------------------------------------------------------------

DESCRIPTION = "BYOA HMI GUI loader (Python/PySide6) and top-level QML shell"
HOMEPAGE = "https://example.com/byoa-hmi"
SECTION = "hmi"

LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

# ---------------------------------------------------------------------------
# Source files - see yocto/README.md for the ln -s commands that populate
# the files/ directory from ../../../gui/ in the repo tree.
# For production, switch to git:// + SRCREV.
# ---------------------------------------------------------------------------
SRC_URI = " \
    file://main.py \
    file://tagengine.py \
    file://Shell.qml \
    file://Fallback.qml \
"

# S override for styhead (Yocto 5.1+): see hmi-core_1.0.bb for explanation.
S:styhead = "${UNPACKDIR}"
S         = "${WORKDIR}"

# ---------------------------------------------------------------------------
# Architecture decision: do NOT inherit allarch.
# python3-pyside6 and the Qt6 runtime packages are architecture-specific.
# Marking this recipe allarch while depending on them would trigger a QA
# RPROVIDES_allarch error.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# RDEPENDS - runtime dependencies for the Python/PySide6 GUI loader
#
# python3-core          - interpreter
# python3-pyside6       - PySide6 Python bindings; from meta-qt6.
#                         See DEPENDENCY NOTE above.
#
# The following Qt6 packages are required for a Wayland QML application.
# All are provided by meta-qt6:
#
# qtbase               - QCoreApplication, QGuiApplication; base runtime
# qtdeclarative        - QML engine (QtQml + QtQuick modules)
# qtdeclarative-qmlplugins
#                      - Ships the built-in QML module .so files (QtQuick,
#                        QtQml.Models, etc.); without this the QML engine
#                        cannot resolve `import QtQuick 6`
# qtwayland            - Qt Wayland client backend; replaces xcb on Weston
# qtwayland-compositor - Not needed by the loader (client only); listed for
#                        clarity - DO NOT add this to RDEPENDS.
# qtwayland-plugins    - Installs the wayland-egl and wayland-brcm platform
#                        plugins; required so QPA can find a Wayland backend
# qt6-fonts-noto       - Noto fallback fonts; prevents "no fonts found"
#                        warnings on a minimal rootfs - adjust to your
#                        brand font package if different
# ---------------------------------------------------------------------------
# The Python stdlib is split into subpackages on a Yocto image: python3-core
# alone ships neither json nor argparse nor logging.  main.py and tagengine.py
# import every module listed below, and a missing one is a ModuleNotFoundError
# at service start rather than a build failure -- so the closure is spelled out
# instead of assumed.  Keep it in step with the imports in gui/hmi_loader/.
RDEPENDS:${PN} = " \
    python3-core \
    python3-argparse \
    python3-json \
    python3-logging \
    python3-pathlib \
    python3-re \
    python3-pyside6 \
    qtbase \
    qtdeclarative \
    qtdeclarative-qmlplugins \
    qtwayland \
    qtwayland-plugins \
    qt6-fonts-noto \
"

# ---------------------------------------------------------------------------
# FILES - the gui/ subdirectory is under ${nonarch_libdir}/hmi/ which is in the
# default packaging paths.  No explicit FILES addition is required unless
# bitbake splits hmi-gui-dev or hmi-gui-doc automatically and misroutes
# the files; adding the explicit glob below is defensive.
# ---------------------------------------------------------------------------
FILES:${PN} += "${nonarch_libdir}/hmi/gui/* ${nonarch_libdir}/hmi/shell/*"

do_install() {
    # -----------------------------------------------------------------------
    # /usr/lib/hmi/gui/ - GUI loader directory.
    # We use ${nonarch_libdir} (resolves to /usr/lib on all architectures)
    # rather than ${libdir} so that multilib builds do not violate the
    # CONTRACT, which fixes these arch-independent paths at /usr/lib/hmi.
    # -----------------------------------------------------------------------
    install -d ${D}${nonarch_libdir}/hmi/gui

    # Install the Python loader and tag engine.  Mode 0644: the loader is
    # started as an argument to the interpreter by hmi-gui-launch, never
    # executed directly, so the execute bit is not required on the file.
    install -m 0644 ${S}/main.py       ${D}${nonarch_libdir}/hmi/gui/main.py
    install -m 0644 ${S}/tagengine.py  ${D}${nonarch_libdir}/hmi/gui/tagengine.py

    # -----------------------------------------------------------------------
    # /usr/lib/hmi/shell/ - the QML shell and fallback screen.
    #
    # This directory is NOT interchangeable with gui/.  main.py resolves its
    # shell as Path(__file__).parent.parent / "shell" / "Shell.qml", i.e.
    # /usr/lib/hmi/shell/Shell.qml, and deploy/provision_panel.py installs it
    # there.  These two files were previously installed into gui/ alongside
    # the loader, where the loader never looks: the image booted, the loader
    # logged "Failed to load shell QML. Exiting.", and Restart=always turned
    # that into a boot loop with no UI and no fallback screen.
    # -----------------------------------------------------------------------
    install -d ${D}${nonarch_libdir}/hmi/shell
    install -m 0644 ${S}/Shell.qml     ${D}${nonarch_libdir}/hmi/shell/Shell.qml
    install -m 0644 ${S}/Fallback.qml  ${D}${nonarch_libdir}/hmi/shell/Fallback.qml
}