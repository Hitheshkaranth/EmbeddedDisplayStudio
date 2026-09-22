"""designer/layout/arrange.py -- snap, fit, align and de-overlap a page.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W1.

The deterministic half of making a draft look designed: every widget sized
to what its type needs, every edge on the grid, peers sharing edges and
baselines, and no two widgets on top of each other. It never invents or
drops a widget -- ids and types are the model's business, geometry is this
module's.
"""
from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field

from .constraints import fit_size, rule_for
from .grid import grid_for, nearest_edge

# How many times the whole sequence may run before it is declared settled.
# It converges in two on every page we have; the bound is there so a
# pathological draft cannot spin.
MAX_PASSES = 6
# How many single overlaps one pass will fix before giving up on the rest.
MAX_FIXES = 96
# The magnet: an edge within this many pixels of a grid line is pulled onto
# it. A quarter of the gutter keeps a hand-composed page -- whose edges line
# up with each other rather than with our grid -- where its designer put it.
SNAP_DIVISOR = 4
# Two widgets are in the same row (or column) when they share this much of
# each other's height (or width).
PEER_BAND = 0.8
# A widget may lose this much of a side to clear an overlap before moving it
# becomes the better answer. Most overlaps a draft produces are slivers --
# the corner of a dial's bounding box over a button -- and taking the sliver
# off is a smaller change to a composition than relocating either widget.
TRIM_FRACTION = 0.25
_EDGES = ("left", "right", "top", "bottom", "cx", "cy")


@dataclass
class ArrangeReport:
    """What one arrange pass did.

    Attributes:
        moved: widgets whose position changed.
        resized: widgets whose size changed.
        overlaps_before, overlaps_after: overlapping pairs on the page.
        offscreen_before, offscreen_after: widgets crossing the margins.
        notes: one short line per decision worth explaining to a user.
    """
    moved: int = 0
    resized: int = 0
    overlaps_before: int = 0
    overlaps_after: int = 0
    offscreen_before: int = 0
    offscreen_after: int = 0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- geometry
def _rect(widget) -> tuple[int, int, int, int]:
    geometry = widget.geometry
    return (int(round(float(geometry.get("x", 0)))), int(round(float(geometry.get("y", 0)))),
            max(1, int(round(float(geometry.get("width", 1))))),
            max(1, int(round(float(geometry.get("height", 1))))))


def _place(widget, rect) -> bool:
    """Write a rectangle back as whole pixels; True when it really changed.

    Half a pixel is a blurred edge on a panel and a different number in every
    file the generators write, so geometry leaves here as integers even when
    the widget stayed where it was.
    """
    x, y, width, height = (int(value) for value in rect)
    width, height = max(1, width), max(1, height)
    changed = _rect(widget) != (x, y, width, height)
    widget.geometry.update({"x": x, "y": y, "width": width, "height": height})
    return changed


def _movable(widget) -> bool:
    return not bool(getattr(widget, "locked", False))


def _area_between(first, second) -> int:
    ax, ay, aw, ah = _rect(first)
    bx, by, bw, bh = _rect(second)
    width = min(ax + aw, bx + bw) - max(ax, bx)
    height = min(ay + ah, by + bh) - max(ay, by)
    return width * height if width > 0 and height > 0 else 0


def _hits(widget, others) -> bool:
    return any(_area_between(widget, other) > 0 for other in others)


def _overlap_load(widget, widgets) -> int:
    """How much of the page this one widget is sitting on top of."""
    return sum(_area_between(widget, other) for other in widgets if other is not widget)


def _walk(widgets):
    for widget in widgets:
        yield widget
        yield from _walk(widget.children)


def _overlap_pairs(widgets) -> list[tuple[str, str, int]]:
    found = []
    for index, first in enumerate(widgets):
        for second in widgets[index + 1:]:
            area = _area_between(first, second)
            if area > 0:
                found.append((str(first.id), str(second.id), int(area)))
    return found


