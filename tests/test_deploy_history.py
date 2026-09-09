"""
tests/test_deploy_history.py
Layer: Test (W11)
Unit tests for tools/hmi_deployer/deploy_history.
"""

import unittest
from collections import namedtuple

from tools.hmi_deployer.deploy_history import (
    DeployHistoryEntry,
    append_history,
    merge_timeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(ts="2025-01-01T00:00:00Z", **kwargs):
    """Convenience factory for DeployHistoryEntry."""
    defaults = dict(
        timestamp=ts,
        bundle_name="app-bundle",
        version="1.0.0",
        target="prod",
        result="success",
        stage="deploy",
        detail="",
        rollback=False,
    )
    defaults.update(kwargs)
    return DeployHistoryEntry(**defaults)


# ---------------------------------------------------------------------------
# DeployHistoryEntry – immutability / structure
# ---------------------------------------------------------------------------

class TestDeployHistoryEntry(unittest.TestCase):
    """Verify the namedtuple contract."""

    def test_fields(self):
        self.assertEqual(
            DeployHistoryEntry._fields,
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
        )

    def test_immutable(self):
        e = _entry()
        with self.assertRaises(AttributeError):
            e.timestamp = "modified"

    def test_defaults(self):
        e = DeployHistoryEntry()
        self.assertIsNone(e.timestamp)
        self.assertIsNone(e.bundle_name)
        self.assertIsNone(e.version)
        self.assertIsNone(e.target)
        self.assertIsNone(e.result)
        self.assertIsNone(e.stage)
        self.assertIsNone(e.detail)
        self.assertIsNone(e.rollback)


# ---------------------------------------------------------------------------
# append_history – bounded, newest-first, immutable
# ---------------------------------------------------------------------------

class TestAppendHistory(unittest.TestCase):
    """Tests for append_history()."""

    def test_empty_input(self):
        result = append_history((), _entry(ts="2025-06-01T00:00:00Z"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].timestamp, "2025-06-01T00:00:00Z")

    def test_single_append(self):
        e1 = _entry(ts="2025-01-01T00:00:00Z")
        result = append_history((), e1)
        self.assertEqual(result, (e1,))

    def test_newest_first(self):
        e1 = _entry(ts="2025-01-01T00:00:00Z")
        e2 = _entry(ts="2025-06-01T00:00:00Z")
        result = append_history((e1,), e2)
        self.assertEqual(result[0], e2)
        self.assertEqual(result[1], e1)

    def test_limit_enforced(self):
        entries = tuple(_entry(ts=f"2025-01-{T:02d}T00:00:00Z") for T in range(1, 11))
        result = append_history(entries, _entry(ts="2025-02-01T00:00:00Z"), limit=5)
        self.assertEqual(len(result), 5)
        # append_history prepends the new entry and slices; entries were
        # ordered oldest-first so the first 5 after the prepend are:
        self.assertEqual(result[0].timestamp, "2025-02-01T00:00:00Z")
        self.assertEqual(result[4].timestamp, "2025-01-04T00:00:00Z")

    def test_limit_zero(self):
        e1 = _entry(ts="2025-01-01T00:00:00Z")
        result = append_history((), e1, limit=0)
        self.assertEqual(len(result), 0)

    def test_original_unchanged(self):
        e1 = _entry(ts="2025-01-01T00:00:00Z")
        original = (e1,)
        result = append_history(original, _entry(ts="2025-06-01T00:00:00Z"))
        self.assertEqual(len(original), 1)
        self.assertEqual(len(result), 2)

    def test_limit_preserves_newest_first(self):
        entries = tuple(_entry(ts=f"2025-01-{T:02d}T00:00:00Z") for T in range(1, 20))
        result = append_history(entries, _entry(ts="2025-03-01T00:00:00Z"), limit=10)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0].timestamp, "2025-03-01T00:00:00Z")
        # append_history prepends the new entry and slices the top N;
        # the entries were ordered oldest-first (day 1 → 19).
        self.assertEqual(result[1].timestamp, "2025-01-01T00:00:00Z")
        self.assertEqual(result[9].timestamp, "2025-01-09T00:00:00Z")


