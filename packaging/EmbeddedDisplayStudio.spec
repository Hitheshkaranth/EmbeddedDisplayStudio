# PyInstaller spec for EmbeddedDisplay Studio.
#
# Build from the repository root:
#     python -m PyInstaller packaging/EmbeddedDisplayStudio.spec --noconfirm
#
# main.py is the entry point from a checkout and the script frozen here, so
# there is one way in rather than two. It also carries the sub-commands the
# packaged Studio uses to re-execute itself for the preview child and the
# dependency scan -- see its module docstring.
#
# The data layout below is not cosmetic. The Studio finds its assets relative
# to __file__ -- shadcn.py reads ../tokens.json, ../icons/tabler_icons.py and
# ../qml, and the deployer package reads its own resources/ directory -- so the
# tree inside the bundle has to mirror the repository or those lookups miss.
#
# tabler_icons.py ships as data, not as a module: it is loaded by path through
# importlib, and a frozen module would have no path to load.

import importlib.util
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


def _stdlib_modules():
    """Every importable top-level standard-library module.

    PyInstaller bundles what static analysis can reach, and the customer's
    application is not reachable: the preview loads it at runtime through
    runpy, so none of its imports are ever seen. The frozen runtime therefore
    carried only what the Studio itself imports, and a customer application
    doing something as ordinary as loading a stylesheet died on
    `No module named 'pkgutil'`.

    The whole standard library is a few megabytes against a 160 MB download,
    and it is the difference between previewing an arbitrary Qt application
    and previewing only the ones that happen to import what the Studio does.
    Names are filtered through find_spec because sys.stdlib_module_names is
    the same list on every platform and includes Unix-only modules.
    """
    found = []
    for name in sorted(getattr(sys, "stdlib_module_names", ())):
        if name.startswith("_"):
            continue
        try:
            if importlib.util.find_spec(name) is not None:
                found.append(name)
        except (ImportError, ValueError, AttributeError):
            continue
    return found


# Qt modules too large to carry for an application that might use them
# (WebEngine is ~200 MB with its resources; WebView sits on it), and the
# Designer plugin API, which applications do not import (QUiLoader is in
# QtUiTools).
_PYSIDE6_SKIP = ("QtWebEngine", "QtWebView", "QtDesigner")


def _pyside6_modules():
    """Every installed PySide6 Qt module but the ones in _PYSIDE6_SKIP.

    The same gap as the standard library: the Studio's own imports decide
    which Qt modules PyInstaller collects, so a customer application loading
    a .ui file died in the preview on `No module named 'PySide6.QtUiTools'`.
    """
    import pkgutil
    import PySide6
    return [f"PySide6.{m.name}" for m in pkgutil.iter_modules(PySide6.__path__)
            if m.name.startswith("Qt") and not m.name.startswith(_PYSIDE6_SKIP)]


# SPECPATH is injected by PyInstaller and is this file's directory. Deriving
# the root from it rather than from the working directory means the build does
# not depend on where it was launched from -- and paths inside the spec are
# resolved relative to the spec, so they must be absolute.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# The panel's own renderer, headless, so the Studio previews a design as
# the glass draws it. It lands at _internal/hmi-ui/hmi-ui.exe, which is
# where designer.preview.find_hmi_ui looks in a frozen Studio. A build
# without it (native/hmi-ui/win64/build.sh not run) still ships: the Studio
# then previews with Qt/QML, as it did before the port.
binaries = []
_hmi_ui = os.path.join(REPO_ROOT, "native", "hmi-ui", "out", "win64", "hmi-ui.exe")
if os.path.isfile(_hmi_ui):
    binaries.append((_hmi_ui, "hmi-ui"))
else:
    print(f"warning: {_hmi_ui} not found; the packaged Studio will preview with "
          "Qt/QML instead of hmi-ui (build it with native/hmi-ui/win64/build.sh)",
          file=sys.stderr)

datas = [
    (os.path.join(REPO_ROOT, "tools", "hmi_deployer", "resources"),
     os.path.join("tools", "hmi_deployer", "resources")),
    (os.path.join(REPO_ROOT, "ui", "tokens.json"), "ui"),
    (os.path.join(REPO_ROOT, "ui", "icons"), os.path.join("ui", "icons")),
    (os.path.join(REPO_ROOT, "ui", "qml"), os.path.join("ui", "qml")),
    # The runtime's widget sources: the Code section shows the C that draws
    # each widget on the panel (designer/code/code_model.py widget_c).
    (os.path.join(REPO_ROOT, "native", "hmi-ui", "src", "widgets"),
     os.path.join("native", "hmi-ui", "src", "widgets")),
    # The design presets read an exemplar off disk when a brief matches one
    # (tools/hmi_deployer/design_presets.py, _TEMPLATES_DIR). Without these a
    # hand-written brief raised FileNotFoundError inside the send path.
    (os.path.join(REPO_ROOT, "designer", "templates"),
     os.path.join("designer", "templates")),
    # What a Qt bundle's deploy installs on a Qt-free panel: the Qt app
    # launcher, its unit and defaults, and the runtime-aware hmi-install
    # (tools/hmi_deployer/qt_deploy.py, LAUNCHER_FILES).
    (os.path.join(REPO_ROOT, "native", "hmi-gui", "target"),
     os.path.join("native", "hmi-gui", "target")),
    (os.path.join(REPO_ROOT, "target", "bin", "hmi-install"),
     os.path.join("target", "bin")),
    # pip's vendored CA bundle (pip/_vendor/certifi/cacert.pem): without it
    # the preview's installer cannot reach PyPI over HTTPS.
    *collect_data_files("pip"),
]

a = Analysis(
    [os.path.join(REPO_ROOT, "main.py")],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "gui")],
    binaries=binaries,
    datas=datas,
    # tagengine is reached through a sys.path insert at import time, and
    # schema.deps only through main.py's --deps-scan dispatch; neither is
    # visible to the dependency graph.
    # pip in full, because it picks its commands by name through importlib
    # ("pip" alone carried none of them, and the preview's installer died on
    # `No module named 'pip._internal.commands.install'`). And the standard
    # library and PySide6 in full, for the customer application the preview
    # hosts, whose imports nothing can see ahead of time.
    hiddenimports=["hmi_loader.tagengine", "schema.deps", *collect_submodules("pip"),
                   *_stdlib_modules(), *_pyside6_modules()],
    hookspath=[],
    runtime_hooks=[],
    # The Studio drives the panel over ssh and previews Qt Widgets and QML.
    # It has no use for the scientific stack, and excluding it keeps the
    # download to something a machine builder will actually wait for.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "PySide2"],
    noarchive=False,
    # pip as source files on disk rather than inside the archive: its
    # vendored distlib finds its resources through the module's loader and
    # has no finder for PyInstaller's ("Unable to locate finder for
    # 'pip._vendor.distlib'").
    module_collection_mode={"pip": "py"},
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EmbeddedDisplayStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A deployment console is a desktop application; a console window behind it
    # would be noise. Its own Console Output panel carries everything the panel
    # says.
    console=False,
    disable_windowed_traceback=False,
    icon=os.path.join(REPO_ROOT, "tools", "hmi_deployer", "resources", "logo.ico"),
)