def _outside(widget, grid) -> bool:
    x, y, width, height = _rect(widget)
    return (x < grid.margin or y < grid.margin
            or x + width > grid.content_right or y + height > grid.content_bottom)


# ------------------------------------------------------------------- steps
def _fit_all(widgets, registry) -> bool:
    """Step 1: every widget sized to what its type needs."""
    changed = False
    for widget in widgets:
        if not _movable(widget):
            continue
        x, y, width, height = _rect(widget)
        fitted = fit_size(rule_for(registry, widget.type), width, height)
        changed |= _place(widget, (x, y, fitted[0], fitted[1]))
    return changed


def _clamp_all(widgets, grid, registry) -> bool:
    """Step 5: everything inside the margins, shrinking rather than clipping."""
    changed = False
    for widget in widgets:
        if not _movable(widget):
            continue
        x, y, width, height = _rect(widget)
        if width > grid.content_width or height > grid.content_height:
            width, height = fit_size(rule_for(registry, widget.type),
                                     min(width, grid.content_width),
                                     min(height, grid.content_height))
        x = min(max(x, grid.margin), max(grid.margin, grid.content_right - width))
        y = min(max(y, grid.margin), max(grid.margin, grid.content_bottom - height))
        changed |= _place(widget, (x, y, width, height))
    return changed


