#!/usr/bin/env python3
"""historian -- CONTRACT 13.4 tag history for hmi-hwd. FROZEN API (wave 1, W4).

Stdlib only (sqlite3): it runs on the panel's /opt/hmi-python. hmi_hwd.py
creates one from hwd.json's "history" object, feeds it every published
numeric tag value, commits on its schedule and answers the "history"
command from it.

Schema: one table `samples(tag TEXT NOT NULL, ts INTEGER NOT NULL,
value REAL NOT NULL)` with an index on (tag, ts); ts is epoch milliseconds.

    python3 historian.py export --db PATH --tag T [--since SECONDS]

prints CSV "timestamp_iso,epoch_ms,tag,value" (header line first; value as
repr(float); ISO in UTC
with a trailing "Z", millisecond precision), oldest first.
"""
from __future__ import annotations

import time

PERIOD_MIN_MS, PERIOD_MAX_MS = 100, 3_600_000
RETENTION_MIN_D, RETENTION_MAX_D = 1, 365
COMMIT_EVERY_S = 5.0
PRUNE_EVERY_S = 3600.0
POINTS_MAX = 200
SECONDS_MAX = 604_800


class HistoryConfigError(ValueError):
    """hwd.json "history" is malformed; str(e) names the key."""


class Historian:
    """CONTRACT 13.4 logging rules.

    config: the "history" object -- "path" (required, str), "retention_days"
    (int 1..365, default 7), "tags" (object: tag or "*" ->
    {"period_ms": 100..3600000 (default 1000), "deadband": >= 0 (default 0)}).
    Anything else, or an out-of-range value: HistoryConfigError.
    `clock` returns epoch seconds (float); tests pass a fake.
    """

    def __init__(self, config: dict, clock=time.time):
        raise NotImplementedError

    def logs(self, tag: str) -> bool:
        """True when `tag` is listed or "*" is configured."""
        raise NotImplementedError

    def observe(self, tag: str, value, now: float | None = None) -> bool:
        """Offer one published value. Stores (buffers) a sample and returns
        True when: the value is a finite number (bools are not), the tag is
        logged, at least period_ms passed since the tag's last stored sample,
        and |value - last stored| > deadband or 60 * period_ms passed since
        it (the first value of a tag is always stored)."""
        raise NotImplementedError

    def maybe_commit(self, now: float | None = None) -> int:
        """Commit buffered samples when COMMIT_EVERY_S passed since the last
        commit; prune when PRUNE_EVERY_S passed since the last prune (and on
        the first call). Returns samples committed (0 when it did not commit)."""
        raise NotImplementedError

    def flush(self) -> int:
        """Commit everything buffered now (shutdown). Returns the count."""
        raise NotImplementedError

    def prune(self, now: float | None = None) -> int:
        """Delete samples older than retention_days; returns rows deleted."""
        raise NotImplementedError

    def query(self, tag: str, seconds: int = 3600, points: int = 200,
              now: float | None = None) -> list:
        """[[epoch_ms, value], ...] oldest first for (now - seconds, now],
        including buffered (uncommitted) samples. More than `points`: split
        the window into `points` equal buckets and keep each non-empty
        bucket's last sample. seconds/points outside 1..SECONDS_MAX /
        1..POINTS_MAX: ValueError."""
        raise NotImplementedError

    def close(self) -> None:
        """flush() and close the database."""
        raise NotImplementedError


def from_config(config) -> "Historian | None":
    """None when `config` is None (no "history" key); else Historian(config)."""
    raise NotImplementedError


def export_csv(db_path: str, tag: str, since_s: float | None, out, now: float | None = None) -> int:
    """Write the CSV described above to the text stream `out`; returns rows."""
    raise NotImplementedError


def main(argv=None) -> int:
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
