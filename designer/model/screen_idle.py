"""CONTRACT 13.5 screen idle settings. FROZEN API (wave 1, W5)."""
from __future__ import annotations

from .project import ValidationIssue

IDLE_KEYS = ("dimAfterS", "dimPercent", "offAfterS")

DIM_PCT_MIN = 10
DIM_PCT_MAX = 100


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_idle(idle: dict, path: str) -> list:
    """Issues (designer.model.ValidationIssue at `path`). Messages, exactly:
    unknown key                       "unknown idle setting {key!r}"
    dimAfterS / offAfterS not int >= 0   "{key} must be a whole number of seconds >= 0"
    dimPercent not int 10..100        "dimPercent must be 10..100"
    offAfterS set (> 0) and not greater than a set dimAfterS
                                      "offAfterS must be later than dimAfterS"
    (bools are not numbers.)"""
    issues: list[ValidationIssue] = []
    for key in idle:
        if key not in IDLE_KEYS:
            issues.append(ValidationIssue(path, f"unknown idle setting {key!r}"))

    for key in ("dimAfterS", "offAfterS"):
        if key in idle:
            v = idle[key]
            if not (_is_int(v) and v >= 0):
                issues.append(ValidationIssue(path, f"{key} must be a whole number of seconds >= 0"))

    if "dimPercent" in idle:
        v = idle["dimPercent"]
        if not (_is_int(v) and DIM_PCT_MIN <= v <= DIM_PCT_MAX):
            issues.append(ValidationIssue(path, "dimPercent must be 10..100"))

    dim = idle.get("dimAfterS")
    off = idle.get("offAfterS")
    if _is_int(off) and off > 0 and _is_int(dim) and dim > 0 and off <= dim:
        issues.append(ValidationIssue(path, "offAfterS must be later than dimAfterS"))
    return issues


def normalise_idle(idle: dict) -> dict:
    """The settings to save: known keys only, zeros and the default
    dimPercent (30) dropped; {} when nothing is left."""
    out: dict = {}
    for key in IDLE_KEYS:
        if key not in idle:
            continue
        v = idle[key]
        if key == "dimPercent":
            if v == 30:
                continue
        else:
            if v == 0:
                continue
        out[key] = v
    return out
