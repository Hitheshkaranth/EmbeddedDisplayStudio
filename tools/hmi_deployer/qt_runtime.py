"""
tools/hmi_deployer/qt_runtime.py
Layer: 3 (Host Deployer)
Purpose: assemble, on the Studio's own machine, the Qt runtimes a Qt bundle
         needs on a panel that has none (CONTRACT sections 4.1, 6).

WHY THIS EXISTS
---------------
Panels run the Qt-free GUI by default and have no internet and no package
feed. A bundle with runtime "python" and a manifest qt_binding of "pyside2" or
"pyside6" therefore has to arrive with its Qt runtime, and the only machine
that can fetch one is the host running the Studio -- usually Windows, often a
frozen build with no WSL, dpkg-deb or Docker behind it.

  pyside2  build_pyside2_runtime(): CPython 3.11 + a private Qt 5.15 +
           PySide2, as one tarball whose single top directory is python/.
           The panel extracts it and moves it to QT5_REMOTE_ROOT.
  pyside6  pyside6_wheels(): PySide6-Essentials + shiboken6 wheels for the
           panel's own /opt/hmi-python (CPython 3.12).
  app deps app_wheels(): the bundle's third-party packages as aarch64-usable
           wheels for `pip install --no-index --find-links` on the panel.

THE .deb PROBLEM
----------------
The PySide2 runtime is a port of deploy/provision_pyside2.sh, which unpacks
Debian bookworm .debs with dpkg-deb. Here a .deb is parsed as the ar archive it
is, and its data.tar is streamed member by member straight into the output
tarball under the name the bash script's copy step would have given it. Nothing
is extracted to the Windows filesystem: the .so -> .so.5 -> .so.5.15.8 symlink
chains would fail or silently turn into copies there, tripling the size and
breaking nothing visibly until the panel runs out of flash.

Inputs:  the network (deb.debian.org, github.com, PyPI via pip).
Outputs: files under runtime_cache_dir().
Stdlib only, and no Qt at import time: this also runs from worker threads and
from tests with no display.
"""

import bz2
import collections
import fnmatch
import gzip
import hashlib
import io
import json
import lzma
import os
import pathlib
import posixpath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# Recipe constants. Origin: deploy/provision_pyside2.sh -- keep the two in step.
# ---------------------------------------------------------------------------

# Debian suite the aarch64 PySide2 binaries come from: the last one carrying
# pyside2 against a glibc (2.36) older than the panel's (2.39). Trixie's are
# built against 2.41 and would not load.
SUITE = "bookworm"

# Debian mirror. Only the main component is used.
MIRROR = "https://deb.debian.org/debian"

# python-build-standalone release tag and the CPython it carries. 3.11 is the
# newest interpreter Debian's PySide2 (cp311 ABI) accepts.
PY_TAG = "20260814"
PY_VER = "3.11.16"

# The install_only tarball: its single top directory is python/, which is
# exactly the layout the output needs.
CPYTHON_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PY_TAG}/cpython-{PY_VER}%2B{PY_TAG}-aarch64-unknown-linux-gnu-install_only.tar.gz"
)

# Checksums published alongside the release; used to verify the tarball.
CPYTHON_SUMS_URL = (
    "https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{PY_TAG}/SHA256SUMS"
)

# Where the runtime lands on the panel. hmi-gui-launch hard-codes this path.
QT5_REMOTE_ROOT = "/opt/hmi-python-qt5"

# Root packages; their dependency closure is resolved from the suite index.
ROOT_PKGS = (
    "libshiboken2-py3-5.15",
    "libpyside2-py3-5.15",
    "python3-pyside2.qtcore",
    "python3-pyside2.qtgui",
    "python3-pyside2.qtwidgets",
    "python3-pyside2.qtnetwork",
    "python3-pyside2.qtsvg",
    "python3-pyside2.qtprintsupport",
    "python3-pyside2.qtxml",
    "qtwayland5",
)

# Pure-Python packages industrial PySide2 apps commonly import and no .deb
# provides in a usable form. Baked into the runtime's site-packages.
PIP_PKGS = ("pyserial", "prettytable", "networkscan")

# Provided by the panel, or deliberately omitted (the ~200 MB Mesa/LLVM stack:
# Qt Widgets renders raster, the glvnd stubs satisfy the link). Pruned from the
# closure along with their own dependencies.
SKIP_PKGS = (
    "libc6", "libgcc-s1", "libstdc++6", "libc-bin", "libcrypt1",
    "python3", "python3-minimal", "libpython3.11", "libpython3.11-minimal",
    "libpython3.11-stdlib", "dpkg", "install-info", "debconf", "sensible-utils", "ucf",
    "adduser", "passwd", "libudev1", "libsystemd0", "systemd", "udev",
    "libgl1-mesa-dri", "libglx-mesa0", "libegl-mesa0", "libllvm15", "libgbm1",
    "libdrm2", "libdrm-common", "libdrm-amdgpu1", "libdrm-nouveau2", "libdrm-radeon1",
    "libelf1", "libsensors5", "libsensors-config", "libz3-4", "libedit2",
)

