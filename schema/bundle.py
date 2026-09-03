#!/usr/bin/env python3
"""
schema/bundle.py -- the single implementation of the bundle packing rules
=========================================================================

Layer: shared (host tooling; imported by the desktop tool, run as a script by
the host CLI)

What goes into a bundle, and what is silently left out, is now defined once.

WHY THIS FILE EXISTS
--------------------
DEFAULT_EXCLUDES and .hmiignore support existed only in the desktop tool, while
the README described both as platform behaviour. deploy_to_hmi.sh packaged the
directory as it found it, so the documented "build outputs, caches and VCS
metadata are left out of the bundle automatically" was false for the CLI: it
shipped .git/, build/ and __pycache__/ over a field link and into panel flash.

Both tools now produce byte-identical tarballs from the same directory, which
also means the SHA-256 the installer verifies does not depend on which tool
built the bundle.

Inputs:  a validated bundle directory.
Outputs: a deterministic .tar.gz plus its .sha256 sidecar.
"""

import datetime
import hashlib
import json
import os
import sys
import tarfile
from typing import Any, Dict, List, Tuple

# Hard ceiling on what may be sent, matching MAX_BUNDLE_SIZE in
# target/bin/hmi-install. Checking it here as well means an oversized bundle is
# refused in a second on the laptop, naming the files responsible, instead of
# after a long upload the target then rejects.
MAX_BUNDLE_BYTES = 524288000  # 500 MB


class BundleTooLargeError(Exception):
    """Raised when a bundle exceeds what the target will accept."""


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

# CONTRACT section 4 validation lives in schema/manifest.py, which the host
# CLI and the target installer also call. Re-exported here so existing callers
# (and tests) keep importing deployer.validate_bundle, while there is only one
# implementation to keep correct.
#
# Three copies of these rules had drifted apart in both directions: this tool
# required 'qt', 'screen' and 'tags_required' that the other two ignored -- so
# the manifest in the README was rejected here -- while never checking
# 'version', which both of the others required.
#
# DEFAULT_EXCLUDES, HMIIGNORE and the two functions that read them come back
# the same way. They belong to packing, but the validator needs them to answer
# "would this bundle ship a Qt binding?", and it is the file that reaches the
# panel on its own -- so it holds them and this module borrows them, rather
# than the other way round, which no installer's sys.path could resolve.
from schema.manifest import (  # noqa: E402  (import placed with its explanation)
    DEFAULT_EXCLUDES,
    HMIIGNORE,
    _excluded,
    detect_qt_binding,
    load_excludes,
    screen_of,
    validate_bundle,
)


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


def main(argv=None):
    """Command-line entry point used by deploy_to_hmi.sh.

    Usage:
        python3 bundle.py plan <bundle_dir>
            Print one archive-relative path per line, then a final line
            "TOTAL <bytes>". Shows exactly what would be shipped.

        python3 bundle.py pack <bundle_dir> <output_dir>
            Build the tarball and its sidecar. Prints the tarball path.

    Returns:
        0 on success, 1 on a bundle error (message on stderr), 2 on misuse.
    """
    usage = "usage: bundle.py {plan|pack} <bundle_dir> [output_dir]"
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(usage, file=sys.stderr)
        return 2

    command = argv[0]
    try:
        if command == "plan" and len(argv) == 2:
            entries, total = plan_bundle(argv[1])
            for _full, arcname in entries:
                print(arcname)
            print("TOTAL %d" % total)
            return 0
        if command == "pack" and len(argv) == 3:
            tar_path, _sha_path = package_bundle(argv[1], argv[2])
            print(tar_path)
            return 0
    except BundleTooLargeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print("bundle error: %s" % exc, file=sys.stderr)
        return 1

    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
