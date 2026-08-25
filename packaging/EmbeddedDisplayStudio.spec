# PyInstaller spec for EmbeddedDisplay Studio.
#
# Build from the repository root:
#     python -m PyInstaller packaging/EmbeddedDisplayStudio.spec --noconfirm
#
# The data layout below is not cosmetic. The Studio finds its assets relative
# to __file__ -- shadcn.py reads ../tokens.json, ../icons/tabler_icons.py and
# ../qml, and the deployer package reads its own resources/ directory -- so the
# tree inside the bundle has to mirror the repository or those lookups miss.
#
# tabler_icons.py ships as data, not as a module: it is loaded by path through
# importlib, and a frozen module would have no path to load.

import os

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
    [os.path.join(REPO_ROOT, "packaging", "studio_entry.py")],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "gui")],
    binaries=[],
    datas=datas,
    # tagengine is reached through a sys.path insert at import time, which the
    # dependency graph cannot see.
    hiddenimports=["hmi_loader.tagengine"],
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
