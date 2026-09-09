"""
tests/test_binding_diagnostics.py
Layer: Test (W11)
Unit tests for designer.model.binding_diagnostics.
"""

import os
import sys
import unittest
from collections import namedtuple

# Ensure repo root is on sys.path so absolute imports work from tests/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from designer.model.binding_diagnostics import DiagnosticRow, audit_bindings

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

# A simple binding-value object with a ``.tag`` attribute
BindingValue = namedtuple("BindingValue", ["tag"])

# A simple widget with ``.id`` and ``.bindings``
Widget = namedtuple("Widget", ["id", "bindings"])


class TestDiagnosticRow(unittest.TestCase):
    """Tests for the DiagnosticRow dataclass."""

    def test_immutable(self):
        row = DiagnosticRow(
            tag="x", widget_id="w", property="p", status="ready", detail="ok"
        )
        with self.assertRaises(Exception):
            row.tag = "y"

    def test_sort_order(self):
        r1 = DiagnosticRow(
            tag="a", widget_id="w1", property="x", status="ready", detail=""
        )
        r2 = DiagnosticRow(
            tag="a", widget_id="w2", property="x", status="ready", detail=""
        )
        r3 = DiagnosticRow(
            tag="b", widget_id="w1", property="x", status="ready", detail=""
        )
        self.assertLess(r1, r2)
        self.assertLess(r2, r3)


class TestAuditBindings(unittest.TestCase):
    """Tests for audit_bindings()."""

    # -- empty binding (error) -----------------------------------------------

    def test_empty_binding_none(self):
        widget = Widget(id="btn1", bindings={"text": None})
        rows = audit_bindings([widget], {"text"})
        statuses = [r.status for r in rows]
        self.assertIn("error", statuses)
        self.assertEqual(
            [r for r in rows if r.status == "error"][0].detail, "Empty binding"
        )

    def test_empty_binding_empty_string(self):
        widget = Widget(id="btn1", bindings={"text": ""})
        rows = audit_bindings([widget], {"text"})
        statuses = [r.status for r in rows]
        self.assertIn("error", statuses)

    def test_empty_binding_value_with_empty_tag(self):
        widget = Widget(id="btn1", bindings={"text": BindingValue("")})
        rows = audit_bindings([widget], {"text"})
        statuses = [r.status for r in rows]
        self.assertIn("error", statuses)

    # -- unknown tag (warning) -----------------------------------------------

    def test_unknown_tag(self):
        widget = Widget(id="btn1", bindings={"text": BindingValue("foo")})
        rows = audit_bindings([widget], {"bar"})
        self.assertEqual(len(rows), 2)
        # First row: warning for the unknown binding (sorted by tag "bar" < "foo")
        warning_row = [r for r in rows if r.status == "warning"][0]
        self.assertEqual(warning_row.tag, "foo")
        self.assertEqual(warning_row.status, "warning")
        self.assertEqual(warning_row.detail, "Tag not declared")
        # Second row: info for the unused declared tag
        info_row = [r for r in rows if r.status == "info"][0]
        self.assertEqual(info_row.tag, "bar")
        self.assertEqual(info_row.status, "info")
        self.assertEqual(info_row.detail, "Unused declared tag")

    # -- duplicate same tag/property use (info) ------------------------------

    def test_duplicate_tag_property(self):
        widget1 = Widget(id="btn1", bindings={"text": BindingValue("mytag")})
        widget2 = Widget(id="btn2", bindings={"text": BindingValue("mytag")})
        rows = audit_bindings([widget1, widget2], {"mytag"})
        info_rows = [r for r in rows if r.status == "info"]
        self.assertEqual(len(info_rows), 1)
        self.assertEqual(info_rows[0].widget_id, "btn2")
        self.assertEqual(info_rows[0].detail, "Duplicate tag/property use")

    # -- known / ready -------------------------------------------------------

    def test_known_tag_ready(self):
        widget = Widget(id="btn1", bindings={"text": BindingValue("mytag")})
        rows = audit_bindings([widget], {"mytag"})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.tag, "mytag")
        self.assertEqual(row.status, "ready")
        self.assertEqual(row.widget_id, "btn1")
        self.assertEqual(row.property, "text")

    # -- unused declared tag -------------------------------------------------

    def test_unused_declared_tag(self):
        widget = Widget(id="btn1", bindings={"text": BindingValue("other")})
        rows = audit_bindings([widget], {"unused"})
        unused_rows = [r for r in rows if r.tag == "unused"]
        self.assertEqual(len(unused_rows), 1)
        row = unused_rows[0]
        self.assertEqual(row.status, "info")
        self.assertEqual(row.widget_id, "")
        self.assertEqual(row.property, "")
        self.assertEqual(row.detail, "Unused declared tag")

    # -- dict bindings -------------------------------------------------------

    def test_dict_bindings(self):
        widget = Widget(id="btn1", bindings={"text": BindingValue("t1")})
        rows = audit_bindings([widget], {"t1"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "ready")

    # -- object-style bindings (iterable of tuples) --------------------------

    def test_object_style_bindings(self):
        bindings = [("text", BindingValue("t1")), ("label", BindingValue("t2"))]
        widget = Widget(id="btn1", bindings=bindings)
        rows = audit_bindings([widget], {"t1", "t2"})
        ready_rows = [r for r in rows if r.status == "ready"]
        self.assertEqual(len(ready_rows), 2)

    # -- deterministic sort order --------------------------------------------

    def test_deterministic_sort(self):
        w1 = Widget(id="btn2", bindings={"text": BindingValue("tag_b")})
        w2 = Widget(id="btn1", bindings={"text": BindingValue("tag_a")})
        rows = audit_bindings([w1, w2], {"tag_a", "tag_b"})
        tags = [r.tag for r in rows]
        self.assertEqual(tags, ["tag_a", "tag_b"])

    # -- no widgets ----------------------------------------------------------

    def test_no_widgets(self):
        rows = audit_bindings([], {"t1"})
        unused = [r for r in rows if r.tag == "t1"]
        self.assertEqual(len(unused), 1)
        self.assertEqual(unused[0].status, "info")

    # -- multiple widgets, mix of statuses -----------------------------------

    def test_mixed_statuses(self):
        w1 = Widget(id="btn1", bindings={"text": BindingValue("known")})
        w2 = Widget(id="btn2", bindings={"text": BindingValue("unknown")})
        w3 = Widget(id="btn3", bindings={"text": None})
        rows = audit_bindings([w1, w2, w3], {"known"})
        statuses = {r.status for r in rows}
        self.assertIn("ready", statuses)
        self.assertIn("warning", statuses)
        self.assertIn("error", statuses)


if __name__ == "__main__":
    unittest.main()