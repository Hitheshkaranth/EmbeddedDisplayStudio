"""CONTRACT 13.5 screen idle settings. FROZEN API (wave 1, W5)."""
from __future__ import annotations

IDLE_KEYS = ("dimAfterS", "dimPercent", "offAfterS")


def validate_idle(idle: dict, path: str) -> list:
    """Issues (designer.model.ValidationIssue at `path`). Messages, exactly:
    unknown key                       "unknown idle setting {key!r}"
    dimAfterS / offAfterS not int >= 0   "{key} must be a whole number of seconds >= 0"
    dimPercent not int 10..100        "dimPercent must be 10..100"
    offAfterS set (> 0) and not greater than a set dimAfterS
                                      "offAfterS must be later than dimAfterS"
    (bools are not numbers.)"""
    return []   # W5


def normalise_idle(idle: dict) -> dict:
    """The settings to save: known keys only, zeros and the default
    dimPercent (30) dropped; {} when nothing is left."""
    return dict(idle or {})   # W5
