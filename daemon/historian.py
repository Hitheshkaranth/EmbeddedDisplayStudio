from __future__ import annotations

import argparse
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone

PERIOD_MIN_MS, PERIOD_MAX_MS = 100, 3_600_000
RETENTION_MIN_D, RETENTION_MAX_D = 1, 365
COMMIT_EVERY_S = 5.0
PRUNE_EVERY_S = 3600.0
POINTS_MAX = 200
SECONDS_MAX = 604_800
HOURS_PER_DAY = 24
MINUTES_PER_HOUR = 60
SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR * SECONDS_PER_MINUTE


class HistoryConfigError(ValueError):
    """hwd.json "history" is malformed; str(e) names the key."""


def _require_path(config) -> str:
    path = config.get("path")
    if not isinstance(path, str) or not path:
        raise HistoryConfigError("path")
    return path


def _require_retention(config) -> int:
    days = config.get("retention_days", 7)
    if isinstance(days, bool) or not isinstance(days, int) or not (1 <= days <= 365):
        raise HistoryConfigError("retention_days")
    return days


def _require_tag_cfg(tag: str, tcfg) -> tuple[int, float]:
    if not isinstance(tcfg, dict) or any(k not in ("period_ms", "deadband") for k in tcfg):
        raise HistoryConfigError(f"tag {tag!r}")
    period = tcfg.get("period_ms", 1000)
    if isinstance(period, bool) or not isinstance(period, (int, float)) \
            or not (PERIOD_MIN_MS <= period <= PERIOD_MAX_MS):
        raise HistoryConfigError(f"period_ms for {tag!r}")
    deadband = tcfg.get("deadband", 0.0)
    if isinstance(deadband, bool) or not isinstance(deadband, (int, float)) \
            or not math.isfinite(deadband) or deadband < 0:
        raise HistoryConfigError(f"deadband for {tag!r}")
    return period, float(deadband)


