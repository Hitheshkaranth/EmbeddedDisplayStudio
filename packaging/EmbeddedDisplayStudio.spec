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


# SPECPATH is injected by PyInstaller and is this file's directory. Deriving
# the root from it rather than from the working directory means the build does
# not depend on where it was launched from -- and paths inside the spec are
# resolved relative to the spec, so they must be absolute.
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

datas = [
    (os.path.join(REPO_ROOT, "tools", "hmi_deployer", "resources"),
     os.path.join("tools", "hmi_deployer", "resources")),
    (os.path.join(REPO_ROOT, "ui", "tokens.json"), "ui"),
    (os.path.join(REPO_ROOT, "ui", "icons"), os.path.join("ui", "icons")),
    (os.path.join(REPO_ROOT, "ui", "qml"), os.path.join("ui", "qml")),
]

a = Analysis(
    [os.path.join(REPO_ROOT, "main.py")],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "gui")],
    binaries=[],
    datas=datas,
    # tagengine is reached through a sys.path insert at import time, and
    # schema.deps only through main.py's --deps-scan dispatch; neither is
    # visible to the dependency graph.
    # ...and the standard library in full, for the customer application the
    # preview hosts, whose imports nothing can see ahead of time.
    hiddenimports=["hmi_loader.tagengine", "schema.deps", "pip", *_stdlib_modules()],
    hookspath=[],
    runtime_hooks=[],
    # The Studio drives the panel over ssh and previews Qt Widgets and QML.
    # It has no use for the scientific stack, and excluding it keeps the
    # download to something a machine builder will actually wait for.
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pytest", "PySide2"],
    noarchive=False,
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
