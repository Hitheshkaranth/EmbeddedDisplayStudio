"""Export a panel's tag history as CSV over SSH (CONTRACT 13.4). FROZEN API (wave 1, W4).

    python -m tools.hmi_deployer.history_export --host IP --tag eng.egt [--since 3600] [--out FILE]
         [--user root] [--port 22] [--key PATH] [--db /var/lib/hmi/history.db]

Runs `/opt/hmi-python/bin/python3 /usr/lib/hmi/historian.py export --db DB
--tag TAG --since SECONDS` on the panel through tools.hmi_deployer.ssh and
writes its stdout to --out (default stdout).
"""
from __future__ import annotations

REMOTE_PYTHON = "/opt/hmi-python/bin/python3"
REMOTE_HISTORIAN = "/usr/lib/hmi/historian.py"
DEFAULT_DB = "/var/lib/hmi/history.db"


def remote_command(tag: str, since_s: float | None, db: str = DEFAULT_DB) -> str:
    """The remote shell command, every argument shell-quoted (shlex.quote):
    "<REMOTE_PYTHON> <REMOTE_HISTORIAN> export --db <db> --tag <tag>"
    followed by " --since <'%g' % since_s>" when since_s is not None."""
    raise NotImplementedError


def main(argv=None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