def _snap_all(widgets, grid, registry) -> bool:
    """Step 2: pull every edge that is nearly on the grid onto it."""
    tolerance = max(1, grid.gutter // SNAP_DIVISOR)
    lefts, rights = grid.col_lefts(), grid.col_rights()
    tops, bottoms = grid.row_tops(), grid.row_bottoms()
    changed = False
    for widget in widgets:
        if not _movable(widget):
            continue
        was, load = _rect(widget), _overlap_load(widget, widgets)
        x, y, width, height = was
        rule = rule_for(registry, widget.type)
        x = _magnet(x, lefts, tolerance)
        y = _magnet(y, tops, tolerance)
        width = _magnet_size(rule, x, width, height, rights, tolerance, horizontal=True)
        height = _magnet_size(rule, y, height, width, bottoms, tolerance, horizontal=False)
        if _place(widget, (x, y, width, height)):
            if _overlap_load(widget, widgets) > load:
                # The grid is a guide, not a reason to sit on a neighbour.
                _place(widget, was)
            else:
                changed = True
    return changed


def _magnet(value: int, edges: list[int], tolerance: int) -> int:
    near = edges[nearest_edge(edges, value)]
    return near if abs(near - value) <= tolerance else value


def _magnet_size(rule, start, length, other, edges, tolerance, horizontal) -> int:
    """The length that puts the far edge on the grid, when it is that close
    and the type's rule accepts it unchanged."""
    far = edges[nearest_edge(edges, start + length)]
    if abs(far - (start + length)) > tolerance or far - start < 1:
        return length
    candidate = far - start
    fitted = fit_size(rule, candidate, other) if horizontal else fit_size(rule, other, candidate)
    return candidate if fitted == ((candidate, other) if horizontal else (other, candidate)) else length


def _value_of(widget, edge: str) -> int:
    x, y, width, height = _rect(widget)
    return {"left": x, "right": x + width, "top": y, "bottom": y + height,
            "cx": x + width // 2, "cy": y + height // 2}[edge]


def _clusters(values: list[int], tolerance: int) -> list[list[int]]:
    """Indices grouped into runs of nearly-equal values, no run wider than
    the tolerance itself -- three edges 15 px apart are a diagonal, not a
    line, and dragging them together would be a redesign."""
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    groups: list[list[int]] = []
    for index in order:
        if (groups and values[index] - values[groups[-1][-1]] <= tolerance
                and values[index] - values[groups[-1][0]] <= tolerance):
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def _target(values: list[int], grid_edges: set[int], tolerance: int) -> int | None:
    """Where a cluster of edges belongs: the value most of them are already
    on (a grid line breaking the tie), else a grid line one of them touches,
    else -- and only when they are a hair apart -- the lower median.

    Choosing a value the page already contains is what keeps arrange a fixed
    point, and refusing a cluster that has no such value is what keeps a
    hand-composed page, whose edges line up with each other rather than with
    our grid, unedited.
    """
    counts = Counter(values)
    most = max(counts.values())
    if most > 1:
        # The line most of them are already on, a grid line breaking the tie.
        winners = [value for value, count in counts.items() if count == most]
        on_grid = [value for value in winners if value in grid_edges]
        return min(on_grid or winners)
    on_grid = [value for value in counts if value in grid_edges]
    if on_grid:
        return min(on_grid)
    if max(values) - min(values) > max(1, tolerance // 2):
        return None
    return int(statistics.median_low(values))


def _align(widgets, grid, tolerance, registry) -> tuple[int, bool]:
    """Step 3a: near-equal edges pulled into exact alignment."""
    tolerance = grid.gutter if tolerance is None else max(0, int(tolerance))
    movers = [widget for widget in widgets if _movable(widget)]
    if tolerance <= 0 or len(movers) < 2:
        return 0, False
    lines = {"left": set(grid.col_lefts()), "right": set(grid.col_rights()),
             "top": set(grid.row_tops()), "bottom": set(grid.row_bottoms()),
             "cx": set(), "cy": set()}
    moved: set[int] = set()
    changed = False
    anchored = {"cx": set(), "cy": set()}
    for edge in _EDGES:
        items = [widget for widget in movers
                 if id(widget) not in anchored.get(edge, set())]
        values = [_value_of(widget, edge) for widget in items]
        for group in _clusters(values, tolerance):
            if len(group) < 2:
                continue
            target = _target([values[index] for index in group], lines[edge], tolerance)
            for index in group:
                widget = items[index]
                if edge in ("left", "right"):
                    anchored["cx"].add(id(widget))
                elif edge in ("top", "bottom"):
                    anchored["cy"].add(id(widget))
                if target is None or values[index] == target:
                    continue
                was, load = _rect(widget), _overlap_load(widget, widgets)
                if _pull(widget, edge, target, registry):
                    if _overlap_load(widget, widgets) > load:
                        # Tidiness never buys itself an overlap.
                        _place(widget, was)
                        continue
                    changed = True
                    if edge not in ("right", "bottom"):
                        moved.add(id(widget))
    return len(moved), changed


def _pull(widget, edge: str, target: int, registry) -> bool:
    """Move (or, for a far edge, resize) one widget onto an aligned value."""
    x, y, width, height = _rect(widget)
    rule = rule_for(registry, widget.type)
    if edge == "left":
        return _place(widget, (target, y, width, height))
    if edge == "top":
        return _place(widget, (x, target, width, height))
    if edge == "cx":
        return _place(widget, (target - width // 2, y, width, height))
    if edge == "cy":
        return _place(widget, (x, target - height // 2, width, height))
    if edge == "right":
        candidate = target - x
        if candidate < 1 or fit_size(rule, candidate, height) != (candidate, height):
            return False
        return _place(widget, (x, y, candidate, height))
    candidate = target - y
    if candidate < 1 or fit_size(rule, width, candidate) != (width, candidate):
        return False
    return _place(widget, (x, y, width, candidate))


def _bands(widgets, horizontal: bool) -> list[list]:
    """Widgets of one type grouped into the rows (or columns) they share."""
    bands: list[list] = []
    for widget in widgets:
        for band in bands:
            if all(_shares_band(widget, other, horizontal) for other in band):
                band.append(widget)
                break
        else:
            bands.append([widget])
    return bands


def _shares_band(first, second, horizontal: bool) -> bool:
    ax, ay, aw, ah = _rect(first)
    bx, by, bw, bh = _rect(second)
    if horizontal:
        start, end, first_len, second_len = max(ay, by), min(ay + ah, by + bh), ah, bh
    else:
        start, end, first_len, second_len = max(ax, bx), min(ax + aw, bx + bw), aw, bw
    shared = end - start
    return shared >= PEER_BAND * first_len and shared >= PEER_BAND * second_len


def _unify_peers(widgets, registry) -> bool:
    """Step 3b: equal-role peers in a row get one height, in a column one
    width. Only ever a resize, and never one that creates an overlap."""
    changed = False
    by_type: dict[str, list] = {}
    for widget in widgets:
        if _movable(widget):
            by_type.setdefault(str(widget.type), []).append(widget)
    for widget_type, peers in sorted(by_type.items()):
        if len(peers) < 2:
            continue
        rule = rule_for(registry, widget_type)
        for horizontal in (True, False):
            for band in _bands(peers, horizontal):
                if len(band) < 2:
                    continue
                sizes = [_rect(widget)[3 if horizontal else 2] for widget in band]
                target = int(statistics.median_low(sizes))
                for widget in band:
                    x, y, width, height = _rect(widget)
                    if (height if horizontal else width) == target:
                        continue
                    fitted = fit_size(rule, width, target) if horizontal else fit_size(rule, target, height)
                    if fitted != ((width, target) if horizontal else (target, height)):
                        continue
                    load = _overlap_load(widget, widgets)
                    if _place(widget, (x, y, fitted[0], fitted[1])):
                        if _overlap_load(widget, widgets) > load:
                            _place(widget, (x, y, width, height))
                        else:
                            changed = True
    return changed


def _free_spot(widget, others, grid) -> tuple[int, int] | None:
    """The nearest free position for this widget, preferring right, then
    below, then left, then above, and a grid line over anything else.

    The candidates are the grid's own lines plus a gutter past each
    neighbour's far edge, which is where the room left on a crowded page
    actually is.
    """
    x, y, width, height = _rect(widget)
    lefts = set(grid.col_lefts()) | {grid.margin}
    tops = set(grid.row_tops()) | {grid.margin}
    on_grid_x, on_grid_y = set(grid.col_lefts()), set(grid.row_tops())
    for other in others:
        other_x, other_y, other_width, other_height = _rect(other)
        lefts.add(other_x + other_width + grid.gutter)
        tops.add(other_y + other_height + grid.gutter)
    best = None
    for left in sorted(lefts):
        if left < grid.margin or left + width > grid.content_right:
            continue
        for top in sorted(tops):
            if top < grid.margin or top + height > grid.content_bottom:
                continue
            dx, dy = left - x, top - y
            if dx == 0 and dy == 0:
                continue
            if dx > 0 and abs(dx) >= abs(dy):
                direction = 0
            elif dy > 0 and abs(dy) > abs(dx):
                direction = 1
            elif dx < 0:
                direction = 2
            else:
                direction = 3
            off_grid = int(left not in on_grid_x) + int(top not in on_grid_y)
            key = (abs(dx) + abs(dy), off_grid, direction, left, top)
            if best is not None and key >= best[0]:
                continue
            _place(widget, (left, top, width, height))
            clear = not _hits(widget, others)
            _place(widget, (x, y, width, height))
            if clear:
                best = (key, left, top)
    return (best[1], best[2]) if best else None


def _nudge_clear(widget, other, others, grid) -> bool:
    """The smallest straight push off one neighbour, when the grid has no
    room to offer: better a widget five pixels to the right than a five
    pixel overlap nobody can explain."""
    x, y, width, height = _rect(widget)
    other_x, other_y, other_width, other_height = _rect(other)
    moves = ((other_x + other_width - x, 0), (0, other_y + other_height - y),
             (other_x - width - x, 0), (0, other_y - height - y))
    for index, (dx, dy) in sorted(enumerate(moves), key=lambda item: (abs(sum(item[1])), item[0])):
        left, top = x + dx, y + dy
        if (dx == 0 and dy == 0) or left < grid.margin or top < grid.margin:
            continue
        if left + width > grid.content_right or top + height > grid.content_bottom:
            continue
        _place(widget, (left, top, width, height))
        if not _hits(widget, others):
            return True
        _place(widget, (x, y, width, height))
    return False


def _shrink_one_cell(widget, grid, registry) -> bool:
    x, y, width, height = _rect(widget)
    step_x = grid.col_span(1) + grid.gutter
    step_y = grid.row_span(1) + grid.gutter
    fitted = fit_size(rule_for(registry, widget.type),
                      max(1, width - step_x), max(1, height - step_y))
    return _place(widget, (x, y, fitted[0], fitted[1]))


def _trim_apart(first, second, registry, notes, fraction=TRIM_FRACTION) -> bool:
    """Take the overlap off one of the two rather than move either.

    Only the far edges are candidates -- pulling a left or top edge in is a
    move as well as a resize -- and only when what comes off is `fraction` of
    that side at most and the type's rule accepts the result. The caller
    relaxes `fraction` when the alternative is leaving the overlap there.
    """
    candidates = []
    for widget, other in ((first, second), (second, first)):
        if not _movable(widget):
            continue
        x, y, width, height = _rect(widget)
        other_x, other_y = _rect(other)[0], _rect(other)[1]
        rule = rule_for(registry, widget.type)
        narrower = (other_x - x, height, width - (other_x - x))
        shorter = (width, other_y - y, height - (other_y - y))
        for new_width, new_height, cost in (narrower, shorter):
            side = width if new_height == height else height
            if new_width < 1 or new_height < 1 or cost <= 0 or cost > fraction * side:
                continue
            candidates.append((cost, str(widget.id), widget, fit_size(rule, new_width, new_height)))
    for cost, _name, widget, fitted in sorted(candidates, key=lambda item: item[:2]):
        x, y, width, height = _rect(widget)
        _place(widget, (x, y, fitted[0], fitted[1]))
        if _area_between(first, second) == 0:
            other = second if widget is first else first
            notes.append(f"trimmed {widget.id} back off {other.id}")
            return True
        _place(widget, (x, y, width, height))
    return False


def _resolve_overlaps(widgets, grid, registry, notes) -> bool:
    """Step 4: the worst pair is separated -- by taking a sliver off one of
    them where that is the smaller change, otherwise by moving the smaller
    widget to the nearest free grid position; if nothing is free it loses a
    cell and tries again."""
    changed = False
    stuck: set[tuple[str, str]] = set()
    for _ in range(MAX_FIXES):
        pairs = [pair for pair in _overlap_pairs(widgets) if (pair[0], pair[1]) not in stuck]
        if not pairs:
            break
        pairs.sort(key=lambda pair: (-pair[2], pair[0], pair[1]))
        first_id, second_id, _area = pairs[0]
        by_id = {str(widget.id): widget for widget in widgets}
        pair = [by_id[first_id], by_id[second_id]]
        if _trim_apart(pair[0], pair[1], registry, notes):
            changed = True
            continue
        pair.sort(key=lambda widget: (_rect(widget)[2] * _rect(widget)[3], str(widget.id)))
        mover = next((widget for widget in pair if _movable(widget)), None)
        if mover is None:
            stuck.add((first_id, second_id))
            continue
        others = [widget for widget in widgets if widget is not mover]
        spot = _free_spot(mover, others, grid)
        attempts = 0
        while spot is None and attempts < 3 and _shrink_one_cell(mover, grid, registry):
            # A cell narrower and a cell shorter, then look again.
            changed, attempts = True, attempts + 1
            spot = _free_spot(mover, others, grid)
        if spot is None:
            # Nowhere to go: something here is big enough to fill the screen,
            # so one of the two gives up as much of a side as it has to.
            if _trim_apart(pair[0], pair[1], registry, notes, fraction=1.0):
                changed = True
                continue
            other = pair[0] if pair[1] is mover else pair[1]
            if _nudge_clear(mover, other, others, grid):
                notes.append(f"nudged {mover.id} off {other.id}")
                changed = True
                continue
            stuck.add((first_id, second_id))
            notes.append(f"{mover.id} has nowhere clear to go on this screen")
            continue
        x, y, width, height = _rect(mover)
        _place(mover, (spot[0], spot[1], width, height))
        changed = True
        other = pair[0] if pair[1] is mover else pair[1]
        notes.append(f"moved {mover.id} clear of {other.id}")
    return changed


# -------------------------------------------------------------------- pass
def _arrange_level(widgets, grid, registry, notes) -> None:
    """One container's worth of widgets, laid out on one grid."""
    if not widgets:
        return
    _fit_all(widgets, registry)
    for _ in range(MAX_PASSES):
        changed = _clamp_all(widgets, grid, registry)
        changed |= _snap_all(widgets, grid, registry)
        changed |= _align(widgets, grid, None, registry)[1]
        changed |= _unify_peers(widgets, registry)
        changed |= _resolve_overlaps(widgets, grid, registry, notes)
        if not changed:
            break
    _clamp_all(widgets, grid, registry)
    for widget in widgets:
        if widget.children:
            # A child's geometry is relative to its parent, so the parent's
            # own box is the screen its children are composed on.
            _, _, width, height = _rect(widget)
            _arrange_level(list(widget.children), grid_for(width, height), registry, notes)


def arrange(project, page, registry, grid=None) -> ArrangeReport:
    """Lay `page` out on the grid, in place.

    Order of operations (each step keeps what the previous one achieved):
      1. fit every widget to its type's rule (constraints.fit_size);
      2. snap every rectangle to the grid;
      3. pull near-equal edges into alignment (within one gutter, left,
         right, top, bottom and centre lines) and give equal-role peers in
         a row the same height (and in a column the same width);
      4. resolve overlaps by pushing the smaller widget of each pair to the
         nearest free grid position, preferring the direction with room;
      5. keep everything inside the margins, shrinking rather than clipping.

    Containers are laid out with their children: a child's geometry is
    relative to its parent, so the parent is fitted first and children are
    arranged inside its content box.

    Args:
        project: the DesignerProject (screen size, theme).
        page: the DesignerPage to lay out; its widgets are mutated.
        registry: the widget registry.
        grid: the Grid to use, or None for grid_for(screen).

    Returns:
        ArrangeReport.
    """
    screen = getattr(project, "screen", None)
    if grid is None:
        grid = grid_for(getattr(screen, "width", 1280), getattr(screen, "height", 800))
    report = ArrangeReport()
    widgets = list(page.widgets)
    before = [(widget, _rect(widget)) for widget in _walk(widgets)]
    report.overlaps_before = len(_overlap_pairs(widgets))
    report.offscreen_before = sum(1 for widget in widgets if _outside(widget, grid))

    _arrange_level(widgets, grid, registry, report.notes)

    report.overlaps_after = len(_overlap_pairs(widgets))
    report.offscreen_after = sum(1 for widget in widgets if _outside(widget, grid))
    for widget, (x, y, width, height) in before:
        new_x, new_y, new_width, new_height = _rect(widget)
        if (new_x, new_y) != (x, y):
            report.moved += 1
        if (new_width, new_height) != (width, height):
            report.resized += 1
    if report.resized:
        report.notes.insert(0, f"{report.resized} widgets resized to their type's proportions")
    if report.moved:
        report.notes.insert(0, f"{report.moved} widgets moved onto the grid")
    return report


def overlaps(page) -> list[tuple[str, str, int]]:
    """Every overlapping pair of top-level widgets as (id_a, id_b, area)."""
    return _overlap_pairs(list(page.widgets))


def align_edges(page, grid, tolerance: int | None = None) -> int:
    """Pull edges that are nearly equal into exact alignment; returns how
    many widgets moved. `tolerance` defaults to the grid's gutter."""
    return _align(list(page.widgets), grid, tolerance, None)[0]