# ---------------------------------------------------------------------------
# merge_timeline – normalization, labelling, ordering
# ---------------------------------------------------------------------------

class TestMergeTimeline(unittest.TestCase):
    """Tests for merge_timeline()."""

    def test_empty_inputs(self):
        result = merge_timeline([], [])
        self.assertEqual(result, ())

    def test_deploy_only(self):
        d1 = {"timestamp": "2025-01-01T00:00:00Z", "bundle": "a"}
        result = merge_timeline([d1], [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "deploy")
        self.assertEqual(result[0]["bundle"], "a")

    def test_log_only(self):
        l1 = {"timestamp": "2025-01-01T00:00:00Z", "message": "hello"}
        result = merge_timeline([], [l1])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "log")
        self.assertEqual(result[0]["message"], "hello")

    def test_mixed_descending_order(self):
        d1 = {"timestamp": "2025-01-01T00:00:00Z", "bundle": "a"}
        l1 = {"timestamp": "2025-06-01T00:00:00Z", "message": "b"}
        d2 = {"timestamp": "2025-03-01T00:00:00Z", "bundle": "c"}
        result = merge_timeline([d1, d2], [l1])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["timestamp"], "2025-06-01T00:00:00Z")
        self.assertEqual(result[1]["timestamp"], "2025-03-01T00:00:00Z")
        self.assertEqual(result[2]["timestamp"], "2025-01-01T00:00:00Z")

    def test_deploy_before_log_on_tie(self):
        ts = "2025-01-01T00:00:00Z"
        d1 = {"timestamp": ts, "bundle": "a"}
        l1 = {"timestamp": ts, "message": "b"}
        result = merge_timeline([d1], [l1])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source"], "deploy")
        self.assertEqual(result[1]["source"], "log")

    def test_multiple_ties_stable(self):
        ts = "2025-01-01T00:00:00Z"
        d1 = {"timestamp": ts, "bundle": "a"}
        d2 = {"timestamp": ts, "bundle": "b"}
        l1 = {"timestamp": ts, "message": "c"}
        l2 = {"timestamp": ts, "message": "d"}
        result = merge_timeline([d1, d2], [l1, l2])
        self.assertEqual(len(result), 4)
        # All have same timestamp; deploy entries first, then log entries,
        # preserving original order within each group.
        self.assertEqual(result[0]["source"], "deploy")
        self.assertEqual(result[1]["source"], "deploy")
        self.assertEqual(result[2]["source"], "log")
        self.assertEqual(result[3]["source"], "log")

    def test_preserves_extra_keys(self):
        d1 = {"timestamp": "2025-01-01T00:00:00Z", "extra_key": 42}
        result = merge_timeline([d1], [])
        self.assertEqual(result[0]["extra_key"], 42)

    def test_does_not_mutate_input(self):
        d1 = {"timestamp": "2025-01-01T00:00:00Z", "bundle": "a"}
        original_keys = set(d1.keys())
        merge_timeline([d1], [])
        self.assertEqual(set(d1.keys()), original_keys)
        self.assertNotIn("source", d1)

    def test_missing_timestamp_raises(self):
        with self.assertRaises(ValueError):
            merge_timeline([{"bundle": "a"}], [])

        with self.assertRaises(ValueError):
            merge_timeline([], [{"message": "hello"}])

    def test_no_causal_inference(self):
        """merge_timeline must never infer causal relationships between
        deploy and log records – it only sorts and labels."""
        d1 = {"timestamp": "2025-01-01T00:00:00Z", "result": "success"}
        l1 = {"timestamp": "2025-01-01T00:00:01Z", "message": "error"}
        result = merge_timeline([d1], [l1])
        # Both records are present, independently labelled.
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source"], "log")
        self.assertEqual(result[1]["source"], "deploy")
        # No field like "caused_by" or "linked_to" should exist.
        for item in result:
            self.assertNotIn("caused_by", item)
            self.assertNotIn("linked_to", item)


# ---------------------------------------------------------------------------
# Failed deploy / rollback scenarios
# ---------------------------------------------------------------------------

