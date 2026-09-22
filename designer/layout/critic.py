"""designer/layout/critic.py -- how well composed a screen is, in numbers.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W2.

"Beautiful" is enforced, not requested: every candidate screen is measured,
and the pipeline keeps the best. The measures are deliberately blunt and
objective -- a designer would call them the difference between a draft and
a layout:

    overlap    widgets on top of each other (the baseline had a button
               inside a fuel gauge)
    margins    anything crossing the safe band, or off the screen
    alignment  how few distinct left/right/top/bottom edges the screen uses
    grid       how much of the geometry sits on the grid
    hierarchy  is there one clear hero, and a readable size ladder
    balance    ink spread across the screen, and whitespace symmetry
    proportion widgets at the aspect their type wants
    clipping   text or faces cut off (pixels; needs a render)
    contrast   readable foreground against what is behind it (pixels)

Geometry axes need no render. The pixel axes (clipping, contrast) are
scored only when an image is supplied, and are reported as None otherwise.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .constraints import rule_for
from .grid import grid_for

# The axes `Critique.scores` always carries, each 0..100.
AXES = ("overlap", "margins", "alignment", "grid", "hierarchy", "balance", "proportion",
        "clipping", "contrast")
# Weight of each axis in the overall score; pixel axes count only when scored.
WEIGHTS = {"overlap": 2.0, "margins": 1.5, "alignment": 1.5, "grid": 1.0, "hierarchy": 1.5,
           "balance": 1.0, "proportion": 1.5, "clipping": 1.5, "contrast": 1.0}

# --------------------------------------------------------------------------
# The numbers behind the judgement. Every one is a stated opinion about what
# a designer would accept, kept here so a reviewer can argue with it in one
# place instead of hunting through the axes.

# Half a widget hidden under another is the same as not having drawn it, so
# that is where the overlap axis bottoms out.
OVERLAP_FULL = 0.5
# An intersection shallower than this many gutters is a graze, not a burial,
# and counts in proportion to its depth.
OVERLAP_SLIVER_GUTTERS = 2.0
# Where an overlapping pair stops being a nit, and where it becomes a defect.
OVERLAP_WARNING = 0.02
OVERLAP_ERROR = 0.10
# A widget inside the safe margin costs this much of what leaving the screen
# altogether would cost.
MARGIN_GRAZE_WEIGHT = 0.35
# Edges cluster within half a gutter; a lone edge this many tolerances from
# its nearest neighbour is the near miss a designer sees first.
ALIGN_NEAR_MISS = 3.0
# Every widget sharing an edge with one other means clusters = widgets / 2.
ALIGN_IDEAL_RATIO = 0.5
# An edge is "on the grid" within this many pixels of a grid line.
GRID_TOLERANCE = 2.0
# The hero must be this much larger than the next widget to read as the hero.
HERO_RATIO = 1.6
# Areas within this ratio of each other read as the same size tier.
TIER_RATIO = 1.25
# More tiers than this and the ladder stops being readable -- "about five",
# so the cap is spent over twice that many before the term is gone.
TIER_MAX = 5
# Ink this far from the screen centre (as a fraction of the screen) is as
# unbalanced as the axis can say.
BALANCE_CENTRE_FULL = 0.25
# Aspect this far past what the rule allows is a total loss for that widget.
PROPORTION_FULL = 2.0
# Types whose face may run to the edge of its own rectangle.
BLEED_TYPES = ("Image", "Rectangle", "ShCard", "ShPanel", "ShSurface", "ShFrame")
# Ink covering this much of an edge is a border or a fill, not clipped content.
CLIP_FULL_EDGE = 0.75
# A run shorter than this is a face tangent to its own box -- the top of a
# dial, a dot, the tip of a needle -- not content the rectangle cut off.
CLIP_IGNORE = 0.15
# Contrast: what the axis calls perfect, and where it starts complaining.
CONTRAST_GOOD = 4.5
CONTRAST_WARNING = 3.0
CONTRAST_ERROR = 2.0

_SEVERITY_RANK = {"error": 0, "warning": 1, "nit": 2}


@dataclass(frozen=True)
class Issue:
    """One thing wrong with the screen.

    Attributes:
        kind: the axis it belongs to ("overlap", "proportion", ...).
        severity: "error" (a defect anyone would see), "warning", "nit".
        widget_id: the widget at fault, or "" for a whole-screen issue.
        detail: one line, specific and quantified, shown to the user.
    """
    kind: str
    severity: str
    widget_id: str
    detail: str


@dataclass(frozen=True)
class Critique:
    """The verdict on one screen.

    Attributes:
        score: 0..100, the weighted mean of the scored axes.
        scores: axis -> 0..100, or None for a pixel axis with no render.
        issues: every Issue found, worst first.
    """
    score: float
    scores: dict
    issues: tuple

    def summary(self) -> str:
        """One line: the score and the worst two issues."""
        head = f"score {self.score:.0f}/100"
        worst = [f"{issue.kind}: {issue.detail}" for issue in self.issues[:2]]
        return head + " -- " + ("; ".join(worst) if worst else "nothing to fix")

    def errors(self) -> tuple:
        """Only the issues of severity "error"."""
        return tuple(issue for issue in self.issues if issue.severity == "error")


# --------------------------------------------------------------------- utils

def _rect(widget):
    """(x, y, w, h) of a widget, as floats, whatever the file carried."""
    geometry = getattr(widget, "geometry", None) or {}

    def number(key):
        try:
            return float(geometry.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    return number("x"), number("y"), number("width"), number("height")


def _name(widget):
    return getattr(widget, "id", "") or getattr(widget, "type", "") or "?"


def _clamp(value, low=0.0, high=1.0):
    return low if value < low else (high if value > high else value)


def _blend(values):
    """A 60/40 mix of the worst case and the average: one bad widget is a
    defect, many bad widgets are a pattern, and both have to show."""
    if not values:
        return 0.0
    return 0.6 * max(values) + 0.4 * (sum(values) / len(values))


def _cluster(values, tolerance):
    """Sorted values grouped so no group spreads wider than `tolerance`."""
    groups = []
    for value in sorted(values):
        if groups and value - groups[-1][0] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return groups


def _design_size(registry, widget_type):
    definition = registry.get(widget_type) if registry is not None else None
    if definition is None:
        return None
    width = getattr(definition, "default_width", 0)
    height = getattr(definition, "default_height", 0)
    return (float(width), float(height)) if width and height else None


class _Collector:
    """Issues plus the penalty that decides their order."""

    def __init__(self):
        self._rows = []

    def add(self, kind, severity, widget_id, detail, penalty=0.0):
        self._rows.append((_SEVERITY_RANK.get(severity, 3), -float(penalty),
                           len(self._rows), Issue(kind, severity, widget_id, detail)))

    def sorted(self):
        return tuple(row[3] for row in sorted(self._rows, key=lambda row: row[:3]))


# -------------------------------------------------------------- geometry axes

def _overlap_axis(widgets, gutter, issues):
    """100 with no overlapping pair; otherwise the overlapping area as a
    fraction of the smaller widget, discounted when the intersection is a
    shallow graze (two bounding boxes touching) rather than a burial."""
    sliver = max(1.0, gutter * OVERLAP_SLIVER_GUTTERS)
    penalties = []
    for index, first in enumerate(widgets):
        ax, ay, aw, ah = _rect(first)
        for second in widgets[index + 1:]:
            bx, by, bw, bh = _rect(second)
            dx = min(ax + aw, bx + bw) - max(ax, bx)
            dy = min(ay + ah, by + bh) - max(ay, by)
            if dx <= 0 or dy <= 0:
                continue
            area = dx * dy
            smaller_area = min(max(aw * ah, 1.0), max(bw * bh, 1.0))
            fraction = _clamp(area / smaller_area)
            small = first if aw * ah <= bw * bh else second
            penalties.append(fraction * _clamp(min(dx, dy) / sliver))
            severity = ("error" if fraction >= OVERLAP_ERROR else
                        "warning" if fraction >= OVERLAP_WARNING else "nit")
            issues.add("overlap", severity, _name(small),
                       f"'{_name(first)}' and '{_name(second)}' overlap over {area:.0f} px "
                       f"({fraction * 100:.0f} % of '{_name(small)}', {dx:.0f}x{dy:.0f} px deep)",
                       fraction)
    if not penalties:
        return 100.0
    return 100.0 * (1.0 - _clamp(_blend(penalties) / OVERLAP_FULL))


def _margins_axis(widgets, screen_w, screen_h, margin, issues):
    """Off the screen is an error, inside the safe band a warning."""
    penalties = []
    for widget in widgets:
        x, y, w, h = _rect(widget)
        outside = max(0.0, -x, -y, (x + w) - screen_w, (y + h) - screen_h)
        graze = max(0.0, margin - x, margin - y,
                    (x + w) - (screen_w - margin), (y + h) - (screen_h - margin))
        if outside > 0:
            penalty = _clamp(outside / max(margin, 1.0))
            issues.add("margins", "error", _name(widget),
                       f"'{_name(widget)}' at {x:.0f},{y:.0f} {w:.0f}x{h:.0f} leaves the "
                       f"{screen_w:.0f}x{screen_h:.0f} screen by {outside:.0f} px", penalty)
        elif graze > 0:
            penalty = MARGIN_GRAZE_WEIGHT * _clamp(graze / max(margin, 1.0))
            issues.add("margins", "warning", _name(widget),
                       f"'{_name(widget)}' enters the {margin:.0f} px safe margin by "
                       f"{graze:.0f} px", penalty)
        else:
            penalty = 0.0
        penalties.append(penalty)
    return 100.0 * (1.0 - _clamp(_blend(penalties)))


def _edge_values(widgets, family):
    if family == "left":
        return [_rect(w)[0] for w in widgets]
    if family == "right":
        return [_rect(w)[0] + _rect(w)[2] for w in widgets]
    if family == "top":
        return [_rect(w)[1] for w in widgets]
    return [_rect(w)[1] + _rect(w)[3] for w in widgets]


def _alignment_axis(widgets, gutter, issues):
    """How few distinct edge values the screen uses. Every widget sharing an
    edge with another means half as many clusters as widgets, and that is
    100; a distinct edge per widget is 0."""
    count = len(widgets)
    if count < 2:
        return 100.0
    tolerance = max(gutter / 2.0, 1.0)
    totals = []
    scores = []
    for family in ("left", "right", "top", "bottom"):
        values = _edge_values(widgets, family)
        groups = _cluster(values, tolerance)
        totals.append(len(groups))
        scores.append(100.0 * _clamp((1.0 - len(groups) / count) / (1.0 - ALIGN_IDEAL_RATIO)))
        # 32 px and 40 px read as a mistake, not a decision: name the misses.
        for group in groups:
            if len(group) != 1:
                continue
            others = [other[0] for other in groups if other is not group]
            if not others:
                continue
            gap = min(abs(group[0] - value) for value in others)
            if gap > tolerance * ALIGN_NEAR_MISS:
                continue
            owner = next((w for index, w in enumerate(widgets)
                          if abs(values[index] - group[0]) < 1e-6), None)
            issues.add("alignment", "nit", _name(owner) if owner is not None else "",
                       f"{family} edge at {group[0]:.0f} px is {gap:.0f} px from the nearest "
                       f"other {family} edge -- share it or separate it", 0.3)
    score = sum(scores) / len(scores)
    if score < 70:
        issues.add("alignment", "warning", "",
                   f"{count} widgets use {totals[0]} left, {totals[1]} right, {totals[2]} top and "
                   f"{totals[3]} bottom edges; sharing them would need at most "
                   f"{(count + 1) // 2} of each", (100 - score) / 100.0)
    return score


def _grid_axis(widgets, grid, issues):
    """The fraction of edges sitting within GRID_TOLERANCE of a grid line."""
    try:
        xs = set()
        for column in range(int(grid.columns)):
            left = float(grid.col_x(column))
            xs.add(left)
            xs.add(left + float(grid.col_span(1)))
        ys = set()
        for row in range(int(grid.rows)):
            top = float(grid.row_y(row))
            ys.add(top)
            ys.add(top + float(grid.row_span(1)))
    except NotImplementedError:
        return 0.0
    if not xs or not ys:
        return 0.0
    hits = 0
    for widget in widgets:
        x, y, w, h = _rect(widget)
        for value, lines in ((x, xs), (x + w, xs), (y, ys), (y + h, ys)):
            if min(abs(value - line) for line in lines) <= GRID_TOLERANCE:
                hits += 1
    total = 4 * len(widgets)
    score = 100.0 * hits / total
    if score < 50:
        issues.add("grid", "warning", "",
                   f"{hits} of {total} edges sit on the {grid.columns}x{grid.rows} grid "
                   f"(margin {grid.margin} px, gutter {grid.gutter} px)",
                   (100 - score) / 100.0)
    return score


def _hierarchy_axis(widgets, issues):
    """One clear hero, and a size ladder with repetition in it. A page of one
    or two widgets has nothing to rank and is exempt."""
    count = len(widgets)
    if count <= 2:
        return 100.0
    areas = sorted((max(_rect(w)[2] * _rect(w)[3], 0.0) for w in widgets), reverse=True)
    biggest, runner_up = max(areas[0], 1.0), max(areas[1], 1.0)
    hero_ratio = biggest / runner_up
    hero = _clamp((hero_ratio - 1.0) / (HERO_RATIO - 1.0))
    if hero_ratio < HERO_RATIO:
        issues.add("hierarchy", "warning", "",
                   f"no clear hero: the largest widget is {biggest:.0f} px2, only {hero_ratio:.2f}x "
                   f"the next ({runner_up:.0f} px2) where {HERO_RATIO}x reads as one",
                   1.0 - hero)
    tiers = []
    for area in areas:
        if tiers and max(tiers[-1][-1], 1.0) / max(area, 1.0) <= TIER_RATIO:
            tiers[-1].append(area)
        else:
            tiers.append([area])
    # A screen of six widgets at five different sizes is noise, not a ladder:
    # a readable one repeats sizes, so tiers should be about half the widgets.
    spread = _clamp((1.0 - len(tiers) / count) / (1.0 - ALIGN_IDEAL_RATIO))
    cap = _clamp(1.0 - max(0, len(tiers) - TIER_MAX) / (2.0 * TIER_MAX))
    ladder = spread * cap
    if ladder < 0.9:
        issues.add("hierarchy", "nit", "",
                   f"{len(tiers)} distinct size tiers across {count} widgets -- a ladder reads at "
                   f"{TIER_MAX} or fewer, with siblings sharing a size", 1.0 - ladder)
    return 100.0 * (0.45 * hero + 0.55 * ladder)


def _balance_axis(widgets, screen_w, screen_h, issues):
    """Where the ink sits: its centre of mass against the screen centre, how
    evenly it fills the four quadrants, and whether a whole band is empty."""
    rects = [_rect(w) for w in widgets]
    total = sum(max(r[2] * r[3], 0.0) for r in rects)
    if total <= 0:
        return 0.0
    cx = sum((r[0] + r[2] / 2.0) * r[2] * r[3] for r in rects) / total
    cy = sum((r[1] + r[3] / 2.0) * r[2] * r[3] for r in rects) / total
    offset = math.hypot((cx - screen_w / 2.0) / max(screen_w, 1.0),
                        (cy - screen_h / 2.0) / max(screen_h, 1.0))
    centre_term = _clamp(offset / BALANCE_CENTRE_FULL)
    if centre_term > 0.4:
        issues.add("balance", "warning", "",
                   f"the ink centres on {cx:.0f},{cy:.0f}: {abs(cx - screen_w / 2):.0f} px across "
                   f"and {abs(cy - screen_h / 2):.0f} px down from the screen centre", centre_term)

    def covered(x0, y0, x1, y1):
        return sum(max(0.0, min(r[0] + r[2], x1) - max(r[0], x0))
                   * max(0.0, min(r[1] + r[3], y1) - max(r[1], y0)) for r in rects)

    half_w, half_h = screen_w / 2.0, screen_h / 2.0
    quadrants = [covered(0, 0, half_w, half_h), covered(half_w, 0, screen_w, half_h),
                 covered(0, half_h, half_w, screen_h), covered(half_w, half_h, screen_w, screen_h)]
    inside = sum(quadrants)
    if inside <= 0:
        return 0.0
    quadrant_term = _clamp(sum(abs(value / inside - 0.25) for value in quadrants) / 4.0 / 0.375)

    bands = []
    for index in range(3):
        bands.append(("row", index, covered(0, screen_h * index / 3.0,
                                            screen_w, screen_h * (index + 1) / 3.0)))
        bands.append(("col", index, covered(screen_w * index / 3.0, 0,
                                            screen_w * (index + 1) / 3.0, screen_h)))
    shares = [(kind, index, value * 3.0 / inside) for kind, index, value in bands]
    kind, index, thinnest = min(shares, key=lambda band: band[2])
    empty_term = _clamp(1.0 - thinnest)
    if empty_term > 0.4:
        where = ("top", "middle", "bottom") if kind == "row" else ("left", "centre", "right")
        issues.add("balance", "warning", "",
                   f"the {where[index]} third holds {thinnest / 3.0:.0%} of the ink where an even "
                   f"spread would give it 33 %", empty_term)
    return 100.0 * (1.0 - _clamp(0.35 * centre_term + 0.35 * quadrant_term + 0.30 * empty_term))


def _proportion_axis(widgets, registry, issues):
    """How far each widget's aspect is from what its type's rule allows."""
    penalties = []
    for widget in widgets:
        widget_type = getattr(widget, "type", "")
        try:
            rule = rule_for(registry, widget_type)
        except NotImplementedError:
            continue
        _, _, w, h = _rect(widget)
        if w <= 0 or h <= 0:
            continue
        min_w = float(getattr(rule, "min_width", 0) or 0)
        min_h = float(getattr(rule, "min_height", 0) or 0)
        if (min_w and w < min_w - 0.5) or (min_h and h < min_h - 0.5):
            issues.add("proportion", "nit", _name(widget),
                       f"'{widget_type}' at {w:.0f}x{h:.0f} is under the {min_w:.0f}x{min_h:.0f} "
                       f"its face needs to stay readable", 0.2)
        square = bool(getattr(rule, "square", False))
        target = 1.0 if square else getattr(rule, "aspect", None)
        if not target:
            continue
        tolerance = max(0.0 if square else float(getattr(rule, "tolerance", 0.15) or 0.0), 0.02)
        aspect = w / h
        ratio = max(aspect / target, target / aspect)
        allowed = 1.0 + tolerance
        excess = max(0.0, (ratio - allowed) / allowed)
        penalty = _clamp(excess / PROPORTION_FULL)
        penalties.append(penalty)
        if ratio <= allowed:
            continue
        wants = _design_size(registry, widget_type)
        wanted = f"about {wants[0]:.0f}x{wants[1]:.0f}" if wants else f"an aspect of {target:.2f}"
        issues.add("proportion", "error" if ratio > 1.0 + 2.0 * tolerance else "warning",
                   _name(widget),
                   f"'{widget_type}' at {w:.0f}x{h:.0f} is aspect {aspect:.2f} where its type "
                   f"wants {target:.2f} (+/-{tolerance:.0%}) -- {wanted}", penalty)
    if not penalties:
        return 100.0
    return 100.0 * (1.0 - _clamp(sum(penalties) / len(penalties)))


# ----------------------------------------------------------------- pixel axes

_LINEAR = tuple((channel / 12.92) if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                for channel in (value / 255.0 for value in range(256)))
# Ink is a pixel visibly lighter or darker than what its widget sits on:
# an absolute step on a dark panel, a relative one on a bright surface.
_INK_ABSOLUTE = 0.012
_INK_RELATIVE = 0.25


class _Pixels:
    """Random access to a QImage, in WCAG relative luminance."""

    def __init__(self, image, width, height):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage
        if image.width() != width or image.height() != height:
            image = image.scaled(int(width), int(height),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        image = image.convertToFormat(QImage.Format_RGB32)
        self.width = image.width()
        self.height = image.height()
        self._stride = image.bytesPerLine()
        self._buffer = bytes(image.constBits())

    def rgb(self, x, y):
        offset = int(y) * self._stride + int(x) * 4
        return self._buffer[offset + 2], self._buffer[offset + 1], self._buffer[offset]

    def luminance(self, x, y):
        offset = int(y) * self._stride + int(x) * 4
        return (0.2126 * _LINEAR[self._buffer[offset + 2]]
                + 0.7152 * _LINEAR[self._buffer[offset + 1]]
                + 0.0722 * _LINEAR[self._buffer[offset]])


def _samples(low, high, limit):
    """Up to `limit` evenly spaced integer coordinates in [low, high)."""
    span = int(high) - int(low)
    if span <= 0:
        return []
    if span <= limit:
        return list(range(int(low), int(high)))
    step = span / float(limit)
    return [int(low) + int(round(index * step)) for index in range(limit)]


def _dominant(pixels, points):
    """The luminance of the most common colour among `points`."""
    counts = {}
    for x, y in points:
        red, green, blue = pixels.rgb(x, y)
        key = (red >> 3, green >> 3, blue >> 3)
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    key = max(sorted(counts), key=lambda item: counts[item])
    return (0.2126 * _LINEAR[(key[0] << 3) + 4] + 0.7152 * _LINEAR[(key[1] << 3) + 4]
            + 0.0722 * _LINEAR[(key[2] << 3) + 4])


def _local_background(pixels, x0, y0, x1, y1):
    """The luminance of the rectangle's dominant colour -- what the widget's
    own content sits on, which is its surface when it has one and the page
    background when it does not."""
    return _dominant(pixels, [(x, y) for y in _samples(y0, y1, 48)
                              for x in _samples(x0, x1, 48)]) or 0.0


def _surround_background(pixels, x0, y0, x1, y1, reach=3):
    """The luminance of what the widget sits *on*: the dominant colour of the
    ring just outside its rectangle. Measuring a face against its own fill
    would make the page around a filled dot read as the dot's content."""
    points = []
    for offset in range(1, reach + 1):
        top, bottom = y0 - offset, y1 - 1 + offset
        left, right = x0 - offset, x1 - 1 + offset
        for x in _samples(x0, x1, 64):
            if 0 <= top < pixels.height:
                points.append((x, top))
            if 0 <= bottom < pixels.height:
                points.append((x, bottom))
        for y in _samples(y0, y1, 64):
            if 0 <= left < pixels.width:
                points.append((left, y))
            if 0 <= right < pixels.width:
                points.append((right, y))
    if not points:
        return _local_background(pixels, x0, y0, x1, y1)
    value = _dominant(pixels, points)
    return _local_background(pixels, x0, y0, x1, y1) if value is None else value


