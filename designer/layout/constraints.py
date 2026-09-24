"""designer/layout/constraints.py -- what each widget type needs to look right.

A cluster gauge is a dial: square, and useless below ~140 px. A tape is a
tall strip. A button has a minimum touch height. The registry knows each
type's design size (`default_width` / `default_height`); these rules turn
that into limits the layout engine honours, so nothing is stretched into
the 864x100 fuel gauge the baseline produced.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Types whose face is a dial or a circle: always square.
SQUARE_TYPES = ("ShClusterGauge", "ShGauge", "ShCompass", "ShAttitude", "ShTurnCoordinator",
                "ShFlightDirector", "ShAnalogDisplay", "ShStatDot", "ShIconTile", "ShTelltale")
# Minimum height of anything a finger operates.
TOUCH_MIN_HEIGHT = 40

# The instrument categories: a face drawn to a fixed design keeps its
# proportions to within 15 %.
FACE_CATEGORIES = ("Automotive", "Avionics", "Industrial")
# Categories that are a box for other things and have no proportion of their own.
FREE_CATEGORIES = ("Basic", "Containers", "Navigation")
# Tiles and cards are laid-out boxes with a little content: they take a third
# more or less of their design proportion without looking wrong.
TILE_TYPES = ("ShValueTile", "ShIconTile", "ShCard", "ShTripInfo", "ShDataField",
              "ShAlert", "ShAnnunciator", "ShAlarmTable", "ShTrendChart")
TILE_TOLERANCE = 0.35
FACE_TOLERANCE = 0.15
# Chrome: it states or takes a value and stops reading well when blown up.
STATUS_TYPES = ("ShStatDot", "ShTelltale", "ShAnnunciator", "ShAlert", "ShProgress",
                "ShButton", "ShToggle", "ShCheckbox", "ShSelect", "ShInput", "ShNumInput",
                "ShSlider", "ShGearIndicator", "ShDriveMode", "ShIconTile")
# Properties that mean the widget says what it is without help.
LABEL_PROPERTIES = ("label", "title", "text", "caption")
# The floor below which no face is readable at all.
ABSOLUTE_MINIMUM = 24
DESIGN_FRACTION = 0.6


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


def _floor(design: int) -> int:
    return max(ABSOLUTE_MINIMUM, int(math.floor(design * DESIGN_FRACTION + 0.5)))


def rule_for(registry, widget_type: str) -> WidgetRule:
    """The rule for a type, derived from the registry's design size.

    An unknown type gets a permissive rule (min 24x24, no aspect, growable).
    """
    widget_type = str(widget_type or "")
    definition = registry.get(widget_type) if registry is not None else None
    if definition is None:
        return WidgetRule(type=widget_type, min_width=ABSOLUTE_MINIMUM,
                          min_height=ABSOLUTE_MINIMUM, aspect=None, tolerance=0.0,
                          square=False, growable=True)

    design_width = max(1, int(definition.default_width))
    design_height = max(1, int(definition.default_height))
    min_width = _floor(design_width)
    min_height = _floor(design_height)
    if definition.action_signals:
        # A finger, not a mouse: the panel is a touch screen.
        min_height = max(min_height, TOUCH_MIN_HEIGHT)

    square = widget_type in SQUARE_TYPES or design_width == design_height
    if square:
        side = max(min_width, min_height)
        min_width = min_height = side
        aspect, tolerance = 1.0, 0.0
    elif definition.category in FREE_CATEGORIES:
        aspect, tolerance = None, 0.0
    else:
        aspect = design_width / design_height
        tolerance = TILE_TOLERANCE if widget_type in TILE_TYPES else FACE_TOLERANCE
        if definition.category not in FACE_CATEGORIES:
            tolerance = TILE_TOLERANCE

    growable = not (definition.category == "Basic" or widget_type in STATUS_TYPES)
    return WidgetRule(type=widget_type, min_width=min_width, min_height=min_height,
                      aspect=aspect, tolerance=tolerance, square=square, growable=growable)


def fit_size(rule: WidgetRule, width: float, height: float) -> tuple[int, int]:
    """The nearest size to (width, height) the rule allows.

    Grows to the minimums, then corrects the aspect when it is outside the
    tolerance by shrinking the longer side (never growing past the requested
    box), keeping the area as close to the request as the rule permits.
    """
    fitted_width = max(1, int(math.floor(float(width) + 0.5)))
    fitted_height = max(1, int(math.floor(float(height) + 0.5)))
    fitted_width = max(fitted_width, int(rule.min_width))
    fitted_height = max(fitted_height, int(rule.min_height))

    if rule.square:
        side = max(min(fitted_width, fitted_height), int(rule.min_width), int(rule.min_height))
        return side, side

    if rule.aspect:
        ratio = fitted_width / fitted_height
        widest = rule.aspect * (1.0 + rule.tolerance)
        narrowest = rule.aspect * max(0.0, 1.0 - rule.tolerance)
        if ratio > widest:
            # Too wide: take the width in, never push the height out.
            fitted_width = max(int(rule.min_width), int(math.floor(fitted_height * widest)))
        elif narrowest > 0.0 and ratio < narrowest:
            fitted_height = max(int(rule.min_height), int(math.floor(fitted_width / narrowest)))
    return max(1, fitted_width), max(1, fitted_height)


def wants_caption(registry, widget_type: str) -> bool:
    """True when the type shows no label of its own and reads better under a
    caption (the style pass adds one from the widget's id or binding tag)."""
    definition = registry.get(str(widget_type or "")) if registry is not None else None
    if definition is None:
        return False
    if definition.container or definition.category in ("Basic", "Containers", "Navigation"):
        return False
    return not any(name in definition.properties for name in LABEL_PROPERTIES)