# Virtual package name prefixes that carry no files.
VIRTUAL_PREFIXES = ("qtbase-abi-", "qtdeclarative-abi-", "qt5-", "fontconfig-config")

# Directories whose top-level *.so* are swept into python/qt5/lib, in the
# bash script's order: on a basename clash the later directory wins (cp -a
# over the earlier copy). bookworm is merged-/usr but packages still declare
# /lib paths, hence all four.
LIB_SWEEP_DIRS = (
    "usr/lib/aarch64-linux-gnu",
    "usr/lib",
    "lib/aarch64-linux-gnu",
    "lib",
)

# Source of the Qt plugin tree, copied whole to python/qt5/plugins.
PLUGIN_SRC = "usr/lib/aarch64-linux-gnu/qt5/plugins"

# Debian's Python package directory and the bindings taken from it.
DIST_PACKAGES = "usr/lib/python3/dist-packages"
BINDING_DIRS = ("PySide2", "shiboken2")

# Where things land inside the output tarball.
OUT_QT_LIB = "python/qt5/lib"
OUT_QT_PLUGINS = "python/qt5/plugins"
OUT_SITE = "python/lib/python3.11/site-packages"

# Bumped when the assembly itself changes, so a cached tarball built by an
# older Studio is rebuilt rather than trusted.
ASSEMBLY_REVISION = 1

# ---------------------------------------------------------------------------
# PySide6 / wheel constants
# ---------------------------------------------------------------------------

# Wheel platform tags pip may choose for the panel (aarch64, glibc 2.39).
# Newest first; pip accepts any of them, and older manylinux wheels run fine
# on a newer glibc.
PANEL_PLATFORMS = (
    "manylinux_2_39_aarch64",
    "manylinux_2_28_aarch64",
    "manylinux_2_17_aarch64",
    "manylinux2014_aarch64",
    "linux_aarch64",
)

# Interpreter of the panel's /opt/hmi-python, which hosts PySide6.
PANEL_PY6_VERSION = "3.12"

# Seconds a single network read may stall before a download is abandoned.
NET_TIMEOUT_S = 60

# Downloads larger than this (bytes) report ~10 % progress steps; smaller ones
# report only once, or 84 .debs would flood the Studio console.
PROGRESS_MIN_BYTES = 4 * 1024 * 1024

# Same flag as native_preview.PIP_FLAG. Duplicated only as a fallback for an
# environment without PySide6, where that module cannot be imported; a test
# pins the two together.
_PIP_FLAG_FALLBACK = "--pip-install"


# ---------------------------------------------------------------------------
# Paths and pip
# ---------------------------------------------------------------------------

def runtime_cache_dir() -> pathlib.Path:
    """Per-user cache for runtimes, .debs and wheels, created if missing.

    Kept outside the Studio install: a frozen build's own directory is
    read-only where it is usually installed, and these files are large and
    worth keeping across runs.

    Returns:
        %LOCALAPPDATA%/EmbeddedDisplayStudio/runtimes, else the same under
        XDG_DATA_HOME or ~/.local/share.
    Raises:
        OSError: the directory cannot be created.
    """
    base = (
        os.environ.get("LOCALAPPDATA")
        or os.environ.get("XDG_DATA_HOME")
        or os.path.expanduser("~/.local/share")
    )
    path = pathlib.Path(base) / "EmbeddedDisplayStudio" / "runtimes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pip_argv(args: list) -> list:
    """The command line that runs pip with `args` from this process.

    A frozen Studio has no `python -m pip`; it re-invokes its own executable
    with PIP_FLAG, which main.py dispatches to pip's main.

    Args:
        args: pip arguments, e.g. ["download", "--dest", d, "pyserial"].
    Returns:
        argv list suitable for subprocess.
    """
    if getattr(sys, "frozen", False):
        try:
            # Imported late: native_preview pulls in PySide6, and this module
            # must stay importable without Qt.
            from tools.hmi_deployer.native_preview import PIP_FLAG
        except ImportError:
            PIP_FLAG = _PIP_FLAG_FALLBACK
        return [sys.executable, PIP_FLAG, *args]
    return [sys.executable, "-m", "pip", *args]


def _run_pip(args: list, progress) -> tuple:
    """Run pip and capture its output.

    Args:
        args: pip arguments (see pip_argv).
        progress: callable(str) for the Studio console.
    Returns:
        (returncode, combined stdout+stderr text).
    Side effects:
        Spawns a process; blocks until it exits. Network I/O through pip.
    """
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    proc = subprocess.run(
        pip_argv(["--disable-pip-version-check", "--no-input", *args]),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        creationflags=flags,
    )
    return proc.returncode, proc.stdout or ""


def _tail(text: str, lines: int = 6) -> str:
    """Last few non-empty lines of `text`, for error messages."""
    kept = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])


# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------

