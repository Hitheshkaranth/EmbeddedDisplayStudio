"""CONTRACT 13.3 alarm options on a binding. FROZEN API (wave 1, W3).

`DesignerBinding.alarm` holds them; `DesignerProject.alarms()` merges
`manifest_fields(binding.alarm)` into the tag's manifest entry, and
`validate()` reports `validate_alarm_options`.
"""
from __future__ import annotations

import math

from .project import ValidationIssue

ALARM_KEYS = ("priority", "latch", "delay_ms", "deadband", "message")


def validate_alarm_options(options: dict, path: str) -> list:
    """Issues (designer.model.ValidationIssue at `path`). Messages, exactly:

    unknown key                 "unknown alarm option {key!r}"
    priority not int 1..4       "priority must be 1..4"
    latch not bool              "latch must be true or false"
    delay_ms not int 0..600000  "delay_ms must be 0..600000"
    deadband not a number >= 0  "deadband must be a number >= 0"
    message not a str           "message must be text"
    (bools are not numbers.)"""
    issues = []

    def is_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def is_number(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))

    for key in options:
        if key not in ALARM_KEYS:
            issues.append(ValidationIssue(path, f"unknown alarm option {key!r}"))
            continue

        value = options[key]
        if key == "priority":
            if not is_int(value) or not (1 <= value <= 4):
                issues.append(ValidationIssue(path, "priority must be 1..4"))
        elif key == "latch":
            if not isinstance(value, bool):
                issues.append(ValidationIssue(path, "latch must be true or false"))
        elif key == "delay_ms":
            if not is_int(value) or not (0 <= value <= 600000):
                issues.append(ValidationIssue(path, "delay_ms must be 0..600000"))
        elif key == "deadband":
            if not is_number(value) or value < 0:
                issues.append(ValidationIssue(path, "deadband must be a number >= 0"))
        elif key == "message":
            if not isinstance(value, str):
                issues.append(ValidationIssue(path, "message must be text"))

    return issues


def manifest_fields(options: dict) -> dict:
    """The valid options as manifest keys, in ALARM_KEYS order, dropping any
    invalid or unknown one and any at its default (latch False, delay_ms 0,
    deadband 0, message ""); priority is always written when valid."""
    result = {}
    if options.get("priority") is not None:
        priority = options["priority"]
        if isinstance(priority, int) and not isinstance(priority, bool) and 1 <= priority <= 4:
            result["priority"] = priority
    for key in ("latch", "delay_ms", "deadband", "message"):
        if key not in options:
            continue
        value = options[key]
        if key == "latch":
            if not isinstance(value, bool):
                continue
            if value:
                result["latch"] = True
        elif key == "delay_ms":
            if (not isinstance(value, int) or isinstance(value, bool)
                    or not (0 <= value <= 600000)):
                continue
            if value != 0:
                result["delay_ms"] = value
        elif key == "deadband":
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or value < 0):
                continue
            if value != 0:
                result["deadband"] = value
        elif key == "message":
            if not isinstance(value, str) or value == "":
                continue
            result["message"] = value
    return result