class Historian:
    """CONTRACT 13.4 logging rules.

    config: the "history" object -- "path" (required, str), "retention_days"
    (int 1..365, default 7), "tags" (object: tag or "*" ->
    {"period_ms": 100..3600000 (default 1000), "deadband": >= 0 (default 0)}).
    Anything else, or an out-of-range value: HistoryConfigError.
    `clock` returns epoch seconds (float); tests pass a fake.
    """

    def __init__(self, config: dict, clock=time.time):
        self._clock = clock
        if not isinstance(config, dict):
            raise HistoryConfigError("history")
        path = _require_path(config)
        self._retention_days = _require_retention(config)

        tags_cfg = config.get("tags", {})
        if not isinstance(tags_cfg, dict):
            raise HistoryConfigError("tags")
        # A single "*" entry, or {tag: (period_ms, deadband)} for named tags.
        self._star: tuple[int, float] | None = None
        self._named: dict[str, tuple[int, float]] = {}
        for tag, tcfg in tags_cfg.items():
            if tag == "*":
                self._star = _require_tag_cfg(tag, tcfg)
            else:
                self._named[tag] = _require_tag_cfg(tag, tcfg)
        if self._star is None and not self._named:
            raise HistoryConfigError("tags")

        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS samples "
            "(tag TEXT NOT NULL, ts INTEGER NOT NULL, value REAL NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sample_ts ON samples (tag, ts)"
        )
        self._conn.commit()

        # (period_ms, deadband, last_ts_ms, last_value) per logged tag.
        self._last: dict[str, tuple[int, float, int, float]] = {}
        # Buffered, not-yet-committed samples: list of (tag, ts_ms, value).
        self._buffer: list[tuple[str, int, float]] = []
        self._last_commit: float = clock()
        self._last_prune: float = clock()

    def logs(self, tag: str) -> bool:
        """True when `tag` is listed or "*" is configured."""
        return tag in self._named or self._star is not None

    def _tag_period(self, tag: str) -> tuple[int, float]:
        return self._named.get(tag, self._star)  # type: ignore[return-value]

    def observe(self, tag: str, value, now: float | None = None) -> bool:
        """Offer one published value. Stores (buffers) a sample and returns
        True when: the value is a finite number (bools are not), the tag is
        logged, at least period_ms passed since the tag's last stored sample,
        and |value - last stored| > deadband or 60 * period_ms passed since
        it (the first value of a tag is always stored)."""
        if now is None:
            now = self._clock()
        if not self.logs(tag):
            return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            return False
        value = float(value)
        period_ms, deadband = self._tag_period(tag)
        last = self._last.get(tag)
        ts_ms = int(now * 1000)
        if last is None:
            self._last[tag] = (period_ms, deadband, ts_ms, value)
            self._buffer.append((tag, ts_ms, value))
            return True
        _, _, last_ms, last_val = last
        elapsed_ms = ts_ms - last_ms
        moved = abs(value - last_val) > deadband
        if elapsed_ms >= period_ms and (moved or elapsed_ms >= 60 * period_ms):
            self._last[tag] = (period_ms, deadband, ts_ms, value)
            self._buffer.append((tag, ts_ms, value))
            return True
        return False

    def maybe_commit(self, now: float | None = None) -> int:
        """Commit buffered samples when COMMIT_EVERY_S passed since the last
        commit; prune when PRUNE_EVERY_S passed since the last prune (and on
        the first call). Returns samples committed (0 when it did not commit)."""
        if now is None:
            now = self._clock()
        committed = 0
        if now - self._last_prune >= PRUNE_EVERY_S:
            self._prune_locked(now)
            self._last_prune = now
        if now - self._last_commit >= COMMIT_EVERY_S:
            committed = self._flush_locked()
            self._last_commit = now
        return committed

    def flush(self) -> int:
        """Commit everything buffered now (shutdown). Returns the count."""
        return self._flush_locked()

    def prune(self, now: float | None = None) -> int:
        """Delete samples older than retention_days; returns rows deleted."""
        if now is None:
            now = self._clock()
        self._prune_locked(now)
        self._last_prune = now
        # _prune_locked records the count on the connection; return it.
        count = self._pruned_rows
        self._pruned_rows = 0
        return count

    _pruned_rows = 0

    def _flush_locked(self) -> int:
        if not self._buffer:
            return 0
        rows = [(tag, ts, value) for tag, ts, value in self._buffer]
        self._buffer.clear()
        self._conn.executemany(
            "INSERT INTO samples (tag, ts, value) VALUES (?, ?, ?)", rows
        )
        self._conn.commit()
        return len(rows)

    def _prune_locked(self, now: float) -> None:
        cutoff_ms = int((now - self._retention_days * SECONDS_PER_DAY) * 1000)
        cur = self._conn.execute(
            "DELETE FROM samples WHERE ts < ?", (cutoff_ms,)
        )
        self._pruned_rows = cur.rowcount
        self._conn.commit()

    def query(self, tag: str, seconds: int = 3600, points: int = 200,
              now: float | None = None) -> list:
        """[[epoch_ms, value], ...] oldest first for (now - seconds, now],
        including buffered (uncommitted) samples. More than `points`: split
        the window into `points` equal buckets and keep each non-empty
        bucket's last sample. seconds/points outside 1..SECONDS_MAX /
        1..POINTS_MAX: ValueError."""
        if (not isinstance(seconds, int) or isinstance(seconds, bool)
                or not (1 <= seconds <= SECONDS_MAX)):
            raise ValueError("seconds")
        if (not isinstance(points, int) or isinstance(points, bool)
                or not (1 <= points <= POINTS_MAX)):
            raise ValueError("points")
        if now is None:
            now = self._clock()

        now_ms = int(now * 1000)
        lo_ms = now_ms - seconds * 1000
        rows = self._fetch(tag, lo_ms, now_ms)
        # Merge buffered samples over what was committed.
        for b_tag, b_ts, b_val in self._buffer:
            if b_tag == tag and lo_ms < b_ts <= now_ms:
                rows.append([b_ts, b_val])
        rows.sort(key=lambda r: r[0])

        if len(rows) <= points:
            return rows
        # Partition (lo_ms, now_ms] into `points` equal buckets.
        span = float(now_ms - lo_ms)
        buckets = [None] * points
        for ts, value in rows:
            # Buckets are (lo, hi]: a sample on a bucket's upper edge is its last.
            idx = math.ceil((ts - lo_ms) * points / span) - 1 if span > 0 else 0
            if idx < 0:
                idx = 0
            if idx >= points:
                idx = points - 1
            buckets[idx] = [ts, value]
        return [b for b in buckets if b is not None]

    def _fetch(self, tag: str, lo_ms: int, now_ms: int) -> list:
        cur = self._conn.execute(
            "SELECT ts, value FROM samples WHERE tag = ? AND ts > ? AND ts <= ? "
            "ORDER BY ts ASC",
            (tag, lo_ms, now_ms),
        )
        return [[ts, value] for ts, value in cur.fetchall()]

    def close(self) -> None:
        """flush() and close the database."""
        try:
            self._flush_locked()
        finally:
            self._conn.close()


def from_config(config) -> "Historian | None":
    """None when `config` is None (no "history" key); else Historian(config)."""
    if config is None:
        return None
    return Historian(config)


def export_csv(db_path: str, tag: str, since_s: float | None, out, now: float | None = None) -> int:
    """Write the CSV described above to the text stream `out`; returns rows."""
    if now is None:
        now = time.time()
    lo_ms = 0
    if since_s is not None:
        lo_ms = int(now * 1000) - int(since_s * 1000)
    cur = sqlite3.connect(db_path).execute(
        "SELECT ts, value FROM samples WHERE tag = ? AND ts >= ? ORDER BY ts ASC",
        (tag, lo_ms),
    )
    out.write("timestamp_iso,epoch_ms,tag,value\n")
    count = 0
    for ts_ms, value in cur.fetchall():
        out.write(_iso_from_ms(ts_ms) + f",{ts_ms},{tag},{repr(float(value))}\n")
        count += 1
    return count


def _iso_from_ms(ts_ms: int) -> str:
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts_ms % 1000:03d}Z"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export tag history as CSV.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--db", required=True)
    exp.add_argument("--tag", required=True)
    exp.add_argument("--since", type=float, default=None)
    args = parser.parse_args(argv)

    if args.cmd == "export":
        out = sys.stdout
        rows = export_csv(args.db, args.tag, args.since, out)
        return 0 if rows >= 0 else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())