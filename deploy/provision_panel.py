#!/usr/bin/env python3
"""
deploy/provision_panel.py
Layer: 3 (Host Deployer)
Purpose: Install the EmbeddedDisplay Studio platform onto a running panel over SSH,
without rebuilding or reflashing an image.

The platform is Qt-free: the GUI is native/hmi-ui (C + LVGL, drawing to
DRM/KMS with no compositor), the daemon is Python. A panel provisioned by an
earlier version for the Qt loader is converted: hmi-ui.service takes the
display and install.sh removes the loader, its private Qt6 runtime and the
Weston configuration (--keep-qt leaves them on disk, disabled).

The bitbake layer in yocto/meta-hmi is how this reaches a production image.
This script is for the other case: a board that is already on a bench or in the
field, where "rebuild the image" is not a reasonable prerequisite for trying a
deployment. It installs the same files to the same paths (CONTRACT section 3).

    python deploy/provision_panel.py --host 192.168.1.50 --key ~/.ssh/id_ed25519

It runs read-only checks first and prints what it found, so a board that cannot
host this platform is identified before anything is written to it.

Uses the ssh/scp binaries rather than a Python SSH library, for the same reason
tools/hmi_deployer does: they are present on Windows, macOS and Linux, and they
honour the user's existing keys, agent and config.
"""
from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tarfile
import tempfile
from typing import List, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Where the payload is staged on the target before install.sh runs.
REMOTE_STAGE = "/tmp/hmi_provision"

# The panel GUI binary, as native/hmi-ui/arm64/build.sh leaves it.
HMI_UI_BINARY = "native/hmi-ui/out/aarch64/hmi-ui"

# Text extensions that must reach the target with LF endings. The repository is
# normalised to LF by .gitattributes, but a checkout on a machine with a
# different git configuration can still produce CRLF, and a CRLF shebang fails
# with the famously unhelpful "bad interpreter: /bin/sh^M".
TEXT_SUFFIXES = (
    ".sh", ".py", ".qml", ".json", ".conf", ".service", ".qmldir", ".md", "",
)

# The payload: (source path relative to the repo, destination relative to /).
# Destinations are CONTRACT section 3 verbatim; install.sh applies the modes.
FILE_PAYLOAD: List[Tuple[str, str]] = [
    ("target/bin/hmi-install",              "usr/bin/hmi-install"),
    ("target/bin/hmi-hwd-launch",           "usr/bin/hmi-hwd-launch"),
    # The panel GUI: native/hmi-ui built for aarch64 (native/hmi-ui/arm64/
    # build.sh). C + LVGL on DRM/KMS; no Qt, no compositor.
    (HMI_UI_BINARY,                         "usr/lib/hmi/ui/hmi-ui"),
    ("daemon/hmi_hwd.py",                   "usr/lib/hmi/hmi_hwd.py"),
    # The Modbus TCP client the daemon imports as a sibling module; the
    # launcher runs hmi_hwd.py as a script, so its own directory is on
    # sys.path and `import modbus` resolves here.
    ("daemon/modbus.py",                    "usr/lib/hmi/modbus.py"),
    # The single implementation of CONTRACT section 4; hmi-install calls it
    # from here rather than carrying its own copy of the manifest rules.
    ("schema/manifest.py",                  "usr/lib/hmi/manifest.py"),
    ("daemon/hwd.json",                     "etc/hmi/hwd.json"),
    ("target/etc/default/hmi-ui",           "etc/default/hmi-ui"),
    ("target/systemd/hmi-ui.service",       "etc/systemd/system/hmi-ui.service"),
    ("target/systemd/hmi-hwd.service",      "etc/systemd/system/hmi-hwd.service"),
    ("target/tmpfiles/hmi.conf",            "usr/lib/tmpfiles.d/hmi.conf"),
]

# Payload sources that are binaries: never line-ending normalised.
BINARY_SOURCES = {HMI_UI_BINARY}

# The daemon's optional packages, installed into a freshly shipped
# /opt/hmi-python from aarch64 wheels beside the tarball (see --python).
PYTHON_WHEELS = ("gpiod", "pyserial")