class TestFailedDeployRollback(unittest.TestCase):
    """Tests covering failed deployments and rollback entries."""

    def test_failed_deploy(self):
        e = _entry(
            ts="2025-02-15T10:30:00Z",
            result="failure",
            stage="validate",
            detail="checksum mismatch",
            rollback=False,
        )
        result = append_history((), e)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].result, "failure")
        self.assertEqual(result[0].stage, "validate")
        self.assertEqual(result[0].detail, "checksum mismatch")
        self.assertFalse(result[0].rollback)

    def test_rollback_entry(self):
        e = _entry(
            ts="2025-02-15T11:00:00Z",
            result="rollback",
            stage="rollback",
            detail="reverted to previous version",
            rollback=True,
        )
        result = append_history((), e)
        self.assertTrue(result[0].rollback)
        self.assertEqual(result[0].result, "rollback")

    def test_mixed_success_failure_rollback(self):
        e_success = _entry(ts="2025-01-01T00:00:00Z", result="success")
        e_fail = _entry(
            ts="2025-02-01T00:00:00Z",
            result="failure",
            detail="timeout",
        )
        e_rb = _entry(
            ts="2025-03-01T00:00:00Z",
            result="rollback",
            rollback=True,
            detail="rolled back after failure",
        )
        history = append_history((), e_success)
        history = append_history(history, e_fail)
        history = append_history(history, e_rb)
        self.assertEqual(len(history), 3)
        # Newest first
        self.assertEqual(history[0].result, "rollback")
        self.assertEqual(history[1].result, "failure")
        self.assertEqual(history[2].result, "success")

    def test_rollback_in_timeline(self):
        d1 = {
            "timestamp": "2025-03-01T00:00:00Z",
            "bundle_name": "app",
            "result": "rollback",
            "rollback": True,
        }
        result = merge_timeline([d1], [])
        self.assertEqual(result[0]["source"], "deploy")
        self.assertEqual(result[0]["result"], "rollback")
        self.assertTrue(result[0]["rollback"])


# ---------------------------------------------------------------------------
# Mixed timeline ordering edge cases
# ---------------------------------------------------------------------------

class TestMixedTimelineOrdering(unittest.TestCase):
    """Edge-case tests for merge_timeline ordering."""

    def test_many_entries_sorted(self):
        deploy = [
            {"timestamp": f"2025-01-{T:02d}T00:00:00Z", "bundle": f"b{T}"}
            for T in range(1, 20)
        ]
        logs = [
            {"timestamp": f"2025-02-{T:02d}T00:00:00Z", "msg": f"m{T}"}
            for T in range(1, 15)
        ]
        result = merge_timeline(deploy, logs)
        self.assertEqual(len(result), 33)
        # Verify descending order
        for i in range(len(result) - 1):
            self.assertGreaterEqual(
                result[i]["timestamp"],
                result[i + 1]["timestamp"],
            )

    def test_timestamps_as_integers(self):
        """Timestamps can be integers (epoch seconds)."""
        d1 = {"timestamp": 1700000000, "bundle": "a"}
        l1 = {"timestamp": 1700000100, "msg": "b"}
        result = merge_timeline([d1], [l1])
        self.assertEqual(result[0]["timestamp"], 1700000100)
        self.assertEqual(result[1]["timestamp"], 1700000000)

    def test_string_timestamps_lexicographic(self):
        """ISO 8601 strings sort correctly lexicographically."""
        d1 = {"timestamp": "2025-12-31T23:59:59Z", "bundle": "a"}
        d2 = {"timestamp": "2025-01-01T00:00:00Z", "bundle": "b"}
        result = merge_timeline([d1, d2], [])
        self.assertEqual(result[0]["timestamp"], "2025-12-31T23:59:59Z")
        self.assertEqual(result[1]["timestamp"], "2025-01-01T00:00:00Z")

    def test_return_type_is_tuple(self):
        result = merge_timeline([], [])
        self.assertIsInstance(result, tuple)

    def test_append_history_returns_tuple(self):
        result = append_history((), _entry())
        self.assertIsInstance(result, tuple)


if __name__ == "__main__":
    unittest.main()