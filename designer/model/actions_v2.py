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
    raise NotImplementedError


def action_tags(action) -> set:
    """Tags a 13.1 action writes or names: toggle / increment / decrement
    always their `tag`; ack / shelve their `tag` unless it is "" or "*";
    back none; write / pulse / navigate none here (the project counts those).
    """
    return set()   # W1


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
    return []   # W1
