"""designer/layout/archetypes.py -- the compositions a screen can have.

FROZEN CONTRACT (AI beauty swarm, 2026-09-22). Owner: W3.

Composition is the part a language model is worst at and a designer is best
at, so it is not asked for: a handful of human-designed slot templates on
the 12-column grid carry it, and the model's widgets are placed into the
slots by role. Every archetype has one hero, a legible reading order and
balanced whitespace by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from . import constraints as _constraints
from . import grid as _grid

# What a widget is for, which decides the slot it can take.
ROLES = ("hero", "primary", "secondary", "control", "status", "caption", "table", "rail")

# Archetypes are drawn on a canonical 12 x 12 board: twelve columns, which is
# the grid's own COLUMNS, and twelve rows, which are mapped onto however many
# rows the real screen's grid offers. A canonical board keeps the five
# compositions readable as drawings and independent of the panel's height.
CANONICAL_ROWS = 12

# Faces and charts: the instruments a screen is built around. One of these,
# when it is much larger than its design size, is the page's hero.
FACE_TYPES = (
    "ShClusterGauge", "ShGauge", "ShAttitude", "ShCompass", "ShVSI", "ShTape",
    "ShEngineGauge", "ShEngineBar", "ShFuelQuantity", "ShAutoLevel", "ShVehicleStatus",
    "ShTurnCoordinator", "ShFlightDirector", "ShTrendChart", "ShAnalogDisplay",
)
# Lamps and annunciators: small, and read as a group rather than one at a time.
STATUS_TYPES = ("ShStatDot", "ShTelltale", "ShAlert", "ShAnnunciator", "ShProgress")
# Rows of records.
TABLE_TYPES = ("ShAlarmTable",)
# Tiles and readouts: a number with a caption, never the centre of a screen.
SECONDARY_TYPES = (
    "ShValueTile", "ShAutoReadout", "ShNumDisplay", "ShDataField", "ShTripInfo",
    "ShSegmentBar", "ShGearIndicator", "Image", "Rectangle", "ShInput",
)

# A hero has to be a face, has to be big in absolute terms, and has to have
# been given far more room than its design size -- otherwise it is one
# instrument among several and the page has no hero at all.
HERO_MIN_AREA = 100_000
HERO_MIN_GROWTH = 2.0

# Where a widget may spill when its own role has no slot left. The chain the
# brief asks for (secondary <-> primary, status <-> secondary, caption <->
# status) with the ends closed so nothing is ever dropped.
_ADJACENT = {
    "hero": ("primary", "secondary", "rail"),
    "primary": ("hero", "secondary", "rail", "table"),
    "secondary": ("primary", "rail", "status", "hero"),
    "control": ("secondary", "rail", "status"),
    "status": ("secondary", "caption", "rail"),
    "caption": ("status", "secondary", "rail"),
    "table": ("primary", "hero", "secondary"),
    "rail": ("secondary", "primary", "status"),
}

# No cell is ever split below this, whatever the widget count.
_ABSOLUTE_MIN_CELL = (24, 20)


@dataclass(frozen=True)
class Slot:
    """One place on the grid an archetype offers.

    Attributes:
        name: "hero", "left-rail", "footer-3", ... unique in the archetype.
        col, row, cspan, rspan: the block of grid cells it covers.
        role: which ROLES value belongs here.
        priority: lower is filled first when there are fewer widgets than slots.
    """
    name: str
    col: int
    row: int
    cspan: int
    rspan: int
    role: str
    priority: int = 0


@dataclass(frozen=True)
class Archetype:
    """A named composition.

    Attributes:
        id: "hero-centre", "thirds", "header-hero-rail", "card-grid", "split".
        name, description: shown to the user when a variant is offered.
        slots: the slots, in reading order.
        keywords: words in a brief that suggest this composition.
    """
    id: str
    name: str
    description: str
    slots: tuple
    keywords: tuple

    def slots_for(self, role: str) -> tuple:
        """Slots of this role, in priority order."""
        order = {slot.name: index for index, slot in enumerate(self.slots)}
        matching = [slot for slot in self.slots if slot.role == role]
        matching.sort(key=lambda slot: (slot.priority, order[slot.name]))
        return tuple(matching)


# -- the five compositions ------------------------------------------------
# Drawn on the canonical 12 x 12 board. Columns are the grid's own; rows are
# twelfths of the content height. Every board is checked by the gate: one
# hero, unique names, 6..14 slots, nothing past column 12.

_HERO_CENTRE = Archetype(
    id="hero-centre",
    name="Hero centre",
    description="One big instrument in the middle, a rail of readings down each "
                "side, a caption band above and the controls along the foot.",
    slots=(
        Slot("caption-band", 0, 0, 12, 1, "caption", 0),
        Slot("hero", 3, 1, 6, 8, "hero", 0),
        Slot("left-1", 0, 1, 3, 3, "primary", 1),
        Slot("right-1", 9, 1, 3, 3, "primary", 2),
        Slot("left-2", 0, 4, 3, 3, "primary", 3),
        Slot("right-2", 9, 4, 3, 3, "secondary", 4),
        Slot("left-3", 0, 7, 3, 2, "secondary", 5),
        Slot("right-3", 9, 7, 3, 2, "secondary", 6),
        Slot("foot-1", 0, 9, 3, 3, "status", 7),
        Slot("foot-2", 3, 9, 3, 3, "control", 8),
        Slot("foot-3", 6, 9, 3, 3, "control", 9),
        Slot("foot-4", 9, 9, 3, 3, "secondary", 10),
    ),
    keywords=("cluster", "gauge", "gauges", "instrument", "instruments", "dial",
              "tachometer", "rpm", "speed", "speedometer", "engine"),
)

_THIRDS = Archetype(
    id="thirds",
    name="Thirds",
    description="Three equal columns; the middle one runs taller and carries "
                "the hero, the outer two stack a reading over a readout.",
    slots=(
        Slot("caption-band", 0, 0, 12, 1, "caption", 0),
        Slot("hero", 4, 1, 4, 9, "hero", 0),
        Slot("left-top", 0, 1, 4, 1, "status", 5),
        Slot("right-top", 8, 1, 4, 1, "status", 6),
        Slot("left-1", 0, 2, 4, 4, "primary", 1),
        Slot("right-1", 8, 2, 4, 4, "primary", 2),
        Slot("left-2", 0, 6, 4, 4, "secondary", 3),
        Slot("right-2", 8, 6, 4, 4, "secondary", 4),
        Slot("foot-1", 0, 10, 4, 2, "control", 7),
        Slot("foot-2", 4, 10, 4, 2, "control", 8),
        Slot("foot-3", 8, 10, 4, 2, "secondary", 9),
    ),
    keywords=("thirds", "three", "compare", "comparison", "columns", "zones",
              "phases", "stages", "channels"),
)

_HEADER_HERO_RAIL = Archetype(
    id="header-hero-rail",
    name="Header, hero and rail",
    description="A title band, the hero filling two thirds of the screen and a "
                "rail of cards down the right, controls at the foot.",
    slots=(
        Slot("title", 0, 0, 8, 1, "caption", 0),
        Slot("header-status", 8, 0, 4, 1, "status", 4),
        Slot("hero", 0, 1, 8, 8, "hero", 0),
        Slot("rail-1", 8, 1, 4, 3, "primary", 1),
        Slot("rail-2", 8, 4, 4, 3, "secondary", 2),
        Slot("rail-3", 8, 7, 4, 2, "secondary", 3),
        Slot("rail-4", 8, 9, 4, 3, "rail", 6),
        Slot("foot-1", 0, 9, 4, 3, "control", 5),
        Slot("foot-2", 4, 9, 4, 3, "control", 7),
    ),
    keywords=("detail", "details", "header", "title", "rail", "sidebar",
              "monitor", "monitoring", "summary", "trend"),
)

_CARD_GRID = Archetype(
    id="card-grid",
    name="Card grid",
    description="A three by three grid of equal cards, the first two of the top "
                "row merged so the screen still opens on something.",
    slots=(
        Slot("title", 0, 0, 12, 1, "caption", 0),
        Slot("hero", 0, 1, 8, 4, "hero", 0),
        Slot("cell-3", 8, 1, 4, 4, "primary", 1),
        Slot("cell-4", 0, 5, 4, 4, "secondary", 2),
        Slot("cell-5", 4, 5, 4, 4, "secondary", 3),
        Slot("cell-6", 8, 5, 4, 4, "secondary", 4),
        Slot("cell-7", 0, 9, 4, 3, "status", 5),
        Slot("cell-8", 4, 9, 4, 3, "control", 6),
        Slot("cell-9", 8, 9, 4, 3, "control", 7),
    ),
    keywords=("menu", "tiles", "tile", "overview", "grid", "dashboard", "home",
              "launcher", "cards"),
)

_SPLIT = Archetype(
    id="split",
    name="Split",
    description="Two halves: the instruments and their controls on the left, a "
                "table or log running the full height on the right.",
    slots=(
        Slot("title", 0, 0, 12, 1, "caption", 0),
        Slot("hero", 0, 1, 6, 6, "hero", 0),
        Slot("table", 6, 1, 6, 8, "table", 1),
        Slot("left-1", 0, 7, 3, 3, "primary", 2),
        Slot("left-2", 3, 7, 3, 3, "secondary", 3),
        Slot("status-strip", 0, 10, 6, 2, "status", 4),
        Slot("foot-1", 6, 9, 3, 3, "control", 5),
        Slot("foot-2", 9, 9, 3, 3, "control", 6),
    ),
    keywords=("alarm", "alarms", "log", "logs", "table", "event", "events",
              "history", "journal", "list", "split"),
)

_CATALOGUE = (_HERO_CENTRE, _THIRDS, _HEADER_HERO_RAIL, _CARD_GRID, _SPLIT)


def archetypes() -> tuple:
    """Every archetype, in the order they are offered as variants.

    At least these five, each with one hero slot and 6-14 slots in total:
      hero-centre        one big instrument centred, rails either side,
                         a caption band at the top and controls at the foot
      thirds             three equal columns, hero in the middle column
      header-hero-rail   title band, hero left, a rail of cards on the right
      card-grid          a 2x3 or 3x3 grid of equal cards, no single hero
                         (hero slot spans two cells of the first row)
      split              two halves: instruments left, table/log right
    """
    return _CATALOGUE


_WORD_RE = re.compile(r"[a-z0-9]+")


def archetype_for(brief: str, widget_count: int, page=None) -> Archetype:
    """The archetype that suits this brief and this many widgets.

    Keyword match first ("cluster", "gauge" -> hero-centre; "alarm", "log",
    "table" -> split; "menu", "tiles", "overview" -> card-grid); otherwise by
    count: <= 4 hero-centre, <= 8 thirds, <= 12 header-hero-rail, else card-grid.
    """
    words = set(_WORD_RE.findall(str(brief or "").lower()))
    best, best_hits = None, 0
    for archetype in _CATALOGUE:
        # A brief that says "alarm overview with a log" names both a table and
        # a menu; the composition its words point at most often wins, and the
        # catalogue's own order settles a tie.
        hits = len(words & set(archetype.keywords))
        if hits > best_hits:
            best, best_hits = archetype, hits
    if best is not None:
        return best
    # A page of records wants the split whatever the brief called it.
    if page is not None and any(w.type in TABLE_TYPES for w in getattr(page, "widgets", ())):
        return _SPLIT
    count = int(widget_count or 0)
    if count <= 4:
        return _HERO_CENTRE
    if count <= 8:
        return _THIRDS
    if count <= 12:
        return _HEADER_HERO_RAIL
    return _CARD_GRID


def role_for(registry, widget) -> str:
    """What this widget is for, from its type and size.

    Faces and charts are "primary" ("hero" when they are the largest face on
    the page), tiles and readouts "secondary", anything with signals
    "control", dots/telltales/alerts "status", Text "caption", tables
    "table"; a widget the archetype has no room for takes "rail".
    """
    widget_type = getattr(widget, "type", str(widget))
    if widget_type in TABLE_TYPES:
        return "table"
    if widget_type in STATUS_TYPES:
        return "status"
    if widget_type == "Text":
        return "caption"
    definition = registry.get(widget_type) if registry is not None else None
    if definition is not None and definition.action_signals:
        return "control"
    if widget_type in FACE_TYPES:
        return "hero" if _is_hero_sized(definition, widget) else "primary"
    if widget_type in SECONDARY_TYPES:
        return "secondary"
    if definition is not None and definition.container:
        return "primary"
    return "secondary"


def _is_hero_sized(definition, widget) -> bool:
    """A face given hero treatment: big on the screen and far past its own
    design size. With only the widget in hand there is nothing else to
    compare it with, so apply_archetype settles ties -- see _page_roles."""
    geometry = getattr(widget, "geometry", {}) or {}
    area = float(geometry.get("width", 0) or 0) * float(geometry.get("height", 0) or 0)
    if area < HERO_MIN_AREA:
        return False
    if definition is None:
        return True
    design = float(definition.default_width * definition.default_height) or 1.0
    return area >= HERO_MIN_GROWTH * design


def _page_roles(registry, page, hero_box=None) -> dict:
    """The role of every widget on the page, with exactly one hero whenever
    the page has a face at all: role_for cannot see its neighbours.

    With a `hero_box` -- the size of the composition's hero slot -- the hero
    is the face that fills it best, which is both the designer's answer to
    "which of these is the screen about" and the only one that does not move
    on a second pass: how big a widget ends up is a fact about the slot it
    was given, not about where it started.
    """
    roles = {}
    for widget in page.widgets:
        roles[widget.id] = role_for(registry, widget)
    faces = [w for w in page.widgets if w.type in FACE_TYPES]
    if faces:
        for widget in faces:
            roles[widget.id] = "primary"
        if hero_box:
            key = lambda w: (-_fitted_area(registry, w, hero_box),  # noqa: E731
                             -_design_area(registry, w), w.id)
        else:
            key = lambda w: (-_area(w), w.id)  # noqa: E731
        roles[sorted(faces, key=key)[0].id] = "hero"
    return roles


def _area(widget) -> float:
    geometry = widget.geometry or {}
    return float(geometry.get("width", 0) or 0) * float(geometry.get("height", 0) or 0)


def _design_area(registry, widget) -> float:
    definition = registry.get(widget.type) if registry is not None else None
    if definition is None:
        return 0.0
    return float(definition.default_width * definition.default_height)


# -- placement ------------------------------------------------------------


class _Cell:
    """A slot resolved to pixels; splitting makes more of them."""

    __slots__ = ("name", "x", "y", "w", "h", "role", "priority", "order", "taken")

    def __init__(self, name, x, y, w, h, role, priority, order):
        self.name, self.x, self.y, self.w, self.h = name, x, y, w, h
        self.role, self.priority, self.order, self.taken = role, priority, order, False

    @property
    def area(self):
        return self.w * self.h


def _content_box(grid):
    margin = int(getattr(grid, "margin", 0) or 0)
    return (margin, margin, int(grid.width) - 2 * margin, int(grid.height) - 2 * margin)


def _slot_rect(grid, slot):
    """The pixel rectangle of a canonical slot on this grid."""
    rows = int(getattr(grid, "rows", 0) or 0)
    if rows >= CANONICAL_ROWS:
        # Rounded, not truncated: twelve canonical bands over fifteen real
        # rows should come out 1-1-1-2-1-1-... rather than dropping a whole
        # row on one band and giving the next two.
        top = _scale_row(slot.row, rows)
        bottom = _scale_row(slot.row + slot.rspan, rows)
        rect = grid.cell(slot.col, top, slot.cspan, max(1, bottom - top))
    else:
        rect = _canonical_rect(grid, slot)
    return _clamp_rect(grid, rect)


def _scale_row(row, rows):
    """A canonical row edge on a grid of `rows` rows, rounded half up. The
    edges stay strictly increasing because rows >= CANONICAL_ROWS."""
    return (2 * row * rows + CANONICAL_ROWS) // (2 * CANONICAL_ROWS)


def _canonical_rect(grid, slot):
    """Twelve rows of the content box, for a grid too short to map onto."""
    left, top, width, height = _content_box(grid)
    gutter = int(getattr(grid, "gutter", 0) or 0)
    columns = 12
    col_pitch = (width - (columns - 1) * gutter) / float(columns)
    row_pitch = (height - (CANONICAL_ROWS - 1) * gutter) / float(CANONICAL_ROWS)
    x = left + round(slot.col * (col_pitch + gutter))
    y = top + round(slot.row * (row_pitch + gutter))
    w = round(slot.cspan * col_pitch + (slot.cspan - 1) * gutter)
    h = round(slot.rspan * row_pitch + (slot.rspan - 1) * gutter)
    return (int(x), int(y), int(max(1, w)), int(max(1, h)))


def _clamp_rect(grid, rect):
    left, top, width, height = _content_box(grid)
    x, y, w, h = (int(round(value)) for value in rect)
    w = max(1, min(w, width))
    h = max(1, min(h, height))
    x = max(left, min(x, left + width - w))
    y = max(top, min(y, top + height - h))
    return (x, y, w, h)


def _split_cell(cell, gutter, min_size, order):
    """Two cells from one, side by side or stacked, or None when neither half
    would still hold what has to go in it."""
    min_w, min_h = min_size
    wide = cell.w >= cell.h
    for horizontal in (wide, not wide):
        if horizontal:
            half = (cell.w - gutter) // 2
            if half < min_w or cell.h < min_h:
                continue
            first = _Cell(cell.name + "-a", cell.x, cell.y, half, cell.h,
                          cell.role, cell.priority, order)
            second = _Cell(cell.name + "-b", cell.x + half + gutter, cell.y,
                           cell.w - half - gutter, cell.h, cell.role, cell.priority, order + 1)
        else:
            half = (cell.h - gutter) // 2
            if half < min_h or cell.w < min_w:
                continue
            first = _Cell(cell.name + "-a", cell.x, cell.y, cell.w, half,
                          cell.role, cell.priority, order)
            second = _Cell(cell.name + "-b", cell.x, cell.y + half + gutter,
                           cell.w, cell.h - half - gutter, cell.role, cell.priority, order + 1)
        if first.w > 0 and first.h > 0 and second.w > 0 and second.h > 0:
            return first, second
    return None


def _make_room(cells, needed, gutter, min_size, notes):
    """Split the lowest-priority cells in half until there are `needed`."""
    order = len(cells) * 10
    floor = min_size
    guard = 0
    while len(cells) < needed and guard < 512:
        guard += 1
        made = None
        for cell in sorted(cells, key=lambda c: (-c.priority, -c.area, c.order)):
            made = _split_cell(cell, gutter, floor, order)
            if made is not None:
                cells.remove(cell)
                cells.extend(made)
                notes.append(f"split the {cell.name} slot in two: more widgets than slots")
                order += 2
                break
        if made is None:
            if floor == _ABSOLUTE_MIN_CELL:
                break
            # Nothing splits at the types' minimum size any more. A widget is
            # never dropped, so the minimum gives way instead.
            notes.append("more widgets than the composition holds at their minimum "
                         "size: the last slots go below it")
            floor = _ABSOLUTE_MIN_CELL
    return cells


def _fitted_area(registry, widget, box):
    try:
        rule = _constraints.rule_for(registry, widget.type)
        width, height = _constraints.fit_size(rule, box[0], box[1])
    except NotImplementedError:  # pragma: no cover - until W1 lands
        return float(box[0]) * float(box[1])
    return float(width) * float(height)


def _minimum_cell(registry, widgets):
    """The smallest cell any of these widgets can still be read in."""
    min_w, min_h = 0, 0
    for widget in widgets:
        try:
            rule = _constraints.rule_for(registry, widget.type)
        except NotImplementedError:  # pragma: no cover - until W1 lands
            continue
        min_w = rule.min_width if not min_w else min(min_w, rule.min_width)
        min_h = rule.min_height if not min_h else min(min_h, rule.min_height)
    return (max(min_w, _ABSOLUTE_MIN_CELL[0]), max(min_h, _ABSOLUTE_MIN_CELL[1]))


def apply_archetype(project, page, archetype, registry, grid=None) -> list[str]:
    """Place every widget of `page` into `archetype`'s slots, in place.

    Widgets are ranked by role and by current area, and assigned to the
    slots of their role in priority order; a widget with no slot of its role
    left takes the next free slot of an adjacent role rather than being
    dropped. Each widget is then sized with constraints.fit_size inside its
    slot and centred in it. Containers keep their children.

    Returns:
        One note per placement decision worth explaining.
    """
    notes: list[str] = []
    widgets = list(page.widgets)
    if not widgets:
        return notes
    if grid is None:
        grid = _grid.grid_for(project.screen.width, project.screen.height)
    gutter = int(getattr(grid, "gutter", 8) or 8)

    cells = [_Cell(slot.name, *_slot_rect(grid, slot), slot.role, slot.priority, index)
             for index, slot in enumerate(archetype.slots)]
    hero_cells = [cell for cell in cells if cell.role == "hero"] or cells
    hero_box = max((cell.w, cell.h) for cell in hero_cells)
    roles = _page_roles(registry, page, hero_box)
    if len(cells) < len(widgets):
        cells = _make_room(cells, len(widgets), gutter,
                           _minimum_cell(registry, widgets), notes)

    by_role: dict[str, list] = {}
    for cell in cells:
        by_role.setdefault(cell.role, []).append(cell)
    for group in by_role.values():
        group.sort(key=lambda c: (c.priority, -c.area, c.order))
    biggest = max(cells, key=lambda c: (c.area, -c.order))

    def rank(widget):
        # Role first, then size -- but size measured against the largest slot
        # the role offers rather than against the widget's current geometry.
        # The draft's own area cannot be the key here: after one pass a
        # widget's area is a fact about the slot it was given, and two peers
        # that landed in differently shaped slots would swap places on the
        # next pass. Measuring the slot instead is what makes applying an
        # archetype twice change nothing the second time.
        group = by_role.get(roles[widget.id]) or [biggest]
        box = max((c.w, c.h) for c in group)
        return (ROLES.index(roles[widget.id]), -_fitted_area(registry, widget, box),
                -_design_area(registry, widget), widget.id)

    for widget in sorted(widgets, key=rank):
        role = roles[widget.id]
        cell = _take(by_role, role)
        if cell is None:
            for neighbour in _ADJACENT.get(role, ()):
                cell = _take(by_role, neighbour)
                if cell is not None:
                    notes.append(f"{widget.id}: no {role} slot left, took the "
                                 f"{cell.name} slot ({neighbour}) instead")
                    break
        if cell is None:
            free = [c for c in cells if not c.taken]
            if not free:
                notes.append(f"{widget.id}: every slot is taken, left where it was")
                continue
            cell = min(free, key=lambda c: (c.priority, -c.area, c.order))
            cell.taken = True
            notes.append(f"{widget.id}: spilled into the {cell.name} slot")
        _place(registry, widget, cell, notes)
        if role == "hero":
            notes.append(f"{widget.id} is the hero: {widget.geometry['width']}x"
                         f"{widget.geometry['height']} in the {cell.name} slot")

    notes.insert(0, f"{archetype.name}: {len(widgets)} widgets into {len(cells)} slots")
    return notes


def _take(by_role, role):
    for cell in by_role.get(role, ()):
        if not cell.taken:
            cell.taken = True
            return cell
    return None


# A control or a lamp made four times its design size is not a bolder
# design, it is a mistake: a start button filling a foot slot reads as a
# blue slab. Types the rules call not growable take their slot's position
# but keep about their own size.
_NON_GROWABLE_HEADROOM = 1.25


def _place(registry, widget, cell, notes):
    """Size the widget to its type's rule inside the cell and centre it."""
    box_w, box_h = cell.w, cell.h
    definition = registry.get(widget.type) if registry is not None else None
    try:
        rule = _constraints.rule_for(registry, widget.type)
        # Text is the exception: a label's width is its content, so a title
        # held to 1.25 x the registry's 140 px comes out clipped.
        if not rule.growable and definition is not None and widget.type != "Text":
            box_w = min(box_w, int(round(definition.default_width * _NON_GROWABLE_HEADROOM)))
            box_h = min(box_h, int(round(definition.default_height * _NON_GROWABLE_HEADROOM)))
        width, height = _constraints.fit_size(rule, box_w, box_h)
    except NotImplementedError:  # pragma: no cover - until W1 lands
        width, height = cell.w, cell.h
    width, height = int(round(width)), int(round(height))
    if width > cell.w or height > cell.h:
        notes.append(f"{widget.id}: a {widget.type} does not fit the {cell.name} slot "
                     f"at its minimum size; held to {min(width, cell.w)}x"
                     f"{min(height, cell.h)}")
    width = max(1, min(width, cell.w))
    height = max(1, min(height, cell.h))
    before = dict(widget.geometry or {})
    widget.geometry.update({
        "x": cell.x + (cell.w - width) // 2,
        "y": cell.y + (cell.h - height) // 2,
        "width": width,
        "height": height,
    })
    definition = registry.get(widget.type) if registry is not None else None
    if widget.children and definition is not None and definition.container:
        _rescale_children(widget, before, widget.geometry)


def _rescale_children(widget, before, after):
    """Children are parent-relative; keep them where they sat in the box."""
    old_w = float(before.get("width", 0) or 0)
    old_h = float(before.get("height", 0) or 0)
    if old_w <= 0 or old_h <= 0:
        return
    sx, sy = after["width"] / old_w, after["height"] / old_h
    if sx == 1.0 and sy == 1.0:
        return
    for child in widget.children:
        geometry = child.geometry
        geometry["x"] = int(round(float(geometry.get("x", 0) or 0) * sx))
        geometry["y"] = int(round(float(geometry.get("y", 0) or 0) * sy))
        geometry["width"] = max(1, int(round(float(geometry.get("width", 1) or 1) * sx)))
        geometry["height"] = max(1, int(round(float(geometry.get("height", 1) or 1) * sy)))