# Whole directories. The kit is what hmi-ui reads at runtime: the Inter fonts
# and the rasterised Tabler icons (schema/gen_icons.py). The QML components
# beside them in the repo are the Studio's preview/spec and do not travel.
TREE_PAYLOAD: List[Tuple[str, str]] = [
    ("ui/qml/Shadcn/fonts", "usr/lib/hmi/kit/fonts"),
    ("ui/qml/Shadcn/icons", "usr/lib/hmi/kit/icons"),
]

# Skipped when packing the trees above.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".sha")

# One command, so a single round trip answers every question that decides
# whether this board can host the platform.
PREFLIGHT = r"""
echo "uname: $(uname -srm)"
echo "os: $( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || echo unknown)"
echo "python3: $(command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' || echo MISSING)"
echo "python3_stdlib: $(python3 -c 'import json, socket, hashlib, ctypes, asyncio' >/dev/null 2>&1 && echo full || echo partial)"
echo "hmi_python: $(test -x /opt/hmi-python/bin/python3 && /opt/hmi-python/bin/python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' 2>/dev/null || echo absent)"
echo "systemctl: $(command -v systemctl >/dev/null 2>&1 && echo present || echo MISSING)"
echo "systemd_running: $(systemctl is-system-running 2>/dev/null || echo no)"
echo "drm_cards: $(ls /dev/dri/card* 2>/dev/null | tr '\n' ' ')"
echo "libdrm: $(ls /usr/lib/libdrm.so.2 /usr/lib/*/libdrm.so.2 /lib/*/libdrm.so.2 2>/dev/null | head -1)"
echo "weston_unit: $(systemctl list-unit-files 2>/dev/null | grep -c '^weston.service' || echo 0)"
echo "qt_loader: $( (test -e /usr/lib/hmi/gui/main.py || test -e /usr/lib/hmi/qt6 || test -e /etc/systemd/system/hmi-gui.service) && echo present || echo absent)"
echo "flock: $(command -v flock >/dev/null 2>&1 && echo present || echo MISSING)"
echo "tar: $(command -v tar >/dev/null 2>&1 && echo present || echo MISSING)"
echo "sha256sum: $(command -v sha256sum >/dev/null 2>&1 && echo present || echo MISSING)"
echo "docker: $(command -v docker >/dev/null 2>&1 || test -x /usr/local/bin/docker && echo present || echo absent)"
echo "existing_hmi_install: $(test -x /usr/bin/hmi-install && echo present || echo absent)"
echo "rootfs_rw: $(touch /.hmi_write_test 2>/dev/null && rm -f /.hmi_write_test && echo yes || echo no)"
echo "free_root: $(df -Pk / | awk 'NR==2 {print int($4/1024)}') MB"
"""


def ssh_base(host: str, user: str, port: int, key: Optional[str]) -> List[str]:
    """Builds the common ssh argument prefix."""
    args = ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    if port != 22:
        args += ["-p", str(port)]
    if key:
        args += ["-i", key]
    args.append(f"{user}@{host}")
    return args


def scp_cmd(host: str, user: str, port: int, key: Optional[str],
            src: str, dest: str) -> List[str]:
    """Builds an scp command for a single local file."""
    args = ["scp", "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes"]
    if port != 22:
        args += ["-P", str(port)]
    if key:
        args += ["-i", key]
    args += [src, f"{user}@{host}:{dest}"]
    return args