def _is_ink(value, background):
    step = abs(value - background)
    return step > _INK_ABSOLUTE and step / max(background, 0.005) > _INK_RELATIVE


def _clipping_axis(widgets, pixels, issues):
    """Ink running into a widget's own edge, where the type is not meant to
    bleed. A run covering the whole edge is a border or a fill and is left
    alone; a partial run is content the rectangle cut off."""
    penalties = []
    for index, widget in enumerate(widgets):
        if getattr(widget, "type", "") in BLEED_TYPES:
            continue
        x, y, w, h = _rect(widget)
        x0, y0 = int(max(0, round(x))), int(max(0, round(y)))
        x1 = int(min(pixels.width, round(x + w)))
        y1 = int(min(pixels.height, round(y + h)))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        # A neighbour lying over this rectangle paints ink that is not this
        # widget's face; its pixels cannot say anything about this widget.
        others = [_rect(other) for position, other in enumerate(widgets) if position != index]

        def mine(px, py, others=others):
            return not any(ox <= px < ox + ow and oy <= py < oy + oh
                           for ox, oy, ow, oh in others)

        background = _surround_background(pixels, x0, y0, x1, y1)
        worst, worst_edge, worst_coverage = 0.0, "", 0.0
        for edge, line in (("top", [(px, y0) for px in _samples(x0, x1, 160)]),
                           ("bottom", [(px, y1 - 1) for px in _samples(x0, x1, 160)]),
                           ("left", [(x0, py) for py in _samples(y0, y1, 160)]),
                           ("right", [(x1 - 1, py) for py in _samples(y0, y1, 160)])):
            points = [point for point in line if mine(*point)]
            if len(points) < max(4, 0.25 * len(line)):
                continue
            ink = sum(1 for px, py in points if _is_ink(pixels.luminance(px, py), background))
            coverage = ink / float(len(points))
            penalty = 0.0 if coverage >= CLIP_FULL_EDGE else _clamp(
                (coverage - CLIP_IGNORE) / (CLIP_FULL_EDGE - CLIP_IGNORE))
            if penalty > worst:
                worst, worst_edge, worst_coverage = penalty, edge, coverage
        penalties.append(worst)
        if worst > 0.25:
            issues.add("clipping", "error" if worst > 0.6 else "warning", _name(widget),
                       f"'{_name(widget)}' has ink on {worst_coverage:.0%} of its {worst_edge} "
                       f"edge at {w:.0f}x{h:.0f}: its face runs out of its rectangle", worst)
    if not penalties:
        return None
    return 100.0 * (1.0 - _clamp(_blend(penalties)))


