"""
tools/hmi_deployer/deployer.py
Layer: 3 (Host Deployer)
Purpose: Handles the app bundle validation, packaging, and the sequential install
flow (CONTRACT section 4, 6).
"""
import json
import os
import shutil
import tarfile
import hashlib
import fnmatch
from typing import Tuple, List, Dict, Any, Optional
import datetime

from PySide6.QtCore import QObject, QThread, Signal

# Bundle packing rules live in schema/bundle.py, which deploy_to_hmi.sh also
# calls, so both tools produce byte-identical tarballs from the same directory.
# These used to be implemented here only, which made the README's claim that
# build outputs and caches are excluded automatically true of this tool and
# false of the CLI.
from schema.bundle import (  # noqa: E402  (import placed with its explanation)
    DEFAULT_EXCLUDES,
    HMIIGNORE,
    MAX_BUNDLE_BYTES,
    BundleTooLargeError,
    load_excludes,
    package_bundle,
    plan_bundle,
)

# CONTRACT section 4 validation lives in schema/manifest.py, which the host CLI
# and the target installer also call. Re-exported so existing callers keep
# importing deployer.validate_bundle, while there is one implementation to keep
# correct.
#
# The three copies had drifted apart in both directions: this tool required
# 'qt', 'screen' and 'tags_required' that the other two ignored -- so the
# manifest printed in the README was rejected here -- while never checking
# 'version', which both of the others required.
from schema.manifest import (  # noqa: E402
    detect_qt_binding,
    screen_of,
    validate_bundle,
)

class PackageWorker(QThread):
    """
    Packs a bundle into its tarball off the UI thread.

    Packaging walks every file in the bundle, sums their sizes and writes a
    compressed archive. On a real application that is seconds of solid work,
    and running it inline froze the window the instant Deploy was pressed:
    Windows marks a window that has not pumped messages for five seconds as
    "Not Responding", so the tool looked hung at exactly the moment it had the
    most to say for itself.

    Signals:
        done(str, str): tarball path, checksum sidecar path.
        failed(str, str): reason kind ('too-large' or 'error') and its message.
    """

    done = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        bundle_dir: str,
        out_dir: str,
        discard_dir: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        """
        Args:
            bundle_dir: the loaded bundle to pack.
            out_dir: an existing empty directory to write the tarball into.
            discard_dir: the previous deploy's directory, deleted before
                packing. Removing up to 500 MB is itself a UI-thread stall, so
                it happens here rather than in the caller.
            parent: parent QObject.
        """
        super().__init__(parent)
        self.bundle_dir = bundle_dir
        self.out_dir = out_dir
        self.discard_dir = discard_dir

    def run(self) -> None:
        """Pack the bundle, reporting either the artefacts or why not."""
        try:
            if self.discard_dir:
                shutil.rmtree(self.discard_dir, ignore_errors=True)
            tar_path, sha_path = package_bundle(self.bundle_dir, self.out_dir)
        except BundleTooLargeError as exc:
            self.failed.emit("too-large", str(exc))
            return
        except Exception as exc:
            self.failed.emit("error", str(exc))
            return
        self.done.emit(tar_path, sha_path)


def detect_bundle(bundle_dir: str) -> dict:
    """
    Infers a manifest for a directory that does not have one.

    Most real applications were not written for this platform and have no
    manifest.json; refusing them outright makes the tool useless for the very
    thing it exists to do. This inspects the directory and proposes a manifest
    the user can accept, so an existing Qt app can be imported as-is.

    Detection order matters: a project containing both main.qml and main.py is
    treated as QML, because on this platform a QML entry is the lighter-weight
    integration (it runs inside the shell that is already up) and a Python entry
    replaces the whole GUI process.

    Args:
        bundle_dir: directory to inspect.

    Returns:
        A manifest dict ready to be written, or {} when no plausible entry point
        could be found (in which case the caller should tell the user what is
        missing rather than guessing).
    """
    import re

    # Name comes from the folder, lowercased and stripped to the contract's
    # character set, since that is what both installers enforce.
    raw = os.path.basename(os.path.normpath(bundle_dir))
    name = re.sub(r"[^a-z0-9._-]", "-", raw.lower()).strip("-.") or "imported-app"
    name = name[:64]

    entry = None
    runtime = None
    for candidate in ("main.qml", "Main.qml", "app.qml"):
        if os.path.isfile(os.path.join(bundle_dir, candidate)):
            entry, runtime = candidate, "qml"
            break
    if entry is None:
        for candidate in ("main.py", "app.py", "__main__.py"):
            if os.path.isfile(os.path.join(bundle_dir, candidate)):
                entry, runtime = candidate, "python"
                break
    if entry is None:
        return {}

    manifest = {
        "schema": 1,
        "name": name,
        "version": "0.1.0",
        "entry": entry,
        "runtime": runtime,
        "screen": {"width": 1280, "height": 800},
        "tags_required": [],
        "qt": ">=6.5",
    }

    if runtime == "python":
        binding = detect_qt_binding(bundle_dir, entry)
        manifest["qt_binding"] = binding
        if binding == "pyside2":
            # A Qt5 app; saying ">=6.5" here would be a lie the panel acts on.
            manifest["qt"] = ">=5.15"

    return manifest


def write_manifest(bundle_dir: str, manifest: dict) -> str:
    """
    Writes a manifest into a bundle directory.

    Args:
        bundle_dir: the bundle root.
        manifest: the manifest object to serialise.

    Returns:
        The path written.

    newline="\\n" is deliberate: the target parses this file, and the repository
    is LF-only.
    """
    path = os.path.join(bundle_dir, "manifest.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return path
