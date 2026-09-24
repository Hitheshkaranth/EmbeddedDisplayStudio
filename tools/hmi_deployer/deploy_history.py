"""
tools/hmi_deployer/deploy_history.py
Layer: Core
Immutable deployment history entries and timeline merging utilities.
No filesystem persistence, Qt, network, or remote behavior.
"""

from collections import namedtuple
import copy


# ---------------------------------------------------------------------------
# Immutable entry
# ---------------------------------------------------------------------------

DeployHistoryEntry = namedtuple(
    "DeployHistoryEntry",
    (
        "timestamp",
        "bundle_name",
        "version",
        "target",
        "result",
        "stage",
        "detail",
        "rollback",
    ),
    defaults=(None,) * 8,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_history(entries, entry, limit=50):
    """Return a *new* tuple of DeployHistoryEntry objects.

    * *entries* – existing history (tuple of DeployHistoryEntry).
    * *entry*  – a single DeployHistoryEntry to append.
    * *limit*  – maximum number of entries kept (default 50).

    The returned tuple is **newest-first** and bounded to *limit* entries.
    The original *entries* tuple is never mutated.
    """
    if not isinstance(entries, tuple):
        entries = tuple(entries)

    new_entries = (entry,) + entries
    if len(new_entries) > limit:
        new_entries = new_entries[:limit]
    return new_entries


def merge_timeline(deploy_entries, log_entries):
    """Merge deploy and log records into a single timestamp-descending tuple.

    Parameters
    ----------
    deploy_entries : iterable of dict
        Each dict must contain at least a ``"timestamp"`` key.  Additional
        keys are preserved verbatim.  The source is labelled ``"source":
        "deploy"``.
    log_entries : iterable of dict
        Same shape as *deploy_entries* but labelled ``"source": "log"``.

    Returns
    -------
    tuple of dict
        All records sorted by ``timestamp`` descending.  When timestamps are
        equal, records from *deploy_entries* are placed before *log_entries*
        (stable sort).  No causal relationship is inferred between deploy
        and log records.

    Raises
    ------
    ValueError
        If a record is missing a ``"timestamp"`` key.
    """
    merged = []

    for rec in deploy_entries:
        if "timestamp" not in rec:
            raise ValueError("deploy record missing 'timestamp' key")
        item = dict(rec)
        item["source"] = "deploy"
        merged.append(item)

    for rec in log_entries:
        if "timestamp" not in rec:
            raise ValueError("log record missing 'timestamp' key")
        item = dict(rec)
        item["source"] = "log"
        merged.append(item)

    # Deterministic: timestamp desc, then original order preserved for ties
    merged.sort(key=lambda x: x["timestamp"], reverse=True)

    return tuple(merged)