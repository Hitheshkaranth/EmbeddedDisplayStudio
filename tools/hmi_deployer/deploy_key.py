"""Deploy key bundles: hand a colleague what they need to deploy to a panel.

A panel trusts one SSH key (its /root/.ssh/authorized_keys). The person who
provisioned it has that key; nobody else can deploy until they do too, and
"copy this file from my ~/.ssh, then type the host, user and port" is how
keys get pasted into chats. A ``.hmikey`` bundle is one file that carries
the key pair and the target's address, and importing it installs the key
where OpenSSH will accept it and fills the Studio's connection fields.

    python -m tools.hmi_deployer.deploy_key export --key ~/.ssh/id_ed25519 \\
        --host 172.16.20.70 --out line3-panel.hmikey
    python -m tools.hmi_deployer.deploy_key import line3-panel.hmikey

The bundle is a plain zip: it holds a private key, so it is to be passed
hand to hand, not posted. Encrypting it would only move the secret into a
passphrase that would travel by the same channel.
"""
from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from typing import Optional

BUNDLE_SUFFIX = ".hmikey"
BUNDLE_FORMAT = 1
# Where imported keys live; one file per bundle, never touching id_* keys.
INSTALL_DIR = os.path.join(os.path.expanduser("~"), ".ssh", "hmi-deploy")
DEFAULT_KEYS = ("id_ed25519", "id_ecdsa", "id_rsa")


class DeployKeyError(Exception):
    pass


def default_private_key() -> str:
    """The key OpenSSH would offer by itself when no -i is given."""
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    for name in DEFAULT_KEYS:
        path = os.path.join(ssh_dir, name)
        if os.path.isfile(path):
            return path
    return ""


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _check_private_key(data: bytes) -> None:
    text = data.decode("ascii", errors="ignore")
    if "PRIVATE KEY" not in text:
        raise DeployKeyError("that file is not an SSH private key")
    # PEM keys say so in a header; OpenSSH-format keys hide it in the
    # base64, which ssh-keygen can tell without the passphrase.
    if "Proc-Type: 4,ENCRYPTED" in text or _openssh_key_is_encrypted(text):
        raise DeployKeyError("the private key is passphrase-protected; the Studio deploys with "
                             "BatchMode and cannot prompt for it -- export an unencrypted deploy key")


def _openssh_key_is_encrypted(text: str) -> bool:
    """True for an "OPENSSH PRIVATE KEY" whose cipher is not "none"."""
    import base64
    if "OPENSSH PRIVATE KEY" not in text:
        return False
    body = "".join(line for line in text.splitlines() if not line.startswith("-----"))
    try:
        raw = base64.b64decode(body)
    except ValueError:
        return False
    # magic "openssh-key-v1" + NUL, then a length-prefixed cipher name.
    magic = b"openssh-key-v1" + bytes([0])
    if not raw.startswith(magic):
        return False
    offset = len(magic)
    length = int.from_bytes(raw[offset:offset + 4], "big")
    cipher = raw[offset + 4:offset + 4 + length]
    return cipher != b"none"


def scan_host_keys(host: str, port: int = 22, timeout_s: int = 8) -> list:
    """The panel's SSH host keys as known_hosts lines, or [] when unreachable.

    Carried in the bundle so the importing machine trusts the panel at
    once. Without them, a known_hosts that already holds another board's
    key for the same DHCP address fails with "Host key verification
    failed" -- which is what "the key does not work" usually means.
    """
    try:
        result = subprocess.run(["ssh-keyscan", "-p", str(port), "-T", str(timeout_s), host],
                                capture_output=True, text=True, timeout=timeout_s + 5, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines()
            if line.strip() and not line.startswith("#")]


def known_hosts_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".ssh", "known_hosts")


def forget_host(host: str, port: int = 22) -> None:
    """Drop every known_hosts entry for the panel's address (both spellings)."""
    for name in {host, f"[{host}]:{port}"}:
        subprocess.run(["ssh-keygen", "-R", name, "-f", known_hosts_path()],
                       capture_output=True, check=False)