def run(cmd: List[str], echo: bool = True) -> Tuple[int, str]:
    """
    Runs a command, streaming its output.

    Args:
        cmd: argv list.
        echo: print each line as it arrives.

    Returns:
        (exit_code, combined_output)
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        lines.append(line)
        if echo:
            print(f"  {line}", flush=True)
    proc.wait()
    return proc.returncode, "\n".join(lines)


def _normalised(path: str) -> bytes:
    """
    Reads a payload file, converting CRLF to LF for text.

    Args:
        path: absolute source path.

    Returns:
        The bytes to place in the archive.
    """
    with open(path, "rb") as f:
        data = f.read()
    rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
    if rel not in BINARY_SOURCES and os.path.splitext(path)[1].lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return data


def _add(tar: tarfile.TarFile, data: bytes, arcname: str, mode: int = 0o644) -> None:
    """Adds in-memory bytes to the archive under arcname."""
    info = tarfile.TarInfo(arcname)
    info.size = len(data)
    info.mode = mode
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    tar.addfile(info, io.BytesIO(data))


def build_payload(out_path: str, python_tarball: Optional[str] = None,
                  wheel_dir: Optional[str] = None) -> int:
    """
    Packs everything the target needs into one tarball.

    Args:
        out_path: where to write the .tar.gz.
        python_tarball: a python-build-standalone aarch64 install_only .tar.gz
            to ship as /opt/hmi-python (files/opt/hmi-python.tar.gz), or None.
        wheel_dir: a directory of aarch64 wheels for PYTHON_WHEELS, shipped
            beside it (files/opt/hmi-python-wheels/), or None.

    Returns:
        The number of files packed.

    A single archive rather than a series of scp calls: it is one round trip,
    it cannot be left half-transferred, and the modes are applied on the target
    by install.sh rather than inherited from whatever filesystem the host uses
    (Windows has no executable bit to preserve).
    """
    count = 0
    with tarfile.open(out_path, "w:gz") as tar:
        _add(tar, _normalised(os.path.join(REPO_ROOT, "deploy", "provision_remote.sh")),
             "install.sh", mode=0o755)
        count += 1

        for src_rel, dest_rel in FILE_PAYLOAD:
            src = os.path.join(REPO_ROOT, src_rel)
            if not os.path.isfile(src):
                hint = ""
                if src_rel == HMI_UI_BINARY:
                    hint = " (build it: bash native/hmi-ui/arm64/build.sh, from WSL)"
                raise FileNotFoundError(f"payload source missing: {src_rel}{hint}")
            _add(tar, _normalised(src), f"files/{dest_rel}")
            count += 1

        if python_tarball:
            with open(python_tarball, "rb") as f:
                _add(tar, f.read(), "files/opt/hmi-python.tar.gz")
            count += 1
            if wheel_dir:
                for name in sorted(os.listdir(wheel_dir)):
                    if name.endswith(".whl"):
                        with open(os.path.join(wheel_dir, name), "rb") as f:
                            _add(tar, f.read(), f"files/opt/hmi-python-wheels/{name}")
                        count += 1

        for src_rel, dest_rel in TREE_PAYLOAD:
            src_root = os.path.join(REPO_ROOT, src_rel)
            if not os.path.isdir(src_root):
                raise FileNotFoundError(f"payload source missing: {src_rel}")
            for dirpath, dirnames, filenames in os.walk(src_root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
                for name in sorted(filenames):
                    if name.endswith(SKIP_SUFFIXES):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, src_root).replace(os.sep, "/")
                    _add(tar, _normalised(full), f"files/{dest_rel}/{rel}")
                    count += 1
    return count


def parse_preflight(output: str) -> dict:
    """Turns the preflight output into a dict of key -> value."""
    found = {}
    for line in output.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            found[key.strip()] = value.strip()
    return found


def fetch_wheels(out_dir: str) -> Optional[str]:
    """
    Downloads aarch64 wheels of the daemon's optional packages with pip.

    Args:
        out_dir: where to put them.

    Returns:
        out_dir when at least one wheel was fetched, else None (the daemon
        runs without GPIO/UART support until they are installed by hand).
    """
    os.makedirs(out_dir, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "download", "-q", "--dest", out_dir,
           "--platform", "manylinux_2_28_aarch64", "--platform", "manylinux2014_aarch64",
           "--only-binary=:all:", "--python-version", "3.12", "--implementation", "cp",
           *PYTHON_WHEELS]
    code, _ = run(cmd, echo=False)
    wheels = [n for n in os.listdir(out_dir) if n.endswith(".whl")]
    if code != 0 or not wheels:
        print("  WARNING: could not download the daemon's gpiod/pyserial wheels; "
              "GPIO and UART stay disabled until they are installed into /opt/hmi-python.")
        return None
    print(f"  wheels for /opt/hmi-python: {', '.join(sorted(wheels))}")
    return out_dir


def report_preflight(facts: dict, python_tarball: Optional[str] = None) -> List[str]:
    """
    Prints the survey and returns the list of blocking problems.

    Args:
        facts: parsed preflight output.
        python_tarball: --python, when given (it lifts the interpreter blocker).

    Returns:
        Human-readable blockers; empty means the board can host the platform.
    """
    print("\n  Board survey")
    print("  " + "-" * 58)
    for key in ("uname", "os", "python3", "python3_stdlib", "hmi_python", "systemctl", "systemd_running",
                "drm_cards", "libdrm", "weston_unit", "qt_loader", "flock", "tar",
                "sha256sum", "docker", "existing_hmi_install", "rootfs_rw", "free_root"):
        if key in facts:
            print(f"  {key:22} {facts[key]}")
    print("  " + "-" * 58)

    blockers = []
    if facts.get("python3", "MISSING") == "MISSING" and facts.get("hmi_python", "absent") == "absent":
        blockers.append(
            "python3 is not installed. hmi-install uses it for the atomic symlink "
            "swap and manifest validation, and the hardware daemon is written in it."
        )
    if (facts.get("python3_stdlib") != "full" and facts.get("hmi_python", "absent") == "absent"
            and not python_tarball):
        blockers.append(
            "The image's python3 lacks the standard library (json, socket, hashlib, "
            "ctypes...) and there is no /opt/hmi-python. Pass --python <tarball> with "
            "a python-build-standalone aarch64 install_only build; provisioning "
            "installs it at /opt/hmi-python."
        )
    if facts.get("systemctl", "MISSING") == "MISSING":
        blockers.append(
            "systemd is not present. This platform ships as systemd units; a "
            "container-based image (TorizonOS and similar) is not a supported target."
        )
    if facts.get("rootfs_rw") == "no":
        blockers.append(
            "The root filesystem is read-only. Remount it read-write, or build the "
            "meta-hmi layer into the image instead of provisioning."
        )
    if not facts.get("drm_cards", "").strip():
        blockers.append(
            "No /dev/dri/card* device. hmi-ui draws straight to DRM/KMS; without a "
            "DRM device there is nothing to draw on."
        )
    if not facts.get("libdrm", "").strip():
        blockers.append(
            "libdrm.so.2 is not installed. hmi-ui links against it (the Toradex "
            "reference images ship it; a minimal image needs the libdrm package)."
        )

    warnings = []
    if facts.get("weston_unit", "0") != "0" or facts.get("qt_loader") == "present":
        warnings.append(
            "This panel carries the compositor and/or the Qt loader from an earlier "
            "provisioning. hmi-ui.service conflicts with them and takes the display; "
            "install.sh removes the Qt loader files (pass --keep-qt to keep them)."
        )
    if facts.get("flock", "MISSING") == "MISSING":
        warnings.append("flock is missing; concurrent installs will not be serialised.")
    if facts.get("docker") == "present":
        warnings.append(
            "A container runtime is present. If the display is currently driven "
            "from a container, stop it before deploying or the two will fight over "
            "the DRM device."
        )

    for w in warnings:
        print(f"\n  WARNING: {w}")
    for b in blockers:
        print(f"\n  BLOCKER: {b}")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the EmbeddedDisplay Studio platform onto a running panel over SSH.",
    )
    parser.add_argument("--host", required=True, help="Panel IP or hostname")
    parser.add_argument("--user", default="root", help="SSH user (default: root)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("--key", default=None, help="Path to the SSH private key")
    parser.add_argument("--check", action="store_true",
                        help="Survey the board and exit without writing anything")
    parser.add_argument("--force", action="store_true",
                        help="Provision even if the survey found blockers")
    parser.add_argument("--force-config", action="store_true",
                        help="Overwrite /etc/hmi/hwd.json and /etc/default/hmi-ui")
    parser.add_argument("--python", default=None, metavar="TARBALL",
                        help="A python-build-standalone aarch64 install_only .tar.gz to "
                             "install as /opt/hmi-python when the panel has no usable "
                             "interpreter (the daemon's gpiod/pyserial wheels are fetched "
                             "with pip download and shipped beside it)")
    parser.add_argument("--force-python", action="store_true",
                        help="Replace an existing /opt/hmi-python with --python's")
    parser.add_argument("--keep-qt", action="store_true",
                        help="Leave the Qt loader, its Qt6 runtime and Weston in place "
                             "(disabled) instead of removing them from the panel")
    parser.add_argument("--enable-hwd", action="store_true",
                        help="Enable and start hmi-hwd.service (verify hwd.json first: "
                             "it drives real GPIO outputs)")
    args = parser.parse_args()

    base = ssh_base(args.host, args.user, args.port, args.key)
    target = f"{args.user}@{args.host}"

    print(f"\n== Surveying {target} ==")
    code, output = run(base + [PREFLIGHT], echo=False)
    if code != 0:
        print(f"  {output}")
        print(
            "\n  Could not connect. Note that BatchMode is on, so password "
            "authentication is never attempted -- install your key first:\n"
            f"      ssh-copy-id {target}"
        )
        return 1

    facts = parse_preflight(output)
    blockers = report_preflight(facts, args.python)

    if args.check:
        print("\n  --check: nothing was written.")
        return 1 if blockers else 0

    if blockers and not args.force:
        print("\n  Refusing to provision. Fix the blockers above, or pass --force.")
        return 1

    print(f"\n== Building payload ==")
    tmp_dir = tempfile.mkdtemp(prefix="hmi_provision_")
    tar_path = os.path.join(tmp_dir, "hmi_provision.tar.gz")
    wheel_dir = None
    if args.python:
        if not os.path.isfile(args.python):
            print(f"  --python: no such file: {args.python}")
            return 1
        wheel_dir = fetch_wheels(os.path.join(tmp_dir, "wheels"))
    packed = build_payload(tar_path, args.python, wheel_dir)
    size_kb = os.path.getsize(tar_path) / 1024
    print(f"  {packed} files, {size_kb:.0f} KB")

    print(f"\n== Uploading ==")
    code, _ = run(base + [f"rm -rf {REMOTE_STAGE} && mkdir -p {REMOTE_STAGE}"])
    if code != 0:
        print("  Could not create the staging directory.")
        return 1
    code, _ = run(scp_cmd(args.host, args.user, args.port, args.key,
                          tar_path, f"{REMOTE_STAGE}/hmi_provision.tar.gz"))
    if code != 0:
        print("  Upload failed.")
        return 1

    print(f"\n== Installing ==")
    env = []
    if args.force_config:
        env.append("HMI_FORCE_CONFIG=1")
    if args.enable_hwd:
        env.append("HMI_ENABLE_HWD=1")
    if args.keep_qt:
        env.append("HMI_KEEP_QT=1")
    if args.force_python:
        env.append("HMI_FORCE_PYTHON=1")
    prefix = (" ".join(env) + " ") if env else ""
    remote = (
        f"cd {REMOTE_STAGE} && tar -xzf hmi_provision.tar.gz && "
        f"{prefix}sh install.sh; rc=$?; cd /; rm -rf {REMOTE_STAGE}; exit $rc"
    )
    code, output = run(base + [remote])

    if code != 0:
        print(f"\n  Provisioning FAILED (exit {code}).")
        return code

    # Re-provisioning a panel that already has an application is a normal way to
    # update the platform under a running app, so report which case this was
    # rather than always claiming the panel is empty.
    _, current = run(base + ["readlink /opt/hmi_apps/current 2>/dev/null || true"],
                     echo=False)
    current = current.strip()

    if current:
        print(
            f"\n  Panel provisioned. The installed application was left in place:\n"
            f"      {current}\n"
            "  install.sh restarted hmi-ui.service on it."
        )
    else:
        print(
            "\n  Panel provisioned. hmi-ui.service is enabled and shows its fallback "
            "screen -- there is no application on it yet.\n"
            "  Deploy one from the Studio, or:\n"
            f"      ./deploy/deploy_to_hmi.sh -H {args.host} -b ./my-design"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
