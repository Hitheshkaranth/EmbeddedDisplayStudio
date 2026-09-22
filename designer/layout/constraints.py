"""designer/layout/constraints.py -- what each widget type needs to look right.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W1.

A cluster gauge is a dial: square, and useless below ~140 px. A tape is a
tall strip. A button has a minimum touch height. The registry knows each
type's design size (`default_width` / `default_height`); these rules turn
that into limits the layout engine honours, so nothing is stretched into
the 864x100 fuel gauge the baseline produced.
"""
from __future__ import annotations

from dataclasses import dataclass

# Types whose face is a dial or a circle: always square.
SQUARE_TYPES = ("ShClusterGauge", "ShGauge", "ShCompass", "ShAttitude", "ShTurnCoordinator",
                "ShFlightDirector", "ShAnalogDisplay", "ShStatDot", "ShIconTile", "ShTelltale")
# Minimum height of anything a finger operates.
TOUCH_MIN_HEIGHT = 40


@dataclass(frozen=True)
class WidgetRule:
    """How a type may be sized.

    Attributes:
        type: the widget type.
        min_width, min_height: below this the face stops being readable
            (0.6 x the registry's design size, floored at 24 px, and at
            TOUCH_MIN_HEIGHT for anything with signals).
        aspect: width / height the type wants, or None when free.
        tolerance: how far from `aspect` is acceptable (0.15 = 15 %).
        square: the face must be square (aspect 1, tolerance 0).
        growable: True when the type reads well made much larger (gauges,
            charts, tables); False for chrome that should stay near its
            design size (buttons, toggles, labels, status dots).
    """
    type: str
    min_width: int
    min_height: int
    aspect: float | None
    tolerance: float
    square: bool
    growable: bool


def rule_for(registry, widget_type: str) -> WidgetRule:
    """The rule for a type, derived from the registry's design size.

    An unknown type gets a permissive rule (min 24x24, no aspect, growable).
    """
    raise NotImplementedError


def fit_size(rule: WidgetRule, width: float, height: float) -> tuple[int, int]:
    """The nearest size to (width, height) the rule allows.

    Grows to the minimums, then corrects the aspect when it is outside the
    tolerance by shrinking the longer side (never growing past the requested
    box), keeping the area as close to the request as the rule permits.
    """
    raise NotImplementedError


def wants_caption(registry, widget_type: str) -> bool:
    """True when the type shows no label of its own and reads better under a
    caption (the style pass adds one from the widget's id or binding tag)."""
    raise NotImplementedError
