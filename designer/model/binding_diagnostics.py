"""
designer/model/binding_diagnostics.py
Layer: Model (M3)
Immutable diagnostic row and audit_bindings() for binding tag validation.
"""

from collections import Counter
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiagnosticRow:
    """Immutable diagnostic row, sortable by (tag, widget_id, property)."""
    tag: str
    widget_id: str
    property: str
    status: str
    detail: str

    def __lt__(self, other):
        return (self.tag, self.widget_id, self.property) < (
            other.tag, other.widget_id, other.property
        )


def audit_bindings(widgets, declared_tags):
    """Audit bindings across widgets against a set of declared tags.

    Parameters
    ----------
    widgets : iterable of objects with ``.id`` and ``.bindings``
        Each widget's ``bindings`` may be a dict mapping property-name to
        a value object that has a ``.tag`` attribute, *or* a plain value
        (``None`` / empty string) that represents an empty binding.
    declared_tags : iterable of str
        The set of tag names that are considered valid / declared.

    Returns
    -------
    list[DiagnosticRow]
        Deterministic rows sorted by (tag, widget_id, property).
        Includes one row per unused declared tag (widget_id / property
        empty, status ``info``).
    """
    declared = set(declared_tags)
    rows = []

    # Track which (tag, property) pairs have been seen for duplicate detection
    seen_tag_property: dict[tuple[str, str], str] = {}

    for widget in widgets:
        widget_id = getattr(widget, "id", "")
        bindings = getattr(widget, "bindings", None)

        if bindings is None:
            continue

        # Normalise bindings to a list of (property_name, value) pairs
        if isinstance(bindings, dict):
            binding_items = bindings.items()
        else:
            # Treat as iterable of (property_name, value) tuples
            try:
                binding_items = list(bindings)
            except TypeError:
                continue

        for prop_name, value in binding_items:
            # --- empty binding ------------------------------------------------
            if value is None or (isinstance(value, str) and value == ""):
                rows.append(
                    DiagnosticRow(
                        tag="",
                        widget_id=widget_id,
                        property=prop_name,
                        status="error",
                        detail="Empty binding",
                    )
                )
                continue

            # --- extract tag attribute safely ---------------------------------
            tag = getattr(value, "tag", None)
            if tag is None or (isinstance(tag, str) and tag == ""):
                rows.append(
                    DiagnosticRow(
                        tag="",
                        widget_id=widget_id,
                        property=prop_name,
                        status="error",
                        detail="Empty binding",
                    )
                )
                continue

            tag = str(tag)

            # --- tag not declared ---------------------------------------------
            if tag not in declared:
                rows.append(
                    DiagnosticRow(
                        tag=tag,
                        widget_id=widget_id,
                        property=prop_name,
                        status="warning",
                        detail="Tag not declared",
                    )
                )
                continue

            # --- duplicate same tag/property use ------------------------------
            key = (tag, prop_name)
            if key in seen_tag_property:
                rows.append(
                    DiagnosticRow(
                        tag=tag,
                        widget_id=widget_id,
                        property=prop_name,
                        status="info",
                        detail="Duplicate tag/property use",
                    )
                )
            else:
                seen_tag_property[key] = widget_id
                rows.append(
                    DiagnosticRow(
                        tag=tag,
                        widget_id=widget_id,
                        property=prop_name,
                        status="ready",
                        detail="Tag bound successfully",
                    )
                )

    # --- unused declared tags -----------------------------------------------
    used_tags = {row.tag for row in rows if row.tag and row.status != "error"}
    for tag in sorted(declared):
        if tag not in used_tags:
            rows.append(
                DiagnosticRow(
                    tag=tag,
                    widget_id="",
                    property="",
                    status="info",
                    detail="Unused declared tag",
                )
            )

    # Deterministic sort by (tag, widget_id, property)
    rows.sort()
    return rows