def install_host_keys(host: str, port: int, lines: list) -> int:
    """Replace the known_hosts entries for ``host`` with ``lines``.

    Returns the number of lines written.
    """
    if not lines:
        return 0
    ssh_dir = os.path.dirname(known_hosts_path())
    os.makedirs(ssh_dir, exist_ok=True)
    forget_host(host, port)
    with open(known_hosts_path(), "a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line.rstrip() + "\n")
    return len(lines)


def verify_key(private_key: str, host: str, user: str = "root", port: int = 22,
               timeout_s: int = 15) -> tuple:
    """Try the key, and only the key, against the panel.

    Returns:
        (ok, reason) -- reason is one of "ok", "no-ssh", "unreachable",
        "host-key", "refused", "permissions", "unknown", with the transport's
        own last line appended after a colon for the console.
    """
    if not shutil.which("ssh"):
        return False, "no-ssh: the OpenSSH client (ssh.exe) is not installed or not on PATH"
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
           "-o", "StrictHostKeyChecking=accept-new", "-o", f"ConnectTimeout={timeout_s}",
           "-i", private_key, "-p", str(port), f"{user}@{host}", "echo HMI-KEY-OK"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 10, check=False)
    except subprocess.TimeoutExpired:
        return False, "unreachable: the panel did not answer"
    except OSError as exc:
        return False, f"no-ssh: {exc}"
    if "HMI-KEY-OK" in result.stdout:
        return True, "ok"
    err = " ".join(line.strip() for line in result.stderr.splitlines()
                   if line.strip() and not line.startswith("**")).strip()
    low = err.lower()
    if "host key verification failed" in low or "remote host identification has changed" in low:
        return False, "host-key: " + err[-160:]
    if "permission denied" in low:
        return False, "refused: the panel does not trust this key (it is not in /root/.ssh/authorized_keys): " + err[-120:]
    if "permissions" in low and ("too open" in low or "bad permissions" in low):
        return False, "permissions: the key file is readable by others and ssh refuses it: " + err[-120:]
    if "timed out" in low or "no route" in low or "could not resolve" in low or "connection refused" in low:
        return False, "unreachable: " + err[-160:]
    return False, "unknown: " + (err[-200:] or f"ssh exited {result.returncode}")


def working_key_for(host: str, user: str = "root", port: int = 22, candidates=()) -> tuple:
    """The first key among ``candidates`` then the ~/.ssh defaults that the
    panel accepts, with the reasons the others gave: (key_or_"", reasons)."""
    reasons = []
    seen = []
    ssh_dir = os.path.join(os.path.expanduser("~"), ".ssh")
    for path in list(candidates) + [os.path.join(ssh_dir, n) for n in DEFAULT_KEYS]:
        if not path or path in seen or not os.path.isfile(path):
            continue
        seen.append(path)
        ok, reason = verify_key(path, host, user, port)
        if ok:
            return path, reasons
        reasons.append(f"{path}: {reason}")
        if reason.startswith(("no-ssh", "unreachable", "host-key")):
            break     # not the key's fault; trying more keys says nothing
    return "", reasons


