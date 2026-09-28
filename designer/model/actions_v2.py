"""CONTRACT 13.1 action kinds in the Designer model. FROZEN API (wave 1, W1).

`DesignerProject.validate()` checks write / pulse / navigate itself and hands
every other kind to `validate_action`; `required_tags()` adds `action_tags`.
"""
from __future__ import annotations

NEW_KINDS = ("back", "toggle", "increment", "decrement", "ack", "shelve")
SHELVE_MS_MIN, SHELVE_MS_MAX = 1, 86_400_000


def truthy(value) -> bool:
    """CONTRACT 13.1 truthy: bool as is; a number != 0; a string not in
    "", "false", "0"; None false; a list/tuple true when non-empty."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value not in ("", "false", "0")
    if isinstance(value, (list, tuple)):
        return bool(value)
    return bool(value)


def action_tags(action) -> set:
    """Tags a 13.1 action writes or names: toggle / increment / decrement
    always their `tag`; ack / shelve their `tag` unless it is "" or "*";
    back none; write / pulse / navigate none here (the project counts those).
    """
    kind = action.kind
    if kind in ("toggle", "increment", "decrement"):
        return {action.tag} if action.tag else set()
    if kind in ("ack", "shelve") and action.tag not in ("", "*"):
        return {action.tag}
    return set()


def validate_action(action, signal: str, path: str, page_ids) -> list:
    """Issues (designer.model.ValidationIssue, path = `path`) for one action
    whose kind is in NEW_KINDS. Messages, exactly:

    toggle/increment/decrement with a tag that is not a lowercase dotted tag
        "action tag {tag!r} is not a lowercase dotted tag name"
    increment/decrement with step <= 0 or not finite
        "step must be a positive number"
    increment/decrement with min > max (both set)
        "min must not be greater than max"
    ack/shelve with a tag that is neither "", "*" nor a dotted tag
        "action tag {tag!r} is not a lowercase dotted tag name"
    shelve with ms outside 1..86400000
        "shelve ms must be 1..86400000"
    ack/shelve with tag "" on any signal other than "alarmActivated"
        "ack and shelve need a tag unless the signal is alarmActivated"
    back: no issues.
    Nothing is reported for kinds outside NEW_KINDS.
    """
    from designer.model.project import ValidationIssue, TAG_RE

    kind = action.kind
    issues: list = []
    tag = action.tag

    def is_dotted(tag_text):
        return bool(tag_text) and bool(TAG_RE.match(tag_text))

    if kind in ("toggle", "increment", "decrement"):
        if not is_dotted(tag):
            issues.append(ValidationIssue(path,
                                          f"action tag {tag!r} is not a lowercase dotted tag name"))
        if kind in ("increment", "decrement"):
            step = action.step
            if isinstance(step, bool) or step <= 0 or step != step or step in (float("inf"), float("-inf")):
                issues.append(ValidationIssue(path, "step must be a positive number"))
            minv, maxv = action.min, action.max
            if minv is not None and maxv is not None and minv > maxv:
                issues.append(ValidationIssue(path, "min must not be greater than max"))
    elif kind in ("ack", "shelve"):
        if tag and tag != "*" and not is_dotted(tag):
            issues.append(ValidationIssue(path,
                                          f"action tag {tag!r} is not a lowercase dotted tag name"))
        if not tag and signal != "alarmActivated":
            issues.append(ValidationIssue(path,
                "ack and shelve need a tag unless the signal is alarmActivated"))
        if kind == "shelve":
            ms = int(action.ms)
            if ms < 1 or ms > 86_400_000:
                issues.append(ValidationIssue(path, "shelve ms must be 1..86400000"))

    return issues