def _contrast_axis(widgets, pixels, issues):
    """Per widget, the luminance ratio between its ink and what it sits on."""
    scores = []
    for widget in widgets:
        x, y, w, h = _rect(widget)
        x0, y0 = int(max(0, round(x))), int(max(0, round(y)))
        x1 = int(min(pixels.width, round(x + w)))
        y1 = int(min(pixels.height, round(y + h)))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        background = _local_background(pixels, x0, y0, x1, y1)
        ink = []
        for py in _samples(y0, y1, 96):
            for px in _samples(x0, x1, 96):
                value = pixels.luminance(px, py)
                if _is_ink(value, background):
                    ink.append(value)
        if len(ink) < 8:
            continue
        ink.sort()
        # The brightest ink that is not a stray pixel: what the eye reads.
        foreground = ink[int(0.85 * (len(ink) - 1))]
        top, bottom = max(foreground, background), min(foreground, background)
        ratio = (top + 0.05) / (bottom + 0.05)
        scores.append(100.0 * _clamp((ratio - 1.0) / (CONTRAST_GOOD - 1.0)))
        if ratio < CONTRAST_WARNING:
            issues.add("contrast", "error" if ratio < CONTRAST_ERROR else "warning", _name(widget),
                       f"'{_name(widget)}' draws its content at {ratio:.1f}:1 against its own "
                       f"background, under the {CONTRAST_WARNING:.0f}:1 a panel needs",
                       _clamp((CONTRAST_WARNING - ratio) / CONTRAST_WARNING))
    if not scores:
        return None
    return sum(scores) / len(scores)