def _download(url: str, dest: pathlib.Path, progress, label: str,
              sha256: str = "") -> pathlib.Path:
    """Fetch `url` to `dest` through a temp file, verifying `sha256` if given.

    Args:
        url: http(s) URL.
        dest: final path; written only once the download is complete and
            verified, so an interrupted run never leaves a truncated file
            that a later run would trust.
        progress: callable(str).
        label: short name used in progress lines.
        sha256: expected hex digest, or "" to skip verification.
    Returns:
        dest.
    Raises:
        urllib.error.URLError / OSError: network or disk failure.
        RuntimeError: checksum mismatch.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "EmbeddedDisplayStudio"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=NET_TIMEOUT_S) as resp, open(part, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done, next_step = 0, 10
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total >= PROGRESS_MIN_BYTES:
                    pct = done * 100 // total
                    if pct >= next_step:
                        progress(f"{label}: {pct}% of {total // (1024 * 1024)} MB")
                        next_step = (pct // 10 + 1) * 10
        if sha256 and digest.hexdigest() != sha256.lower():
            raise RuntimeError(f"{label}: checksum mismatch for {url}")
        os.replace(part, dest)
    finally:
        if part.exists():
            part.unlink()
    return dest


def _fetch_bytes(url: str) -> bytes:
    """Read a small URL fully into memory.

    Raises:
        urllib.error.URLError / OSError: network failure.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "EmbeddedDisplayStudio"})
    with urllib.request.urlopen(req, timeout=NET_TIMEOUT_S) as resp:
        return resp.read()


def _sha256_file(path: pathlib.Path) -> str:
    """Hex SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# ar / .deb parsing
# ---------------------------------------------------------------------------

AR_MAGIC = b"!<arch>\n"   # global header of every ar archive
AR_HEADER_LEN = 60        # bytes per member header


def parse_ar(data: bytes) -> list:
    """Split an ar archive into its members.

    Handles GNU names (trailing "/", the "//" long-name table, "/NNN"
    references), BSD "#1/<len>" names (name stored at the start of the data),
    skips the "/" and "/SYM64/" symbol tables, and the 2-byte alignment pad
    after an odd-length member.

    Args:
        data: the whole archive.
    Returns:
        list of (name, bytes) in archive order.
    Raises:
        ValueError: not an ar archive, or a header/size is malformed.
    """
    if not data.startswith(AR_MAGIC):
        raise ValueError("not an ar archive (bad magic)")
    pos, out, longnames = len(AR_MAGIC), [], b""
    while pos < len(data):
        if data[pos:pos + 1] == b"\n":   # stray pad some writers leave at EOF
            pos += 1
            continue
        header = data[pos:pos + AR_HEADER_LEN]
        if len(header) < AR_HEADER_LEN or header[58:60] != b"`\n":
            raise ValueError(f"malformed ar header at offset {pos}")
        raw_name = header[0:16].decode("ascii", "replace").rstrip(" ")
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError:
            raise ValueError(f"bad ar member size at offset {pos}") from None
        start = pos + AR_HEADER_LEN
        body = data[start:start + size]
        if len(body) != size:
            raise ValueError(f"truncated ar member {raw_name!r}")
        pos = start + size + (size & 1)
        if raw_name in ("/", "/SYM64/", "__.SYMDEF", "__.SYMDEF SORTED"):
            continue
        if raw_name == "//":
            longnames = body
            continue
        if raw_name.startswith("#1/"):
            nlen = int(raw_name[3:])
            name, body = body[:nlen].rstrip(b"\0").decode("utf-8", "replace"), body[nlen:]
        elif raw_name.startswith("/") and raw_name[1:].isdigit():
            off = int(raw_name[1:])
            end = longnames.find(b"\n", off)
            name = longnames[off:end if end >= 0 else None].decode("utf-8", "replace")
            name = name.rstrip("/")
        else:
            name = raw_name[:-1] if raw_name.endswith("/") else raw_name
        out.append((name, body))
    return out


def deb_data_tar(deb_bytes: bytes, label: str = "") -> tarfile.TarFile:
    """Open the data.tar of a .deb for reading.

    Args:
        deb_bytes: the whole .deb.
        label: package name for error messages.
    Returns:
        an open TarFile over an in-memory copy of data.tar.
    Raises:
        ValueError: no data.tar member.
        RuntimeError: data.tar.zst (the stdlib has no zstd decoder).
    """
    for name, body in parse_ar(deb_bytes):
        if not name.startswith("data.tar"):
            continue
        comp = name[len("data.tar"):]
        if comp == ".zst":
            raise RuntimeError(
                f"{label or 'package'}: data.tar.zst is not supported "
                "(no zstd in the Python standard library)"
            )
        mode = {"": "r:", ".gz": "r:gz", ".xz": "r:xz", ".bz2": "r:bz2"}.get(comp)
        if mode is None:
            raise RuntimeError(f"{label or 'package'}: unsupported {name}")
        return tarfile.open(fileobj=io.BytesIO(body), mode=mode)
    raise ValueError(f"{label or 'package'}: no data.tar member")


# ---------------------------------------------------------------------------
# Dependency closure (port of the bash script's embedded resolver)
# ---------------------------------------------------------------------------

def parse_packages_index(text: str) -> tuple:
    """Parse a Debian Packages index.

    Continuation lines are ignored, as in the original resolver: no field it
    reads spans lines.

    Args:
        text: the decompressed Packages file.
    Returns:
        (pkgs, provides): pkgs maps name -> field dict; provides maps a
        virtual name -> [providing package names] in index order.
    """
    pkgs, provides, cur = {}, collections.defaultdict(list), {}

    def flush():
        if cur.get("Package"):
            pkgs[cur["Package"]] = dict(cur)
            for p in re.split(r",\s*", cur.get("Provides", "")):
                if p.strip():
                    provides[p.split()[0]].append(cur["Package"])

    for line in text.splitlines():
        if not line:
            flush()
            cur = {}
        elif line[0] not in " \t" and ":" in line:
            k, _, v = line.partition(":")
            cur[k.strip()] = v.strip()
    flush()
    return pkgs, provides


def _dep_names(field: str) -> list:
    """First alternative of each Depends group, without version or :arch.

    "a (>= 1) | b, c:any" -> ["a", "c"]. Taking only the first alternative is
    what the original resolver does; the others are never needed here.
    """
    out = []
    for group in field.split(","):
        first = group.strip().split("|")[0].strip()
        if first:
            out.append(first.split()[0].split(":")[0])
    return out


def resolve_closure(pkgs: dict, provides: dict, roots, skip=SKIP_PKGS,
                    virtual=VIRTUAL_PREFIXES) -> list:
    """Breadth-first Depends closure of `roots`.

    Args:
        pkgs, provides: from parse_packages_index().
        roots: package names to start from.
        skip: names pruned together with their own dependencies.
        virtual: name prefixes of file-less virtual packages, also pruned.
    Returns:
        list of package field dicts in discovery order (each has "Filename").
    """
    skip = set(skip)
    virtual = tuple(virtual)
    seen, order = set(), []
    queue = collections.deque(roots)
    while queue:
        name = queue.popleft()
        if name in seen or name in skip or name.startswith(virtual):
            continue
        seen.add(name)
        p = pkgs.get(name)
        if p is None:
            if provides.get(name):
                queue.append(provides[name][0])
            continue
        order.append(p)
        queue.extend(_dep_names(p.get("Depends", "")))
    return order


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Archive member name without "./" or "/" prefix or trailing "/"."""
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/").rstrip("/")


