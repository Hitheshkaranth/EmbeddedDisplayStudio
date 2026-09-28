"""CONTRACT 13.2 binding options in the Designer model. FROZEN API (wave 1, W2).

`DesignerProject.validate()` calls `validate_binding` for every binding;
`required_tags()` adds `binding_tags`.
"""
from __future__ import annotations


def binding_tags(binding) -> set:
    """Tags the binding reads: its `tag` (when set) plus every tag its `expr`
    names (an expression that does not compile contributes none)."""
    return set()   # W2


def validate_binding(binding, prop: str, widget, definition, path: str) -> list:
    """Issues (designer.model.ValidationIssue at `path`) for the 13.2 fields
    only -- tag / thresholds are checked by the project. `definition` is the
    registry's WidgetDefinition or None (then property checks are skipped).
    Messages, exactly:

    decimals not in -1..6                 "decimals must be -1..6"
    expr that does not compile            "expression: {reason}"   (ExprError text)
    a rule that is not an object with "if", "prop", "value"
                                          "rule {i}: needs if, prop and value"
    a rule whose "if" is not '<op> <number>'
                                          "rule {i}: condition {text!r} is not '<op> <number>'"
    a rule prop the widget type does not have (definition given)
                                          "rule {i}: {type} has no property {prop!r}"
    a rule prop that is itself bound on this widget
                                          "rule {i}: property {prop!r} is bound"
    a rule value that is not a JSON scalar (str, number, bool, None)
                                          "rule {i}: value must be a scalar"
    `i` counts from 0.
    """
    return []   # W2
