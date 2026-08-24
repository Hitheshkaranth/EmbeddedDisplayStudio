"""
tools/hmi_deployer/deployer.py
Layer: 3 (Host Deployer)
Purpose: Handles the app bundle validation, packaging, and the sequential install
flow (CONTRACT section 4, 6).
"""
import json
import os
import tarfile
import hashlib
import fnmatch
from typing import Tuple, List, Dict, Any
import datetime

# Patterns never worth sending to a panel. These are build outputs, caches and
# VCS metadata: every one of them is regenerated or irrelevant on the target,
# and a real application folder is full of them. Without this the tool packages
# whatever happens to be sitting in the directory, which for an app that has
# ever been built locally means shipping tens or hundreds of megabytes of
# nothing over a field link.
DEFAULT_EXCLUDES = (
    ".git", ".svn", ".hg",
    "__pycache__", "*.pyc", "*.pyo", "*.pyd",
    ".venv", "venv", "env",
    "node_modules",
    "build", "dist", "*.egg-info",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    ".DS_Store", "Thumbs.db",
    ".hmiignore",
)

# Hard ceiling on what may be sent, matching MAX_BUNDLE_SIZE in
# target/bin/hmi-install. Checking it here as well means an oversized bundle is
# refused in a second on the laptop, naming the files responsible, instead of
# after a long upload the target then rejects.
MAX_BUNDLE_BYTES = 524288000  # 500 MB

# Name of the per-bundle exclude file. One glob per line, '#' starts a comment.
# This is how an application says "these files are mine but they are not part
# of what runs on the panel" -- source archives, datasheets, capture logs.
HMIIGNORE = ".hmiignore"


class BundleTooLargeError(Exception):
    """Raised when a bundle exceeds what the target will accept."""


def load_excludes(bundle_dir: str) -> List[str]:
    """
    Returns the exclude patterns in force for a bundle.

    Args:
        bundle_dir: the bundle root.

    Returns:
        DEFAULT_EXCLUDES plus any patterns from the bundle's .hmiignore.
    """
    patterns = list(DEFAULT_EXCLUDES)
    ignore_path = os.path.join(bundle_dir, HMIIGNORE)
    if os.path.isfile(ignore_path):
        with open(ignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line.rstrip("/"))
    return patterns


def _excluded(rel_path: str, name: str, patterns: List[str]) -> bool:
    """
    Tests one path against the exclude patterns.

    Args:
        rel_path: path relative to the bundle root, with forward slashes.
        name: the final path component.
        patterns: glob patterns.

    Returns:
        True if the path should be left out of the bundle.

    A pattern matches either the bare name (so "__pycache__" catches it at any
    depth) or the full relative path (so "docs/big.zip" can be targeted).
    """
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
            return True
    return False


def plan_bundle(bundle_dir: str) -> Tuple[List[Tuple[str, str]], int]:
    """
    Works out exactly what would be packaged, without packaging it.

    Args:
        bundle_dir: the bundle root.

    Returns:
        (entries, total_bytes) where entries is a list of
        (absolute_path, archive_name) in a stable sorted order.
    """
    patterns = load_excludes(bundle_dir)
    entries: List[Tuple[str, str]] = []
    total = 0

    for dirpath, dirnames, filenames in os.walk(bundle_dir):
        rel_dir = os.path.relpath(dirpath, bundle_dir).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        # Prune excluded directories in place so os.walk does not descend into
        # them -- the point is to never stat a 60 GB tree, not to skip it later.
        dirnames[:] = sorted(
            d for d in dirnames
            if not _excluded(f"{rel_dir}/{d}".lstrip("/"), d, patterns)
        )

        for name in sorted(filenames):
            rel = f"{rel_dir}/{name}".lstrip("/")
            if _excluded(rel, name, patterns):
                continue
            full = os.path.join(dirpath, name)
            if not os.path.isfile(full) or os.path.islink(full):
                # Symlinks are archived, but their target size is not counted.
                if os.path.islink(full):
                    entries.append((full, rel))
                continue
            entries.append((full, rel))
            total += os.path.getsize(full)

    return entries, total


def _describe_largest(entries: List[Tuple[str, str]], count: int = 5) -> str:
    """Formats the biggest entries, for an actionable size error."""
    sized = []
    for full, rel in entries:
        try:
            sized.append((os.path.getsize(full), rel))
        except OSError:
            continue
    sized.sort(reverse=True)
    return "\n".join(
        f"    {size / (1024 * 1024):9.1f} MB  {rel}" for size, rel in sized[:count]
    )