def map_deb_member(name: str, isdir: bool) -> tuple:
    """Where the bash script's copy step would put a .deb member.

    Args:
        name: data.tar member name (any "./" prefix).
        isdir: the member is a directory.
    Returns:
        (output name, sweep group) or (None, 0) if the script would not copy
        it. The group orders basename clashes in python/qt5/lib: a later
        LIB_SWEEP_DIRS entry overwrote an earlier one there.
    """
    path = _norm(name)
    if not isdir:
        parent, base = posixpath.split(path)
        if parent in LIB_SWEEP_DIRS and fnmatch.fnmatchcase(base, "*.so*"):
            return f"{OUT_QT_LIB}/{base}", LIB_SWEEP_DIRS.index(parent) + 1
    if path.startswith(PLUGIN_SRC + "/"):
        return f"{OUT_QT_PLUGINS}/{path[len(PLUGIN_SRC) + 1:]}", 0
    for binding in BINDING_DIRS:
        src = f"{DIST_PACKAGES}/{binding}"
        if path == src or path.startswith(src + "/"):
            return f"{OUT_SITE}/{binding}{path[len(src):]}", 0
    return None, 0


class _Spool:
    """Output entries collected before the tarball is written.

    Holds TarInfo metadata in memory and regular-file bodies in numbered temp
    files (plain bytes are safe on any filesystem; only links are not, and
    those stay metadata). Last write of a name wins, subject to priority.
    """

    def __init__(self, tmpdir: pathlib.Path):
        """Args: tmpdir: scratch directory for file bodies (owned by caller)."""
        self.tmpdir = tmpdir
        self.entries = {}   # out name -> (priority tuple, TarInfo, body path|None)
        self._n = 0

    def put(self, info: tarfile.TarInfo, fileobj, priority: tuple) -> None:
        """Record an entry unless an existing one has higher priority.

        Args:
            info: metadata; info.name is the output name.
            fileobj: readable body for a regular file, else None.
            priority: comparable; the greater one wins a name clash, ties go
                to the later call.
        Side effects:
            Writes/removes body files in tmpdir.
        """
        old = self.entries.get(info.name)
        if old is not None and old[0] > priority:
            return
        body = None
        if info.isreg():
            self._n += 1
            body = self.tmpdir / f"{self._n}.bin"
            with open(body, "wb") as fh:
                shutil.copyfileobj(fileobj, fh, 1024 * 1024)
            info.size = body.stat().st_size
        if old is not None and old[2] is not None:
            old[2].unlink()
        self.entries[info.name] = (priority, info, body)


def _new_info(name: str, src: tarfile.TarInfo) -> tarfile.TarInfo:
    """A root-owned TarInfo named `name` carrying src's type, mode and mtime."""
    info = tarfile.TarInfo(name)
    info.type = src.type
    info.mode = src.mode
    info.mtime = src.mtime
    info.linkname = src.linkname
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    return info


