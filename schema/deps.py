#!/usr/bin/env python3
"""
schema/deps.py -- what an application bundle needs on top of the platform
=========================================================================

Layer: shared (host tooling; imported by the desktop tool, runnable as a
script for the host CLI)

WHY THIS FILE EXISTS
--------------------
The platform gives a bundle an interpreter and a Qt binding. Everything else a
real application imports -- a PDF writer, a serial port library, an image
codec -- has to be on the panel already, and nothing checked that it was.

The failure mode is expensive out of proportion to the cause. A missing import
does not degrade the application, it kills it before its first window: the
process dies, systemd restarts it, and the panel sits in a restart loop showing
whatever ran before. The deploy either reports a health-check timeout minutes
later or, if the crash happens to fall on the wrong side of the readiness
settle window, reports success while the panel shows the old release. One
missing package on a board with no compiler and no package feed is a long
afternoon.

So the requirement is read off the application itself, before anything is sent.

WHAT IS COUNTED
---------------
Only files that would actually be packaged, via plan_bundle -- a `build/`
directory or anything named in .hmiignore is not shipped, so what it imports is
not the panel's problem. Of those, every absolute `import x` / `from x import`
is reduced to its top-level name, and three groups are dropped:

* the standard library, which the provisioned interpreter carries in full;
* modules the bundle itself provides, which is most of what a real application
  imports;
* the Qt bindings, which the platform installs and pins deliberately -- a
  bundle must never pull its own PySide over the one the panel was built with.

What is left is what pip has to supply. Import names and distribution names
disagree often enough (`serial` is pyserial, `PIL` is pillow) that the common
cases are mapped explicitly and anything unknown is assumed to install under
its own name, which is usually true and always visible in the console.

A requirements.txt in the bundle is honoured as well, and wins on version: a
scan can say "reportlab", only the author can say "reportlab>=4".
"""

import ast
import os
import sys
from typing import Dict, List, NamedTuple, Sequence, Set

from schema.bundle import plan_bundle

# Import name -> distribution name, for the cases where the two differ.
# Anything absent installs under the name it is imported by.
IMPORT_TO_DISTRIBUTION: Dict[str, str] = {
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "cairo": "pycairo",
    "canopen": "canopen",
    "cv2": "opencv-python-headless",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "fitz": "PyMuPDF",
    "gi": "PyGObject",
    "google": "protobuf",
    # The PyPI project named ``hid`` is a ctypes wrapper that still needs a
    # separately installed libhidapi shared library. ``hidapi`` ships the
    # importable native ``hid`` extension and is therefore the deployable
    # distribution on our self-contained panel runtime.
    "hid": "hidapi",
    "jwt": "PyJWT",
    "OpenGL": "PyOpenGL",
    "PIL": "pillow",
    "pkg_resources": "setuptools",
    "Crypto": "pycryptodome",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "usb": "pyusb",
    "yaml": "PyYAML",
    "zmq": "pyzmq",
}

# Supplied by the platform. A bundle that pip-installs its own PySide gets a
# different Qt from the one the panel's runtime was assembled against, which on
# this hardware means a binding compiled for desktop GL against a GLES board.
PLATFORM_PROVIDED = frozenset({
    "PySide6", "PySide2", "shiboken6", "shiboken2", "PyQt5", "PyQt6",
})

# Import guards for platforms the panel is not. An application that runs on the
# developer's Windows machine as well as on the panel legitimately imports
# these, and asking the panel's pip for them fails.
NOT_ON_LINUX = frozenset({
    "win32api", "win32com", "win32con", "win32gui", "win32file", "win32event",
    "pywintypes", "pythoncom", "winsound", "wmi",
})

# Python 2 spellings. These appear in real code only as the first half of a
# version fallback, and pip has nothing to offer for any of them.
PYTHON2_ONLY = frozenset({
    "ConfigParser", "Cookie", "HTMLParser", "Queue", "SimpleHTTPServer",
    "SocketServer", "StringIO", "Tkinter", "__builtin__", "cPickle",
    "cStringIO", "commands", "httplib", "thread", "urllib2", "urlparse",
})

# Runtimes the panel is not. `System` and `clr` are .NET, reachable only from
# IronPython or pythonnet.
NOT_CPYTHON = frozenset({"System", "clr", "java", "javax", "org"})

REQUIREMENTS_FILE = "requirements.txt"


class Dependency(NamedTuple):
    """One package the panel must have for this bundle to import."""

    module: str        # the name the application imports
    distribution: str  # the name pip installs it under


def _stdlib_names() -> Set[str]:
    """Return every module name the standard library provides.

    Returns:
        The stdlib module names, including builtins.

    The panel's interpreter and this one are both CPython 3.11+, built from
    python-build-standalone with the stdlib complete, so the host's own list is
    an accurate stand-in for the target's.
    """
    names = set(getattr(sys, "stdlib_module_names", ()))
    names.update(sys.builtin_module_names)
    names.add("__future__")
    return names


