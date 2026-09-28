"""CONTRACT 13.3 alarm options on a binding. FROZEN API (wave 1, W3).

`DesignerBinding.alarm` holds them; `DesignerProject.alarms()` merges
`manifest_fields(binding.alarm)` into the tag's manifest entry, and
`validate()` reports `validate_alarm_options`.
"""
from __future__ import annotations

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
    return []   # W3


def manifest_fields(options: dict) -> dict:
    """The valid options as manifest keys, in ALARM_KEYS order, dropping any
    invalid or unknown one and any at its default (latch False, delay_ms 0,
    deadband 0, message ""); priority is always written when valid."""
    return {}   # W3