def _spool_deb(spool: _Spool, deb_path, pkg_index: int, label: str) -> int:
    """Stream one .deb's relevant members into the spool.

    Hard links become regular files (their linkname is an archive path that
    the rename would break). Symlinks swept into qt5/lib that point elsewhere
    by path are rewritten to the bare basename: the sweep flattens the
    directories, so only a same-directory target stays meaningful.

    Args:
        spool: destination.
        deb_path: .deb file.
        pkg_index: position in the closure; later packages win a clash, as
            with successive dpkg-deb -x into one root.
        label: package name for errors.
    Returns:
        number of members taken.
    Raises:
        ValueError / RuntimeError: see deb_data_tar().
    """
    taken = 0
    with open(deb_path, "rb") as fh:
        data = fh.read()
    with deb_data_tar(data, label) as tf:
        for seq, m in enumerate(tf):
            if not (m.isreg() or m.islnk() or m.issym() or m.isdir()):
                continue
            out, group = map_deb_member(m.name, m.isdir())
            if out is None:
                continue
            info = _new_info(out, m)
            body = None
            if m.islnk():
                info.type = tarfile.REGTYPE
                info.linkname = ""
                body = tf.extractfile(m)
            elif m.isreg():
                body = tf.extractfile(m)
            elif m.issym() and group and "/" in m.linkname:
                info.linkname = posixpath.basename(m.linkname)
            spool.put(info, body, (group, pkg_index, seq))
            taken += 1
    return taken


def _wheel_dest(member: str, site: str) -> str:
    """Output name for a wheel member, or "" to drop it.

    purelib/platlib data go to site-packages, as pip would install them;
    scripts/headers/data from *.data are dropped (pip --target would scatter
    them outside site-packages, and nothing on the panel runs them).
    """
    first, _, rest = member.partition("/")
    if first.endswith(".data"):
        kind, _, rel = rest.partition("/")
        if kind in ("purelib", "platlib") and rel:
            return f"{site}/{rel}"
        return ""
    return f"{site}/{member}"


def assemble_runtime(cpython_tarball, debs, out_path, *, wheels=(), progress=print) -> dict:
    """Write the PySide2 runtime tarball from already-fetched inputs.

    The network-free half of build_pyside2_runtime(), so it can be fed local
    files. Output layout, as provision_pyside2.sh's build_payload leaves it:

      python/...                          the CPython install_only tree
      python/qt5/lib/*.so*                top-level libs of LIB_SWEEP_DIRS
      python/qt5/plugins/...              PLUGIN_SRC
      python/lib/python3.11/site-packages/{PySide2,shiboken2,<wheels>}

    Args:
        cpython_tarball: python-build-standalone install_only .tar.gz.
        debs: .deb paths in closure order.
        out_path: .tar.gz to write (the caller makes it atomic).
        wheels: pure-Python wheels to install into site-packages.
        progress: callable(str).
    Returns:
        {"members": n, "libs": n, "plugin_files": n, "symlinks": n,
         "dangling": [names]} describing the output.
    Raises:
        ValueError / RuntimeError: a malformed or unsupported .deb.
        OSError: disk failure.
    """
    with tempfile.TemporaryDirectory(prefix="qt5rt-") as tmp:
        spool = _Spool(pathlib.Path(tmp))
        for d in ("python/qt5", OUT_QT_LIB, OUT_QT_PLUGINS):
            info = tarfile.TarInfo(d)
            info.type, info.mode = tarfile.DIRTYPE, 0o755
            spool.put(info, None, (-1,))
        debs = list(debs)
        for i, deb in enumerate(debs):
            _spool_deb(spool, deb, i, pathlib.Path(deb).name)
        for j, whl in enumerate(wheels):
            with zipfile.ZipFile(whl) as zf:
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    dest = _wheel_dest(zi.filename, OUT_SITE)
                    if not dest:
                        continue
                    info = tarfile.TarInfo(dest)
                    perm = (zi.external_attr >> 16) & 0o777
                    info.mode = perm or 0o644
                    info.uname = info.gname = "root"
                    with zf.open(zi) as body:
                        spool.put(info, body, (0, len(debs) + j, 0))

        entries = spool.entries
        stats = {"members": 0, "libs": 0, "plugin_files": 0, "symlinks": 0, "dangling": []}
        lib_names = {n.rsplit("/", 1)[1] for n in entries if n.startswith(OUT_QT_LIB + "/")}
        for name, (_, info, _) in entries.items():
            if name.startswith(OUT_QT_LIB + "/"):
                stats["libs"] += 1
                if info.issym() and info.linkname not in lib_names:
                    stats["dangling"].append(name)
            elif name.startswith(OUT_QT_PLUGINS + "/") and not info.isdir():
                stats["plugin_files"] += 1
        progress(f"PySide2 runtime: {stats['libs']} libraries, "
                 f"{stats['plugin_files']} plugin files")

        progress("PySide2 runtime: packing")
        written = set()
        with tarfile.open(out_path, "w:gz", compresslevel=6) as out, \
                tarfile.open(cpython_tarball, "r:gz") as cp:
            for m in cp:
                name = _norm(m.name)
                if not name.startswith("python") or name in written:
                    continue
                # A spooled entry replaces a CPython file of the same name
                # (last wins); directories keep CPython's entry.
                if name in entries and not (m.isdir() and entries[name][1].isdir()):
                    continue
                m.name = name
                if m.isreg():
                    with cp.extractfile(m) as body:
                        out.addfile(m, body)
                else:
                    out.addfile(m)
                written.add(name)
                stats["symlinks"] += m.issym()
            for name in sorted(entries):
                if name in written:
                    continue
                _, info, body = entries[name]
                if body is not None:
                    with open(body, "rb") as fh:
                        out.addfile(info, fh)
                else:
                    out.addfile(info)
                written.add(name)
                stats["symlinks"] += info.issym()
        stats["members"] = len(written)
    return stats


