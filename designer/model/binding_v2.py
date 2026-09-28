"""CONTRACT 13.2 binding options in the Designer model. FROZEN API (wave 1, W2).

`DesignerProject.validate()` calls `validate_binding` for every binding;
`required_tags()` adds `binding_tags`.
"""
from __future__ import annotations

from designer.model.project import ValidationIssue
from designer.model.expr import compile_expr, ExprError

_COMPARATORS = (">", ">=", "<", "<=", "==", "!=")


def binding_tags(binding) -> set:
    """Tags the binding reads: its `tag` (when set) plus every tag its `expr`
    names (an expression that does not compile contributes none)."""
    tags = set()
    if getattr(binding, "tag", None):
        tags.add(binding.tag)
    expr_text = getattr(binding, "expr", None)
    if expr_text:
        try:
            tags.update(compile_expr(expr_text).tags)
        except ExprError:
            pass
    return tags


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
    issues = []

    decimals = getattr(binding, "decimals", -1)
    if (not isinstance(decimals, int) or isinstance(decimals, bool)
            or decimals < -1 or decimals > 6):
        issues.append(ValidationIssue(path, "decimals must be -1..6"))

    expr_text = getattr(binding, "expr", None)
    if expr_text:
        try:
            compile_expr(expr_text)
        except ExprError as err:
            issues.append(ValidationIssue(path, "expression: %s" % err))

    rules = getattr(binding, "rules", None)
    if isinstance(rules, list):
        for i, rule in enumerate(rules):
            valid = (isinstance(rule, dict)
                     and "if" in rule and "prop" in rule and "value" in rule)
            if not valid:
                issues.append(ValidationIssue(path,
                    "rule %d: needs if, prop and value" % i))
                continue
            cond = rule["if"]
            if not isinstance(cond, str) or not _is_condition(cond):
                issues.append(ValidationIssue(path,
                    "rule %d: condition %r is not '<op> <number>'" % (i, cond)))
            prop_name = rule["prop"]
            if (not isinstance(prop_name, str)
                    or definition is None
                    or prop_name not in definition.properties):
                if definition is not None and (
                        not isinstance(prop_name, str)
                        or prop_name not in definition.properties):
                    issues.append(ValidationIssue(path,
                        "rule %d: %s has no property %r" % (i, definition.type, prop_name)))
            if isinstance(prop_name, str) and prop_name == prop:
                issues.append(ValidationIssue(path,
                    "rule %d: property %r is bound" % (i, prop_name)))
            value = rule["value"]
            if (not isinstance(value, (str, int, float, bool))
                    or value is None):
                issues.append(ValidationIssue(path,
                    "rule %d: value must be a scalar" % i))

    return issues


def _is_condition(text) -> bool:
    parts = text.split()
    if len(parts) != 2:
        return False
    op, number = parts
    return (op in _COMPARATORS and _is_number(number))


def _is_number(text) -> bool:
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False