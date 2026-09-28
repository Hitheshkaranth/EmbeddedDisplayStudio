"""Export a panel's tag history as CSV over SSH (CONTRACT 13.4). FROZEN API (wave 1, W4).

    python -m tools.hmi_deployer.history_export --host IP --tag eng.egt [--since 3600] [--out FILE]
          [--user root] [--port 22] [--key PATH] [--db /var/lib/hmi/history.db]

Runs `/opt/hmi-python/bin/python3 /usr/lib/hmi/historian.py export --db DB
--tag TAG --since SECONDS` on the panel through tools.hmi_deployer.ssh and
writes its stdout to --out (default stdout).
"""
from __future__ import annotations

import argparse
import shlex

from tools.hmi_deployer.ssh import _signed_exit_code, build_ssh_cmd

REMOTE_PYTHON = "/opt/hmi-python/bin/python3"
REMOTE_HISTORIAN = "/usr/lib/hmi/historian.py"
DEFAULT_DB = "/var/lib/hmi/history.db"


def remote_command(tag: str, since_s: float | None, db: str = DEFAULT_DB) -> str:
    """The remote shell command, every argument shell-quoted (shlex.quote):
    "<REMOTE_PYTHON> <REMOTE_HISTORIAN> export --db <db> --tag <tag>"
    followed by " --since <'%g' % since_s>" when since_s is not None."""
    parts = [
        REMOTE_PYTHON,
        REMOTE_HISTORIAN,
        "export",
        "--db",
        db,
        "--tag",
        tag,
    ]
    if since_s is not None:
        parts.append("--since")
        parts.append("%g" % since_s)
    return " ".join(shlex.quote(p) for p in parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a panel's tag history as CSV over SSH (CONTRACT 13.4)."
    )
    parser.add_argument("--host", required=True, help="Panel IP or hostname")
    parser.add_argument("--tag", required=True, help="Tag name to export")
    parser.add_argument("--since", type=float, default=None,
                        help="Only samples within this many seconds")
    parser.add_argument("--out", default=None,
                        help="Write the CSV here (default stdout)")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help="Historian database on the panel")
    parser.add_argument("--user", default="root", help="SSH user (default root)")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default 22)")
    parser.add_argument("--key", default=None, help="Path to the SSH private key")
    args = parser.parse_args(argv)

    argv = build_ssh_cmd(args.host, args.user, args.port, args.key,
                         remote_command(args.tag, args.since, db=args.db))

    try:
        import subprocess
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace")
        out, _ = proc.communicate()
        code = _signed_exit_code(proc.returncode)
    except Exception:
        out, code = "", 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