# ---------------------------------------------------------------------------
# PySide2 runtime
# ---------------------------------------------------------------------------

def _recipe_hash() -> str:
    """Short digest of everything that decides the runtime's contents."""
    recipe = [SUITE, MIRROR, PY_TAG, PY_VER, ROOT_PKGS, SKIP_PKGS, PIP_PKGS,
              VIRTUAL_PREFIXES, ASSEMBLY_REVISION]
    return hashlib.sha256(json.dumps(recipe).encode()).hexdigest()[:10]


def pyside2_runtime_name() -> str:
    """File name of the cached PySide2 runtime tarball for this recipe."""
    return f"hmi-python-qt5-{PY_VER}-{_recipe_hash()}.tar.gz"


def _cpython_sha256(progress) -> str:
    """Published SHA-256 of the CPython tarball, or "" if unavailable.

    Best effort: the release's SHA256SUMS is not guaranteed to exist for
    every tag, and a missing sum must not block a build.
    """
    fname = CPYTHON_URL.rsplit("/", 1)[1].replace("%2B", "+")
    try:
        sums = _fetch_bytes(CPYTHON_SUMS_URL).decode("utf-8", "replace")
    except OSError:
        progress("CPython: no published checksum, not verified")
        return ""
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == fname:
            return parts[0]
    return ""


def build_pyside2_runtime(progress=print, *, cache=None, force=False) -> pathlib.Path:
    """The PySide2/Qt5 runtime tarball for QT5_REMOTE_ROOT, built if needed.

    Port of deploy/provision_pyside2.sh build_payload, runnable on Windows.
    Downloads are cached (and checksummed) under <cache>/downloads, so a
    rebuild re-fetches only the package index.

    Args:
        progress: callable(str) for the Studio console.
        cache: cache root; default runtime_cache_dir().
        force: rebuild even if the tarball exists.
    Returns:
        path of the tarball; its single top directory is python/. On the
        panel: extract to /tmp, then mv /tmp/python QT5_REMOTE_ROOT.
    Raises:
        urllib.error.URLError / OSError: network or disk failure.
        RuntimeError: a checksum mismatch, a missing package, an
            unsupported .deb, or pip failing to fetch PIP_PKGS.
    Side effects:
        Network I/O; writes ~100+ MB under the cache; blocks for minutes.
    """
    cache = pathlib.Path(cache) if cache else runtime_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / pyside2_runtime_name()
    if out.exists() and not force:
        progress(f"PySide2 runtime: cached {out.name}")
        return out
    dl = cache / "downloads"

    cpy = dl / CPYTHON_URL.rsplit("/", 1)[1].replace("%2B", "+")
    if not cpy.exists():
        progress(f"PySide2 runtime: fetching CPython {PY_VER} (aarch64)")
        _download(CPYTHON_URL, cpy, progress, "CPython", _cpython_sha256(progress))

    progress(f"PySide2 runtime: fetching {SUITE}/arm64 package index")
    index = gzip.decompress(
        _fetch_bytes(f"{MIRROR}/dists/{SUITE}/main/binary-arm64/Packages.gz")
    ).decode("utf-8", "replace")
    pkgs, provides = parse_packages_index(index)
    closure = resolve_closure(pkgs, provides, ROOT_PKGS)
    progress(f"PySide2 runtime: resolving {len(closure)} packages")

    debs = []
    for i, p in enumerate(closure, 1):
        fn = p["Filename"]
        dest = dl / "debs" / posixpath.basename(fn)
        want = p.get("SHA256", "")
        if dest.exists() and (not want or _sha256_file(dest) == want):
            debs.append(dest)
            continue
        progress(f"downloading {i}/{len(closure)} {p['Package']}")
        _download(f"{MIRROR}/{fn}", dest, progress, p["Package"], want)
        debs.append(dest)

    progress(f"PySide2 runtime: pure-Python packages {', '.join(PIP_PKGS)}")
    wheel_dir = app_wheels(list(PIP_PKGS), "3.11", progress, cache=cache)
    wheels = sorted(wheel_dir.glob("*.whl"))

    fd, tmp_name = tempfile.mkstemp(prefix=out.name + ".", suffix=".part", dir=cache)
    os.close(fd)
    try:
        stats = assemble_runtime(cpy, debs, tmp_name, wheels=wheels, progress=progress)
        if stats["dangling"]:
            progress(f"PySide2 runtime: {len(stats['dangling'])} dangling lib symlinks")
        os.replace(tmp_name, out)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    progress(f"PySide2 runtime: {out.name} ({out.stat().st_size // (1024 * 1024)} MB)")
    return out