# ------------------------------------------------------------------ the entry

def critique(project, page, registry, image=None, grid=None) -> Critique:
    """Measure the composition of `page`.

    Args:
        project: the DesignerProject (screen size, theme, background).
        page: the DesignerPage to measure.
        registry: the widget registry.
        image: a QImage of the page as hmi-ui rendered it, or None. When
            given, the pixel axes are scored too; the image is expected at
            the screen's size (any size is scaled to it).
        grid: the Grid to measure against, or None for grid_for(screen).

    Returns:
        Critique. A page with no widgets scores 0 with one "empty" issue.
    """
    screen = getattr(project, "screen", None)
    screen_w = float(getattr(screen, "width", 0) or 0) or 1280.0
    screen_h = float(getattr(screen, "height", 0) or 0) or 800.0
    widgets = list(getattr(page, "widgets", None) or [])
    scores = {axis: None for axis in AXES}
    if not widgets:
        for axis in AXES:
            if axis not in ("clipping", "contrast"):
                scores[axis] = 0.0
        return Critique(0.0, scores, (Issue(
            "empty", "error", "",
            f"the page holds no widgets: {screen_w:.0f}x{screen_h:.0f} px of nothing"),))

    if grid is None:
        grid = grid_for(int(screen_w), int(screen_h))
    gutter = float(getattr(grid, "gutter", 16) or 16)
    margin = float(getattr(grid, "margin", 24) or 24)

    issues = _Collector()
    scores["overlap"] = _overlap_axis(widgets, gutter, issues)
    scores["margins"] = _margins_axis(widgets, screen_w, screen_h, margin, issues)
    scores["alignment"] = _alignment_axis(widgets, gutter, issues)
    scores["grid"] = _grid_axis(widgets, grid, issues)
    scores["hierarchy"] = _hierarchy_axis(widgets, issues)
    scores["balance"] = _balance_axis(widgets, screen_w, screen_h, issues)
    scores["proportion"] = _proportion_axis(widgets, registry, issues)

    if image is not None and not image.isNull():
        pixels = _Pixels(image, int(screen_w), int(screen_h))
        scores["clipping"] = _clipping_axis(widgets, pixels, issues)
        scores["contrast"] = _contrast_axis(widgets, pixels, issues)

    weighted = sum(WEIGHTS[axis] * value for axis, value in scores.items() if value is not None)
    divisor = sum(WEIGHTS[axis] for axis, value in scores.items() if value is not None)
    return Critique(round(_clamp(weighted / divisor if divisor else 0.0, 0.0, 100.0), 2),
                    scores, issues.sorted())


def render_for_critique(project, page, renderer=None):
    """A QImage of the page from hmi-ui, or None when no renderer is
    available (designer.preview.NativeRenderer.render_page_sync)."""
    own = None
    try:
        if renderer is None:
            from designer.preview import NativeRenderer
            renderer = own = NativeRenderer()
        if not getattr(renderer, "available", True):
            return None
        theme = getattr(getattr(project, "screen", None), "theme", "dark") or "dark"
        image = renderer.render_page_sync(project, page, theme)
        return None if image is None or image.isNull() else image
    except Exception:
        return None
    finally:
        if own is not None:
            try:
                own.shutdown()
            except Exception:
                pass