def validate_bundle(bundle_dir: str) -> Tuple[bool, List[str]]:
    """
    Validates a raw app directory against CONTRACT section 4.
    
    Args:
        bundle_dir: Path to the app folder.
        
    Returns:
        (passed, list_of_error_strings_or_success_message).
    """
    errors = []
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    
    if not os.path.isfile(manifest_path):
        return False, ["manifest.json is missing from the bundle root."]
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return False, [f"manifest.json is not valid JSON: {e}"]
        
    if manifest.get("schema") != 1:
        errors.append("manifest.json: 'schema' must be exactly 1.")
        
    name = manifest.get("name", "")
    if not isinstance(name, str) or not name:
        errors.append("manifest.json: 'name' is missing or not a string.")
    else:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", name):
            errors.append("manifest.json: 'name' must be lowercase alphanumeric, dash, dot, or underscore (up to 64 chars).")
            
    entry = manifest.get("entry", "")
    if not isinstance(entry, str) or not entry:
        errors.append("manifest.json: 'entry' is missing or not a string.")
    elif ".." in entry:
        errors.append("manifest.json: 'entry' must not contain '..'.")
    else:
        entry_path = os.path.join(bundle_dir, entry)
        if not os.path.isfile(entry_path):
            errors.append(f"manifest.json: 'entry' file '{entry}' does not exist in the bundle.")
            
    screen = manifest.get("screen")
    if not isinstance(screen, dict) or "width" not in screen or "height" not in screen:
        errors.append("manifest.json: 'screen' must be an object with 'width' and 'height'.")
        
    tags = manifest.get("tags_required")
    if not isinstance(tags, list):
        errors.append("manifest.json: 'tags_required' must be a list of strings.")
        
    qt_ver = manifest.get("qt")
    if not isinstance(qt_ver, str):
        errors.append("manifest.json: 'qt' must be a string (e.g., '>=6.5').")

    # Runtime kind. Absent means "qml", which is what every bundle written
    # before this field existed is, so old manifests keep validating unchanged.
    runtime = manifest.get("runtime", "qml")
    if runtime not in ("qml", "python"):
        errors.append("manifest.json: 'runtime' must be 'qml' or 'python'.")
    elif isinstance(entry, str) and entry:
        # The two runtimes are loaded in fundamentally different ways, so a
        # mismatched extension is a deployment that fails on the panel rather
        # than here: a QML entry is loaded into the shell's existing engine,
        # while a python entry is exec'd as the GUI process itself.
        if runtime == "qml" and not entry.endswith(".qml"):
            errors.append(f"manifest.json: runtime 'qml' requires a .qml entry, got '{entry}'.")
        if runtime == "python" and not entry.endswith(".py"):
            errors.append(f"manifest.json: runtime 'python' requires a .py entry, got '{entry}'.")

    if errors:
        return False, errors
    kind = "Qt Quick (QML)" if runtime == "qml" else "Python (Qt Widgets)"
    return True, [f"Bundle is valid - {kind}."]


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

    return {
        "schema": 1,
        "name": name,
        "version": "0.1.0",
        "entry": entry,
        "runtime": runtime,
        "screen": {"width": 1280, "height": 800},
        "tags_required": [],
        "qt": ">=6.5",
    }


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

def package_bundle(bundle_dir: str, output_dir: str) -> Tuple[str, str]:
    """
    Creates a gzip tarball of the bundle and its SHA256 checksum.

    Args:
        bundle_dir: Path to the app folder to pack.
        output_dir: Path where the .tar.gz and .sha256 should be placed.

    Returns:
        (tar_path, sha256_path)

    Raises:
        BundleTooLargeError: if the selected files exceed what the target
            accepts. The message names the largest offenders and points at
            .hmiignore, because the fix is always "this file is not part of the
            application" rather than anything the tool can decide by itself.

    Build outputs, caches and anything listed in the bundle's .hmiignore are
    left out; see plan_bundle.
    """
    with open(os.path.join(bundle_dir, "manifest.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    name = manifest.get("name", "app")

    entries, total = plan_bundle(bundle_dir)
    if total > MAX_BUNDLE_BYTES:
        raise BundleTooLargeError(
            f"Bundle is {total / (1024 * 1024):.0f} MB before compression; the panel "
            f"accepts at most {MAX_BUNDLE_BYTES / (1024 * 1024):.0f} MB.\n"
            f"Largest files:\n{_describe_largest(entries)}\n"
            f"List anything that is not part of the running application in "
            f"{os.path.join(bundle_dir, HMIIGNORE)} (one glob per line)."
        )

    # Release id: <name>-<UTC yyyymmddTHHMMSSZ>
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    release_id = f"{name}-{timestamp}"

    tar_name = f"{release_id}.tar.gz"
    tar_path = os.path.join(output_dir, tar_name)

    with tarfile.open(tar_path, "w:gz") as tar:
        for full, arcname in entries:
            tar.add(full, arcname=arcname, recursive=False)

    # Compute SHA256
    sha256_hash = hashlib.sha256()
    with open(tar_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    checksum = sha256_hash.hexdigest()
    
    sha256_path = tar_path + ".sha256"
    with open(sha256_path, "w", encoding="utf-8") as f:
        f.write(f"{checksum}  {tar_name}\n")
        
    return tar_path, sha256_path