def local_modules(archive_names: Sequence[str]) -> Set[str]:
    """Return the module names the bundle supplies itself.

    Args:
        archive_names: paths inside the bundle, as plan_bundle reports them.

    Returns:
        Names that resolve inside the bundle and therefore need no package.

    Every module at any depth counts, not just the ones beside the entry
    point. Applications routinely put a package directory on sys.path at
    startup and then import its contents as top-level names, and a scan that
    only looked at the bundle root reported those as missing packages -- which
    would send pip after a name that exists on no index.
    """
    names: Set[str] = set()
    for name in archive_names:
        parts = name.split("/")
        for part in parts[:-1]:
            # A directory is importable whether or not it has __init__.py: the
            # application runs with its own directory on sys.path, and
            # namespace packages resolve.
            names.add(part)
        leaf = parts[-1]
        if leaf.endswith(".py"):
            names.add(leaf[:-3])
    names.discard("")
    return names


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Return True if this except clause handles a failed import."""
    caught = handler.type
    if caught is None:  # bare except
        return True
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    for name in names:
        if isinstance(name, ast.Name) and name.id in (
            "ImportError", "ModuleNotFoundError", "Exception", "BaseException"
        ):
            return True
    return False


def imported_names(path: str) -> Set[str]:
    """Return the top-level names one Python file requires at import time.

    Args:
        path: the file to read.

    Returns:
        Top-level import names; empty if the file will not parse, which is not
        this function's problem to report.

    Two kinds of import are left out. Relative ones resolve inside the bundle
    by definition. Guarded ones -- an import inside a try whose except catches
    ImportError -- are the author saying the module may be absent and the code
    copes, which is how every Python 2 fallback (`Queue`, `urlparse`) and every
    optional integration is written. Treating those as requirements sent pip
    after names that exist on no index.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError, ValueError):
        return set()

    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            _catches_import_error(handler) for handler in node.handlers
        ):
            for statement in node.body:
                for inner in ast.walk(statement):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        guarded.add(id(inner))

    names: Set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def declared_requirements(bundle_dir: str) -> List[str]:
    """Return the requirement lines the bundle states for itself.

    Args:
        bundle_dir: the bundle root.

    Returns:
        Requirement specifiers from requirements.txt, comments and blank lines
        removed. pip options (-r, --index-url) are left out: this list is
        passed to pip as arguments, not as a file.
    """
    path = os.path.join(bundle_dir, REQUIREMENTS_FILE)
    if not os.path.isfile(path):
        return []

    lines: List[str] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.split("#", 1)[0].strip()
                if line and not line.startswith("-"):
                    lines.append(line)
    except OSError:
        return []
    return lines


def _requirement_module(requirement: str) -> str:
    """Return the import name a requirement specifier is expected to provide."""
    name = requirement
    for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", " "):
        name = name.split(separator, 1)[0]
    name = name.strip()
    reverse = {dist.lower(): module for module, dist in IMPORT_TO_DISTRIBUTION.items()}
    return reverse.get(name.lower(), name.replace("-", "_"))


def dependencies(bundle_dir: str) -> List[Dependency]:
    """Work out every package this bundle needs the panel to have.

    Args:
        bundle_dir: the bundle root.

    Returns:
        One Dependency per package, sorted by module name. A requirements.txt
        entry replaces the scanned entry for the same module, so a pinned
        version survives.
    """
    entries, _total = plan_bundle(bundle_dir)
    archive_names = [archive for _path, archive in entries]
    provided = local_modules(archive_names)
    stdlib = _stdlib_names()

    modules: Set[str] = set()
    for path, archive in entries:
        if archive.endswith(".py"):
            modules |= imported_names(path)

    wanted = {
        module
        for module in modules
        if module
        and module not in provided
        and module not in stdlib
        and module not in PLATFORM_PROVIDED
        and module not in NOT_ON_LINUX
        and module not in PYTHON2_ONLY
        and module not in NOT_CPYTHON
        and not module.startswith("_")
    }

    found: Dict[str, str] = {
        module: IMPORT_TO_DISTRIBUTION.get(module, module) for module in wanted
    }

    # An explicit requirement outranks the scan: it may carry a version, and it
    # may name something imported dynamically that no scan can see.
    for requirement in declared_requirements(bundle_dir):
        module = _requirement_module(requirement)
        if module in provided or module in PLATFORM_PROVIDED:
            continue
        found[module] = requirement

    return sorted(
        (Dependency(module, distribution) for module, distribution in found.items()),
        key=lambda dependency: dependency.module.lower(),
    )


def main(argv: Sequence[str]) -> int:
    """Print one `module  distribution` line per dependency of a bundle."""
    if len(argv) != 2:
        sys.stderr.write("usage: python -m schema.deps <bundle-dir>\n")
        return 2
    for dependency in dependencies(argv[1]):
        sys.stdout.write(f"{dependency.module}\t{dependency.distribution}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