def export_bundle(private_key: str, out_path: str, host: str, user: str = "root",
                  port: int = 22, public_key: Optional[str] = None, label: str = "",
                  host_keys: Optional[list] = None) -> str:
    """Write ``out_path`` (a .hmikey zip) from a private key and a target.

    Args:
        private_key: path to the private key the panel trusts.
        out_path: where to write; the suffix is added when missing.
        host, user, port: the panel the key opens.
        public_key: path to the matching .pub; defaults to private_key + ".pub"
            and is optional -- the panel already holds the public half.
        label: a short name shown on import (defaults to the host).
        host_keys: known_hosts lines for the panel; scanned from the panel
            when None (and left out when it cannot be reached).

    Returns:
        The path written.

    Raises:
        DeployKeyError: no key, an encrypted key, or a bad target.
    """
    if not private_key or not os.path.isfile(private_key):
        raise DeployKeyError("no private key to export -- point the Studio's Key field at one "
                             "or keep the default key in ~/.ssh")
    if not host.strip():
        raise DeployKeyError("the bundle needs the panel's host or IP")
    data = _read(private_key)
    _check_private_key(data)
    if not out_path.lower().endswith(BUNDLE_SUFFIX):
        out_path += BUNDLE_SUFFIX
    pub_path = public_key or private_key + ".pub"
    manifest = {
        "format": BUNDLE_FORMAT,
        "label": label.strip() or host.strip(),
        "target": {"host": host.strip(), "user": user.strip() or "root", "port": int(port or 22)},
        "key_file": os.path.basename(private_key),
        "host_keys": scan_host_keys(host.strip(), int(port or 22)) if host_keys is None else list(host_keys),
        "exported_by": f"{getpass.getuser()}@{socket.gethostname()}",
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", json.dumps(manifest, indent=2))
        archive.writestr("key/" + manifest["key_file"], data)
        if os.path.isfile(pub_path):
            archive.writestr("key/" + manifest["key_file"] + ".pub", _read(pub_path))
    return out_path


def read_bundle(bundle_path: str) -> dict:
    """The bundle's manifest, validated; raises DeployKeyError when it is not one."""
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            manifest = json.loads(archive.read("bundle.json"))
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DeployKeyError(f"not a deploy key bundle: {exc}") from None
    if manifest.get("format") != BUNDLE_FORMAT or "key/" + manifest.get("key_file", "") not in names:
        raise DeployKeyError("deploy key bundle has an unknown layout")
    target = manifest.get("target") or {}
    if not target.get("host"):
        raise DeployKeyError("deploy key bundle names no panel")
    return manifest


def _restrict_to_owner(path: str) -> None:
    """Make OpenSSH accept the key: 0600 on POSIX, owner-only ACL on Windows."""
    if platform.system() == "Windows":
        user = os.environ.get("USERNAME") or getpass.getuser()
        for cmd in (["icacls", path, "/inheritance:r"],
                    ["icacls", path, "/grant:r", f"{user}:F"]):
            subprocess.run(cmd, capture_output=True, check=False)
    else:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def import_bundle(bundle_path: str, install_dir: str = INSTALL_DIR) -> dict:
    """Install the bundle's key and return the connection it opens.

    Returns:
        {"key": <installed private key path>, "host":..., "user":..., "port":...,
         "label":..., "exported_by":..., "exported_at":...}
    """
    manifest = read_bundle(bundle_path)
    stem = os.path.splitext(os.path.basename(bundle_path))[0] or "deploy"
    os.makedirs(install_dir, exist_ok=True)
    if platform.system() != "Windows":
        os.chmod(install_dir, stat.S_IRWXU)
    key_path = os.path.join(install_dir, stem)
    with zipfile.ZipFile(bundle_path) as archive:
        with open(key_path, "wb") as handle:
            handle.write(archive.read("key/" + manifest["key_file"]))
        pub_name = "key/" + manifest["key_file"] + ".pub"
        if pub_name in archive.namelist():
            with open(key_path + ".pub", "wb") as handle:
                handle.write(archive.read(pub_name))
    _restrict_to_owner(key_path)
    target = manifest["target"]
    port = int(target.get("port", 22))
    trusted = install_host_keys(target["host"], port, manifest.get("host_keys") or [])
    return {"key": key_path, "host": target["host"], "user": target.get("user", "root"),
            "port": port, "label": manifest.get("label", ""), "host_keys_installed": trusted,
            "exported_by": manifest.get("exported_by", ""), "exported_at": manifest.get("exported_at", "")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export or import an HMI deploy key bundle.")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export", help="pack a key and a panel address into a .hmikey")
    exp.add_argument("--key", default="", help="private key (default: the ~/.ssh id_* key)")
    exp.add_argument("--host", required=True)
    exp.add_argument("--user", default="root")
    exp.add_argument("--port", type=int, default=22)
    exp.add_argument("--label", default="")
    exp.add_argument("--out", required=True)
    exp.add_argument("--no-verify", action="store_true",
                     help="pack without trying the key against the panel (offline)")
    imp = sub.add_parser("import", help="install a .hmikey and print the connection it opens")
    imp.add_argument("bundle")
    ver = sub.add_parser("verify", help="try a key, and only that key, against a panel")
    ver.add_argument("--key", default="")
    ver.add_argument("--host", required=True)
    ver.add_argument("--user", default="root")
    ver.add_argument("--port", type=int, default=22)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            key = args.key or default_private_key()
            ok, reason = (True, "ok") if args.no_verify else verify_key(key, args.host, args.user, args.port)
            if not ok:
                chosen, reasons = working_key_for(args.host, args.user, args.port, [key])
                if not chosen:
                    raise DeployKeyError("no key opens the panel:\n  " + "\n  ".join(reasons))
                print(f"{key} is not accepted by {args.host}; exporting {chosen}, which is")
                key = chosen
            path = export_bundle(key, args.out, args.host, args.user, args.port, label=args.label)
            print(f"wrote {path} -- hand it over in person; it contains a private key")
        elif args.command == "verify":
            ok, reason = verify_key(args.key or default_private_key(), args.host, args.user, args.port)
            print("ok" if ok else reason)
            return 0 if ok else 1
        else:
            info = import_bundle(args.bundle)
            print(f"installed {info['key']}")
            if info["host_keys_installed"]:
                print(f"trusted the panel's host key(s) in {known_hosts_path()}")
            else:
                print("bundle carried no host key; the first connect accepts the panel's")
            print(f"target {info['user']}@{info['host']}:{info['port']}  ({info['label']}, "
                  f"exported by {info['exported_by']} {info['exported_at']})")
            ok, reason = verify_key(info["key"], info["host"], info["user"], info["port"])
            print("link: ok -- deploy away" if ok else f"link: {reason}")
            return 0 if ok else 1
    except DeployKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
