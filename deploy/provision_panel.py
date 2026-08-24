#!/usr/bin/env python3
"""
deploy/provision_panel.py
Layer: 3 (Host Deployer)
Purpose: Install the EmbeddedDisplay platform onto a running panel over SSH,
without rebuilding or reflashing an image.

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
    ("target/bin/hmi-gui-launch",           "usr/bin/hmi-gui-launch"),
    ("daemon/hmi_hwd.py",                   "usr/lib/hmi/hmi_hwd.py"),
    ("daemon/hwd.json",                     "etc/hmi/hwd.json"),
    ("target/etc/default/hmi-gui",          "etc/default/hmi-gui"),
    ("target/systemd/hmi-gui.service",      "etc/systemd/system/hmi-gui.service"),
    ("target/systemd/hmi-hwd.service",      "etc/systemd/system/hmi-hwd.service"),
    ("target/tmpfiles/hmi.conf",            "usr/lib/tmpfiles.d/hmi.conf"),
]

# Whole directories. The loader resolves its shell relative to its own location
# and adds /usr/lib/hmi/qml to the QML import path, so this arrangement is load
# bearing -- see gui/hmi_loader/main.py.
TREE_PAYLOAD: List[Tuple[str, str]] = [
    ("gui/hmi_loader", "usr/lib/hmi/gui"),
    ("gui/shell",      "usr/lib/hmi/shell"),
    ("ui/qml",         "usr/lib/hmi/qml"),
]

# Skipped when packing the trees above.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = (".pyc", ".pyo")

# One command, so a single round trip answers every question that decides
# whether this board can host the platform.
PREFLIGHT = r"""
echo "uname: $(uname -srm)"
echo "os: $( (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME") || echo unknown)"
echo "python3: $(command -v python3 >/dev/null 2>&1 && python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))' || echo MISSING)"
echo "pyside6: $(python3 -c 'import PySide6,sys;print(PySide6.__version__)' 2>/dev/null || echo MISSING)"
echo "systemctl: $(command -v systemctl >/dev/null 2>&1 && echo present || echo MISSING)"
echo "systemd_running: $(systemctl is-system-running 2>/dev/null || echo no)"
echo "weston_unit: $(systemctl list-unit-files 2>/dev/null | grep -c '^weston.service' || echo 0)"
echo "wayland_socket: $(ls /run/user/*/wayland-* 2>/dev/null | head -1 || echo NONE)"
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
    if os.path.splitext(path)[1].lower() in TEXT_SUFFIXES:
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


def build_payload(out_path: str) -> int:
    """
    Packs everything the target needs into one tarball.

    Args:
        out_path: where to write the .tar.gz.

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
                raise FileNotFoundError(f"payload source missing: {src_rel}")
            _add(tar, _normalised(src), f"files/{dest_rel}")
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


def report_preflight(facts: dict) -> List[str]:
    """
    Prints the survey and returns the list of blocking problems.

    Args:
        facts: parsed preflight output.

    Returns:
        Human-readable blockers; empty means the board can host the platform.
    """
    print("\n  Board survey")
    print("  " + "-" * 58)
    for key in ("uname", "os", "python3", "pyside6", "systemctl", "systemd_running",
                "weston_unit", "wayland_socket", "flock", "tar", "sha256sum",
                "docker", "existing_hmi_install", "rootfs_rw", "free_root"):
        if key in facts:
            print(f"  {key:22} {facts[key]}")
    print("  " + "-" * 58)

    blockers = []
    if facts.get("python3", "MISSING") == "MISSING":
        blockers.append(
            "python3 is not installed. hmi-install uses it for the atomic symlink "
            "swap and manifest validation, and the GUI loader is written in it."
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

    warnings = []
    if facts.get("pyside6", "MISSING") == "MISSING":
        warnings.append(
            "PySide6 is not installed. QML bundles and the GUI loader will not run "
            "until it is; a runtime:python bundle needs it too unless the app "
            "brings its own Qt."
        )
    if facts.get("weston_unit", "0") == "0":
        warnings.append(
            "No weston.service on this board. hmi-gui.service declares "
            "Requires=weston.service, so it will not start at boot until a "
            "compositor unit by that name exists."
        )
    if facts.get("flock", "MISSING") == "MISSING":
        warnings.append("flock is missing; concurrent installs will not be serialised.")
    if facts.get("docker") == "present":
        warnings.append(
            "A container runtime is present. If the display is currently driven "
            "from a container, stop it before deploying or the two will fight over "
            "the compositor."
        )

    for w in warnings:
        print(f"\n  WARNING: {w}")
    for b in blockers:
        print(f"\n  BLOCKER: {b}")
    return blockers


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the EmbeddedDisplay platform onto a running panel over SSH.",
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
                        help="Overwrite /etc/hmi/hwd.json and /etc/default/hmi-gui")
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
    blockers = report_preflight(facts)

    if args.check:
        print("\n  --check: nothing was written.")
        return 1 if blockers else 0

    if blockers and not args.force:
        print("\n  Refusing to provision. Fix the blockers above, or pass --force.")
        return 1

    print(f"\n== Building payload ==")
    tmp_dir = tempfile.mkdtemp(prefix="hmi_provision_")
    tar_path = os.path.join(tmp_dir, "hmi_provision.tar.gz")
    packed = build_payload(tar_path)
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
            "  Restart it to pick up the updated platform:\n"
            f"      ssh {target} systemctl restart hmi-gui.service"
        )
    else:
        print(
            "\n  Panel provisioned. hmi-gui.service is enabled but not started -- "
            "there is no application on it yet.\n"
            "  Deploy one with App Studio, or:\n"
            f"      ./deploy/deploy_to_hmi.sh -H {args.host} -b ./my-qt-app"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