# ---------------------------------------------------------------------------
# Wheels
# ---------------------------------------------------------------------------

def _platform_args(python_version: str) -> list:
    """pip flags selecting binary wheels for the panel's interpreter."""
    args = ["--only-binary=:all:"]
    for plat in PANEL_PLATFORMS:
        args += ["--platform", plat]
    return args + ["--python-version", python_version, "--implementation", "cp"]


def pyside6_wheels(progress=print, *, version="6.11.2", cache=None) -> pathlib.Path:
    """PySide6-Essentials and shiboken6 wheels for the panel's /opt/hmi-python.

    Args:
        progress: callable(str).
        version: PySide6 release; shiboken6 follows it as a pinned dependency.
        cache: cache root; default runtime_cache_dir().
    Returns:
        directory holding both wheels (cached per version).
    Raises:
        RuntimeError: pip failed, or did not produce both wheels.
    Side effects:
        Network I/O through pip; ~60 MB on first call.
    """
    cache = pathlib.Path(cache) if cache else runtime_cache_dir()
    dest = cache / "pyside6" / version

    def complete() -> bool:
        # PyPI serves "pyside6_essentials-..."; compare case-blind so the
        # check does not depend on the host filesystem's case rules.
        names = [p.name.lower() for p in dest.glob("*.whl")] if dest.is_dir() else []
        return all(any(n.startswith(f"{dist}-{version}-") for n in names)
                   for dist in ("pyside6_essentials", "shiboken6"))

    if complete():
        progress(f"PySide6 {version}: cached wheels")
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    progress(f"PySide6 {version}: downloading aarch64 wheels")
    rc, text = _run_pip(["download", *_platform_args(PANEL_PY6_VERSION),
                         "--dest", str(dest), f"PySide6-Essentials=={version}"], progress)
    if rc != 0 or not complete():
        raise RuntimeError(f"PySide6 {version}: wheel download failed\n{_tail(text)}")
    return dest


# Target environment for evaluating Requires-Dist markers: the panel.
def _marker_env(python_version: str) -> dict:
    """PEP 508 marker variables for the panel running `python_version`."""
    return {
        "python_version": python_version,
        "python_full_version": python_version + ".0",
        "sys_platform": "linux",
        "platform_system": "Linux",
        "platform_machine": "aarch64",
        "os_name": "posix",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "extra": "",
    }


_MARKER_TOKEN = re.compile(
    r"\s*(?:(\()|(\))|(and|or)\b|(not\s+in\b|in\b|===|==|!=|<=|>=|~=|<|>)|"
    r"'([^']*)'|\"([^\"]*)\"|([A-Za-z_.]+))"
)


def _version_key(v: str):
    """Numeric tuple for simple version strings, else the string itself."""
    parts = v.split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else v


def _compare(left: str, op: str, right: str) -> bool:
    """One PEP 508 comparison, numerically when both sides are versions."""
    if op in ("in", "not in"):
        return (left in right) == (op == "in")
    a, b = _version_key(left), _version_key(right)
    if type(a) is not type(b):
        a, b = left, right
    if isinstance(a, tuple):
        n = max(len(a), len(b))
        a, b = a + (0,) * (n - len(a)), b + (0,) * (n - len(b))
    if op == "~=":
        return a >= b
    return {"==": a == b, "===": left == right, "!=": a != b, "<": a < b,
            "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def marker_matches(marker: str, env: dict) -> bool:
    """Evaluate a PEP 508 environment marker against `env`.

    Covers what Requires-Dist uses in practice (comparisons, and/or,
    parentheses). Anything it cannot parse counts as a match: fetching an
    unneeded wheel is harmless, missing a needed one is not.
    """
    tokens, pos = [], 0
    while pos < len(marker):
        m = _MARKER_TOKEN.match(marker, pos)
        if not m or m.end() == pos:
            if marker[pos:].strip():
                return True
            break
        pos = m.end()
        if m.group(1) or m.group(2) or m.group(3):
            tokens.append(("p", m.group(1) or m.group(2) or m.group(3)))
        elif m.group(4):
            tokens.append(("op", re.sub(r"\s+", " ", m.group(4))))
        elif m.group(5) is not None or m.group(6) is not None:
            tokens.append(("s", m.group(5) if m.group(5) is not None else m.group(6)))
        else:
            tokens.append(("v", m.group(7)))

    def value(tok):
        return tok[1] if tok[0] == "s" else env.get(tok[1], tok[1])

    def expr(i):
        v, i = term(i)
        while i < len(tokens) and tokens[i] == ("p", "or"):
            r, i = term(i + 1)
            v = v or r
        return v, i

    def term(i):
        v, i = atom(i)
        while i < len(tokens) and tokens[i] == ("p", "and"):
            r, i = atom(i + 1)
            v = v and r
        return v, i

    def atom(i):
        if tokens[i] == ("p", "("):
            v, i = expr(i + 1)
            return v, i + 1
        left, op, right = tokens[i], tokens[i + 1], tokens[i + 2]
        return _compare(value(left), op[1], value(right)), i + 3

    try:
        return bool(expr(0)[0])
    except (IndexError, KeyError, TypeError):
        return True


def wheel_requirements(wheel: pathlib.Path, python_version: str) -> list:
    """Requirement strings (markers stripped) a wheel needs on the panel.

    Args:
        wheel: .whl file.
        python_version: panel interpreter, for markers.
    Returns:
        e.g. ["wcwidth", "requests>=2"]; extras-only requirements excluded.
    """
    env = _marker_env(python_version)
    with zipfile.ZipFile(wheel) as zf:
        meta = next((n for n in zf.namelist()
                     if n.count("/") == 1 and n.endswith(".dist-info/METADATA")), None)
        if meta is None:
            return []
        text = zf.read(meta).decode("utf-8", "replace")
    reqs = []
    for line in text.split("\n\n", 1)[0].splitlines():
        if not line.startswith("Requires-Dist:"):
            continue
        req, _, marker = line[len("Requires-Dist:"):].partition(";")
        if marker.strip() and ("extra" in marker or not marker_matches(marker, env)):
            continue
        reqs.append(req.strip().replace(" ", ""))
    return reqs


def is_portable_wheel(filename: str) -> bool:
    """True for a pure-Python py3 wheel usable on any platform."""
    stem = filename[:-4] if filename.endswith(".whl") else filename
    parts = stem.split("-")
    if len(parts) < 5:
        return False
    py, abi, plat = parts[-3:]
    return (abi == "none" and plat == "any"
            and any(t == "py3" or t.startswith("py3") for t in py.split(".")))


def _canon(name: str) -> str:
    """PEP 503 normalised project name of a requirement string."""
    base = re.split(r"[\s<>=!~;\[(@]", name.strip(), 1)[0]
    return re.sub(r"[-_.]+", "-", base).lower()


def app_wheels(distributions: list, python_version: str, progress=print, *,
               cache=None) -> pathlib.Path:
    """Wheels for an app's third-party packages, for an offline panel install.

    Per distribution: pip download of aarch64/pure wheels with dependencies;
    if that fails (sdist-only projects such as networkscan), build it locally
    with `pip wheel --no-deps` and keep the result only if it is pure Python
    (a platform wheel built here would be for Windows), then resolve its
    dependencies the same way.

    Args:
        distributions: requirement strings, e.g. ["pyserial", "networkscan"].
        python_version: panel interpreter, "3.11" (Qt5 runtime) or "3.12".
        progress: callable(str).
        cache: cache root; default runtime_cache_dir().
    Returns:
        a directory emptied and refilled on each call, keyed by the sorted
        names and python_version, for `pip install --no-index --find-links`.
    Raises:
        RuntimeError: naming every distribution that could not be obtained.
    Side effects:
        Network I/O and local builds through pip.
    """
    cache = pathlib.Path(cache) if cache else runtime_cache_dir()
    key = hashlib.sha256(
        json.dumps([sorted(distributions), python_version]).encode()
    ).hexdigest()[:10]
    dest = cache / "app-wheels" / f"py{python_version}-{key}"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    seen, failed = set(), []
    queue = collections.deque(distributions)
    while queue:
        req = queue.popleft()
        canon = _canon(req)
        if not canon or canon in seen:
            continue
        seen.add(canon)
        progress(f"wheels: {req}")
        rc, text = _run_pip(["download", *_platform_args(python_version),
                             "--dest", str(dest), req], progress)
        if rc == 0:
            continue
        # A packaged Studio takes published wheels only. Building from source
        # starts sys.executable several times over, and in a onefile build
        # each start unpacks the whole ~200 MB bundle again, which runs for
        # many minutes and reads as a hang.
        frozen = getattr(sys, "frozen", False)
        with tempfile.TemporaryDirectory(prefix="wheel-", dir=cache) as tmp:
            rc, text = _run_pip(
                ["wheel", "--no-deps", *(["--only-binary=:all:"] if frozen else []),
                 "-w", tmp, req],
                progress,
            )
            built = sorted(pathlib.Path(tmp).glob("*.whl"))
            if rc != 0 or not built:
                if frozen:
                    progress(f"wheels: {req} is published only as source code, which the "
                             "packaged Studio does not build; run the Studio from a "
                             "checkout (python main.py) to deploy it")
                failed.append(req)
                continue
            bad = [w.name for w in built if not is_portable_wheel(w.name)]
            if bad:
                progress(f"wheels: {req} builds a platform wheel ({bad[0]}), not usable")
                failed.append(req)
                continue
            for w in built:
                target = dest / w.name
                shutil.move(str(w), str(target))
                queue.extend(wheel_requirements(target, python_version))
    if failed:
        raise RuntimeError("could not obtain wheels for: " + ", ".join(failed))
    return dest
