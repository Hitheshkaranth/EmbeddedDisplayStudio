"""designer/layout/compiler.py -- compile a screen from what it is about.

The polish pipeline (archetype -> arrange -> style) starts from the model's
geometry and moves it until the critic is satisfied. Geometry is the thing a
language model is worst at, so this module never reads it. It takes the
screen's *content* -- a title, and sections ("Discharge flow", role hero;
"Pressures", role readings; "Pump control", role controls) each holding
widgets -- and compiles the layout the way a designer would build it:

    header      title on the left, status / navigation on the right, a rule
    regions     one titled card per section; the arrangement of the cards is
                chosen by searching row, column and hero-split partitions of
                the body and scoring how well every section's content fits
                its card (a cost model, not a template)
    content     inside a card, widgets of one kind form a band (faces in a
                row at one height, tiles on an equal grid, controls as a
                button row, lamps as labelled dots, charts and tables filling
                what is left); bands stack along the card's long axis
    tokens      one spacing scale, one type scale, one card style, semantic
                button variants, all from the kit's theme

Everything is deterministic: the same sections on the same screen compile to
the same pixels, and the model's widgets keep their ids, types, properties,
bindings and actions -- only geometry and the compiler's own chrome change.

Entry points:
    compile_page(project, page, registry, sections=None, title="") -> CompileReport
    infer_sections(page, registry) -> (title, sections)   # for geometry drafts
"""
from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field

from . import constraints as _constraints
from . import intake as _intake

# -- vocabulary -------------------------------------------------------------

ROLES = ("hero", "instruments", "readings", "trend", "alarms", "status", "controls", "info")
ROLE_ALIASES = {
    "primary": "hero", "main": "hero", "key": "hero", "focus": "hero",
    "gauges": "instruments", "dials": "instruments", "meters": "instruments",
    "kpi": "readings", "kpis": "readings", "values": "readings", "metrics": "readings",
    "readouts": "readings", "secondary": "readings", "tiles": "readings", "data": "readings",
    "chart": "trend", "trends": "trend", "history": "trend",
    "alarm": "alarms", "events": "alarms", "table": "alarms",
    "lamps": "status", "indicators": "status", "telltales": "status", "annunciators": "status",
    "control": "controls", "actions": "controls", "commands": "controls", "setpoints": "controls",
    "header": "status", "footer": "controls", "details": "info", "text": "info",
}
# The order sections read in, top-left first, when the model gave none.
ROLE_ORDER = {role: index for index, role in enumerate(ROLES)}
# How much of the screen a role asks for, relative to its content.
ROLE_WEIGHT = {"hero": 2.4, "instruments": 1.3, "readings": 1.0, "trend": 1.4,
               "alarms": 1.2, "status": 0.7, "controls": 0.8, "info": 0.7}
ROLE_TITLES = {"hero": "", "instruments": "Instruments", "readings": "Readings",
               "trend": "Trend", "alarms": "Alarms", "status": "Status",
               "controls": "Controls", "info": "Information"}

# What a widget is, which decides how it is laid out inside a card.
FACE, TILE, STRIP, CHART, TABLE, CONTROL, LAMP, TEXT = (
    "face", "tile", "strip", "chart", "table", "control", "lamp", "text")
KIND_ORDER = {FACE: 0, TILE: 1, STRIP: 2, CHART: 3, TABLE: 4, LAMP: 5, CONTROL: 6, TEXT: 7}
# A tile this much wider than tall (a segment bar, a progress bar) reads as a
# strip: it takes a whole row instead of a grid cell.
STRIP_ASPECT = 3.0
TILE_TYPES = ("ShValueTile", "ShNumDisplay", "ShAutoReadout", "ShDataField", "ShTripInfo",
              "ShAnalogDisplay", "ShSegmentBar", "ShProgress", "ShGearIndicator",
              "ShDriveMode", "ShIconTile", "ShAlert", "Image", "Rectangle")
LAMP_TYPES = ("ShStatDot", "ShTelltale", "ShAnnunciator")
CONTROL_TYPES = ("ShButton", "ShToggle", "ShCheckbox", "ShSelect", "ShSlider", "ShNumInput",
                 "ShInput", "ShTabs")
CHART_TYPES = ("ShTrendChart",)
TABLE_TYPES = ("ShAlarmTable",)
# Controls that take a whole row, and the ones that sit side by side.
FULL_ROW_CONTROLS = ("ShSlider", "ShNumInput", "ShSelect", "ShInput", "ShTabs")

# Button words -> the kit variant that says what the button does.
_DESTRUCTIVE_WORDS = ("stop", "e-stop", "estop", "emergency", "shutdown", "shut down",
                      "abort", "kill", "halt")
_PRIMARY_WORDS = ("start", "run", "enable", "open", "apply", "confirm", "engage", "ignite",
                  "on", "auto")
_SECONDARY_WORDS = ("reset", "ack", "acknowledge", "silence", "clear", "test", "close",
                    "off", "manual", "back", "home", "menu", "settings", "details")

# Marks the widgets the compiler made itself (card, card title, header, lamp
# labels), so a recompile can strip and rebuild them -- the same contract as
# polish's CAPTION_MARK.
CHROME_MARK = "_compiledChrome"
# "<card title>|<role>" on every widget of a planned screen ("|title" on the
# title text, "|header" on header widgets): the plan, carried by the widgets
# themselves so it survives a sectioned run's merge and a recompile.
SECTION_MARK = "_section"
# Where a lamp's own label goes when the compiler draws it beside the lamp.
LAMP_LABEL_MARK = "_lampLabel"
# A header logo the plan asked to put at the left end, before the title.
SIDE_MARK = "_side"


def is_planned(page) -> bool:
    """True when the page's widgets carry a plan (SECTION_MARK)."""
    return any(widget.properties.get(SECTION_MARK) for widget in _walk(page.widgets))


@dataclass
class Section:
    """One region of the screen: a titled card holding widgets."""
    title: str
    role: str
    widgets: list
    note: str = ""


@dataclass
class CompileReport:
    """What compiling did."""
    layout: str = ""
    sections: list = field(default_factory=list)   # (title, role, (x, y, w, h))
    notes: list = field(default_factory=list)
    cost: float = 0.0
    candidates: int = 0
    density: float = 1.0


@dataclass(frozen=True)
class Tokens:
    """The spacing and type scale for one screen size."""
    margin: int
    gap: int
    pad: int
    header: int
    card_title: int
    title_font: int
    card_title_font: int
    label_font: int
    control_h: int
    radius: int


def tokens_for(width: int, height: int, density: float = 1.0) -> Tokens:
    """A 4-px based spacing scale and a type scale for a W x H screen.

    `density` below 1 tightens the spacing, the card chrome and the control
    height together, for a screen whose content needs more room than it has.
    """
    screen = max(240, min(int(width), int(height)))
    short = screen * max(0.5, min(1.0, float(density)))

    def step(value, low, high):
        return int(max(low, min(high, 4 * round(value / 4.0))))

    # The frame of the glass (margin, header, title) stays; what is inside
    # the cards tightens.
    margin = step(screen * 0.032, 12, 32)
    gap = step(short * 0.022, 6, 24)
    pad = step(short * 0.022, 8, 20)
    header = step(screen * 0.085, 40, 72)
    title_font = int(max(16, min(30, round(header * 0.42))))
    card_title_font = int(max(11, min(17, round(short * 0.022))))
    card_title = int(card_title_font * 1.9)
    label_font = int(max(10, min(15, round(short * 0.018))))
    # 32 px is the floor a finger still hits reliably on a panel.
    control_h = step(short * 0.062, 32, 56)
    return Tokens(margin, gap, pad, header, card_title, title_font, card_title_font,
                  label_font, control_h, 12)


# -- classification ---------------------------------------------------------

def _shows_a_word(widget) -> bool:
    """A value tile reading a name ("Indiranagar"), not a number: in a grid
    cell sized for "4.2" it is clipped, so it takes a row of its own."""
    value = widget.properties.get("value")
    if widget.type != "ShValueTile" or not isinstance(value, str) or len(value.strip()) < 7:
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


def kind_of(registry, widget) -> str:
    """face, tile, chart, table, control, lamp or text."""
    widget_type = widget.type
    if widget_type == "Text":
        return TEXT
    if widget_type in CHART_TYPES:
        return CHART
    if widget_type in TABLE_TYPES:
        return TABLE
    if widget_type in LAMP_TYPES:
        return LAMP
    if widget_type in CONTROL_TYPES:
        return CONTROL
    definition = registry.get(widget_type) if registry is not None else None
    if widget_type in TILE_TYPES:
        if definition is not None and definition.default_width >= STRIP_ASPECT * definition.default_height:
            return STRIP
        if _shows_a_word(widget):
            return STRIP
        return TILE
    if definition is not None and definition.action_signals:
        return CONTROL
    if definition is not None and definition.category in _constraints.FACE_CATEGORIES:
        return FACE
    return TILE


def role_of(text) -> str:
    """A role name from whatever the model wrote ("KPIs" -> readings)."""
    key = re.sub(r"[^a-z]", "", str(text or "").lower())
    if key in ROLES:
        return key
    return ROLE_ALIASES.get(key, "readings")


# How big a widget is drawn relative to its design size. A plan may ask for it
# per section or widget ("size": "compact"), and the compiler lowers the
# screen-wide density when the content needs more room than the glass has.
SIZE_MARK = "_size"
SIZE_FACTORS = {"compact": 0.75, "small": 0.75, "tight": 0.75, "normal": 1.0, "medium": 1.0,
                "default": 1.0, "large": 1.35, "big": 1.35, "prominent": 1.35}
# Below this a face stops reading even when the screen is crowded.
MIN_DENSITY = 0.6
_SCALE = {"density": 1.0}


def size_factor(widget) -> float:
    """The widget's own size wish times the screen's density."""
    wish = SIZE_FACTORS.get(str(widget.properties.get(SIZE_MARK, "") or "").lower(), 1.0)
    return wish * _SCALE["density"]


def _design(registry, widget) -> tuple:
    """The size the widget is laid out from: its design size, scaled."""
    definition = registry.get(widget.type) if registry is not None else None
    width, height = (140, 90) if definition is None else (
        max(1, int(definition.default_width)), max(1, int(definition.default_height)))
    factor = size_factor(widget)
    return max(1, int(round(width * factor))), max(1, int(round(height * factor)))


def _rule(registry, widget):
    """constraints.rule_for with the minimums scaled like the design size;
    a control never goes under the touch floor."""
    import dataclasses
    rule = _constraints.rule_for(registry, widget.type)
    factor = size_factor(widget)
    if abs(factor - 1.0) < 1e-6:
        return rule
    min_w = max(_constraints.ABSOLUTE_MINIMUM, int(rule.min_width * factor))
    min_h = max(_constraints.ABSOLUTE_MINIMUM, int(rule.min_height * factor))
    definition = registry.get(widget.type) if registry is not None else None
    if definition is not None and definition.action_signals:
        min_h = max(min_h, 32)
    if rule.square:
        min_w = min_h = max(min_w, min_h)
    return dataclasses.replace(rule, min_width=min_w, min_height=min_h)


def _aspect(registry, widget) -> float:
    rule = _rule(registry, widget)
    if rule.square:
        return 1.0
    width, height = _design(registry, widget)
    return width / float(height)


# -- band layouts -----------------------------------------------------------
# A band lays out widgets of one kind in a box (w x h, origin 0,0) and
# returns [(widget, (x, y, w, h))], plus a fit score in 0..1 (1 = every
# widget at or above its design size with little waste). `natural` gives the
# height a band wants at a width, for the bands that do not grow.

@dataclass
class Placed:
    widget: object
    rect: tuple            # x, y, w, h relative to the band
    extra: list = field(default_factory=list)   # chrome made for it: [(widget, rect)]


def _face_band(registry, widgets, width, height, tokens, hero=False):
    """Faces in one or two rows, one height each row, spaced evenly."""
    count = len(widgets)
    aspects = [_aspect(registry, w) for w in widgets]
    gap = tokens.gap
    best = None
    for rows in range(1, min(count, 3) + 1):
        per_row = math.ceil(count / rows)
        groups = [list(range(i, min(i + per_row, count))) for i in range(0, count, per_row)]
        row_h = (height - (len(groups) - 1) * gap) / float(len(groups))
        if row_h <= 0:
            continue
        scale_h = row_h
        for group in groups:
            span = sum(aspects[i] for i in group)
            usable = width - (len(group) + 1) * gap * 0.5
            scale_h = min(scale_h, usable / span if span else row_h)
        if scale_h <= 0:
            continue
        # The size a face reads best at: a hero may fill its card, a peer
        # stops at about twice its design size so a row of dials stays a row.
        cap = max(_design(registry, widgets[i])[1] * (6.0 if hero else 2.2) for i in range(count))
        face_h = min(scale_h, cap)
        area = sum(face_h * face_h * aspects[i] for i in range(count))
        if best is None or area > best[0] + 1:
            best = (area, groups, face_h)
    if best is None:
        return [], 0.0
    _area, groups, face_h = best
    placed = []
    total_h = len(groups) * face_h + (len(groups) - 1) * gap
    top = (height - total_h) / 2.0
    for row_index, group in enumerate(groups):
        widths = [face_h * aspects[i] for i in group]
        free = width - sum(widths)
        spacing = free / float(len(group) + 1)
        x = spacing
        y = top + row_index * (face_h + gap)
        for i, face_w in zip(group, widths):
            placed.append(Placed(widgets[i], (x, y, face_w, face_h)))
            x += face_w + spacing
    score = _size_score(registry, placed)
    return placed, score


def _tile_band(registry, widgets, width, height, tokens):
    """Tiles on an equal grid, the column count that keeps their proportion."""
    count = len(widgets)
    design_w = max(_design(registry, w)[0] for w in widgets)
    design_h = max(_design(registry, w)[1] for w in widgets)
    aspect = design_w / float(design_h)
    gap = tokens.gap
    best = None
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        cell_w = (width - (columns - 1) * gap) / float(columns)
        cell_h = (height - (rows - 1) * gap) / float(rows)
        if cell_w <= 0 or cell_h <= 0:
            continue
        tile_h = min(cell_h, design_h * 1.6, cell_w / aspect * 1.5)
        tile_w = min(cell_w, max(design_w * 1.9, tile_h * aspect * 1.4))
        too_small = max(0.0, 1.0 - min(tile_w / (design_w * 0.75), tile_h / (design_h * 0.75)))
        ratio = (tile_w / tile_h) / aspect
        shape = abs(math.log(ratio))
        empty_rows = rows * columns - count
        cost = too_small * 4 + shape + empty_rows * 0.15
        if best is None or cost < best[0]:
            best = (cost, columns, rows, cell_w, cell_h, tile_w, tile_h)
    if best is None:
        return [], 0.0
    _cost, columns, rows, cell_w, cell_h, tile_w, tile_h = best
    grid_w = columns * tile_w + (columns - 1) * gap
    grid_h = rows * tile_h + (rows - 1) * gap
    left = (width - grid_w) / 2.0
    top = (height - grid_h) / 2.0
    placed = []
    for index, widget in enumerate(widgets):
        row, column = divmod(index, columns)
        in_row = min(columns, count - row * columns)
        # A short last row is centred under the full ones.
        offset = (columns - in_row) * (tile_w + gap) / 2.0
        cell_x = left + offset + column * (tile_w + gap)
        cell_y = top + row * (tile_h + gap)
        own_w, own_h = _fit_in_cell(registry, widget, tile_w, tile_h)
        placed.append(Placed(widget, (cell_x + (tile_w - own_w) / 2.0,
                                      cell_y + (tile_h - own_h) / 2.0, own_w, own_h)))
    return placed, _size_score(registry, placed)


def _fit_in_cell(registry, widget, cell_w, cell_h):
    """The widget's own size inside a grid cell: its proportion, and no more
    than a little past its design size when it is chrome that does not grow
    (a gear indicator scales its glyphs with its height and spills)."""
    rule = _rule(registry, widget)
    design_w, design_h = _design(registry, widget)
    # Tiles draw text sized from their height and do not grow their width to
    # match, so none goes far past its design size: the cell's extra room is
    # whitespace around it, not a bigger number that clips.
    # Scaled as a whole from the design size: a tile's text is laid out for
    # its design proportion, and stretching one axis clips it.
    growth = 1.35 if rule.growable else 1.2
    scale = min(cell_w / design_w, cell_h / design_h, growth)
    scale = max(scale, min(rule.min_width / design_w, rule.min_height / design_h))
    return min(design_w * scale, cell_w), min(design_h * scale, cell_h)


def _strip_band(registry, widgets, width, height, tokens):
    """Strips stacked full width, each near its design height."""
    gap = tokens.gap
    heights = [_design(registry, w)[1] * 1.25 for w in widgets]
    total = sum(heights) + gap * (len(widgets) - 1)
    scale = min(1.6, height / total) if total else 1.0
    y = max(0.0, (height - total * scale) / 2.0)
    placed = []
    for widget, strip_h in zip(widgets, heights):
        design_w = _design(registry, widget)[0]
        strip_w = min(width, design_w * 2.4)
        placed.append(Placed(widget, ((width - strip_w) / 2.0, y, strip_w, strip_h * scale)))
        y += strip_h * scale + gap
    return placed, _size_score(registry, placed)


def _fill_band(registry, widgets, width, height, tokens):
    """Charts and tables: side by side, each filling its share."""
    count = len(widgets)
    gap = tokens.gap
    horizontal = width >= height * 1.2 * count or count == 1
    placed = []
    if horizontal:
        cell = (width - (count - 1) * gap) / float(count)
        for i, widget in enumerate(widgets):
            placed.append(Placed(widget, (i * (cell + gap), 0, cell, height)))
    else:
        cell = (height - (count - 1) * gap) / float(count)
        for i, widget in enumerate(widgets):
            placed.append(Placed(widget, (0, i * (cell + gap), width, cell)))
    return placed, _size_score(registry, placed)


def _lamp_items(registry, widgets, tokens, compact=False):
    """(widget, item width, item height) for every lamp."""
    items = []
    floor = 36 if compact else 60
    for widget in widgets:
        if widget.type == "ShStatDot":
            label = _lamp_label(widget)
            width = int(22 + 10 + max(floor, len(label) * tokens.label_font * 0.58))
            items.append((widget, width, max(24 if compact else 28, tokens.label_font * 2)))
        elif widget.type == "ShTelltale":
            label = _lamp_label(widget)
            icon = 28 if compact else 40
            width = int(icon + 10 + max(floor, len(label) * tokens.label_font * 0.58))
            items.append((widget, width, icon + 4))
        else:
            design_w, design_h = _design(registry, widget)
            items.append((widget, design_w, design_h))
    return items


def _lamp_band(registry, widgets, width, height, tokens):
    """Lamps on a grid of equal cells; a status dot gets a label beside it.
    When the full-size grid does not fit, the compact one (smaller lamps,
    tighter labels) is used before anything spills out of the card."""
    items = _lamp_items(registry, widgets, tokens)
    if _lamp_natural(registry, widgets, width, tokens) > height + 0.5:
        items = _lamp_items(registry, widgets, tokens, compact=True)
    cell_w = max(item[1] for item in items)
    cell_h = max(item[2] for item in items)
    gap = tokens.gap
    columns = max(1, min(len(items), int((width + gap) // (cell_w + gap))))
    rows = math.ceil(len(items) / columns)
    # Spread the columns across the band rather than packing them left.
    cell_w = max(cell_w, (width - (columns - 1) * gap) / float(columns))
    grid_h = rows * cell_h + (rows - 1) * gap
    top = max(0.0, (height - grid_h) / 2.0)
    placed = []
    for index, (widget, item_w, item_h) in enumerate(items):
        row, column = divmod(index, columns)
        x = column * (cell_w + gap)
        y = top + row * (cell_h + gap)
        if widget.type in ("ShStatDot", "ShTelltale"):
            # The lamp, and its words beside it: the kit's telltale draws its
            # own label over the icon at panel sizes, so the compiler moves
            # it into a Text of its own.
            dot = 20 if widget.type == "ShStatDot" else min(40, item_h - 4)
            label = _lamp_label(widget)
            if widget.type == "ShTelltale":
                widget.properties[LAMP_LABEL_MARK] = label
                widget.properties["label"] = ""
            item = Placed(widget, (x, y + (cell_h - dot) / 2.0, dot, dot))
            item.extra.append(("label", label, (x + dot + 10, y, cell_w - dot - 10, cell_h)))
            placed.append(item)
        else:
            w = min(item_w if widget.type == "ShTelltale" else cell_w, cell_w)
            placed.append(Placed(widget, (x + (cell_w - w) / 2.0, y + (cell_h - item_h) / 2.0,
                                          w, item_h)))
    fit = 1.0 if grid_h <= height + 0.5 else max(0.0, height / grid_h)
    return placed, fit


def _lamp_natural(registry, widgets, width, tokens):
    items = _lamp_items(registry, widgets, tokens)
    cell_w = max(item[1] for item in items)
    cell_h = max(item[2] for item in items)
    columns = max(1, min(len(items), int((width + tokens.gap) // (cell_w + tokens.gap))))
    rows = math.ceil(len(items) / columns)
    return rows * cell_h + (rows - 1) * tokens.gap


def _control_band(registry, widgets, width, height, tokens):
    """Full-row controls stacked, then toggles on a grid, then buttons in a row."""
    rows_full = [w for w in widgets if w.type in FULL_ROW_CONTROLS]
    switches = [w for w in widgets if w.type in ("ShToggle", "ShCheckbox")]
    buttons = [w for w in widgets if w not in rows_full and w not in switches]
    gap = tokens.gap
    placed, y = [], 0.0
    blocks = _control_blocks(registry, rows_full, switches, buttons, width, tokens)
    total = sum(block[0] for block in blocks) + gap * max(0, len(blocks) - 1)
    # Controls sit at the foot of their card, where a thumb expects them.
    y = max(0.0, height - total) if total < height else 0.0
    for block_h, layout in blocks:
        for widget, (bx, by, bw, bh) in layout:
            placed.append(Placed(widget, (bx, y + by, bw, bh)))
        y += block_h + gap
    fit = 1.0 if total <= height + 0.5 else max(0.0, height / total)
    return placed, fit


def _control_blocks(registry, rows_full, switches, buttons, width, tokens):
    gap = tokens.gap
    blocks = []
    for widget in rows_full:
        design_h = _design(registry, widget)[1]
        block_h = max(tokens.control_h, design_h)
        blocks.append((block_h, [(widget, (0, 0, width, block_h))]))
    if switches:
        item_w = max(_design(registry, w)[0] for w in switches)
        columns = max(1, min(len(switches), int((width + gap) // (item_w + gap))))
        cell_w = (width - (columns - 1) * gap) / float(columns)
        rows = math.ceil(len(switches) / columns)
        row_h = tokens.control_h
        layout = []
        for index, widget in enumerate(switches):
            row, column = divmod(index, columns)
            layout.append((widget, (column * (cell_w + gap), row * (row_h + gap), cell_w, row_h)))
        blocks.append((rows * row_h + (rows - 1) * gap, layout))
    if buttons:
        design_w = max(_design(registry, w)[0] for w in buttons)
        # A button needs its words and some padding, not its design width:
        # three short commands share a row rather than one spilling out.
        need = max(_control_need(registry, w, tokens) for w in buttons)
        per_row = len(buttons)
        while per_row > 1 and (width - (per_row - 1) * gap) / per_row < min(need, design_w * 0.85):
            per_row -= 1
        rows = math.ceil(len(buttons) / per_row)
        cell_w = (width - (per_row - 1) * gap) / float(per_row)
        button_w = min(cell_w, max(design_w * 1.8, cell_w if per_row > 1 else design_w * 2.2))
        button_h = tokens.control_h
        layout = []
        for index, widget in enumerate(buttons):
            row, column = divmod(index, per_row)
            in_row = min(per_row, len(buttons) - row * per_row)
            row_w = in_row * button_w + (in_row - 1) * gap
            left = (width - row_w) / 2.0
            layout.append((widget, (left + column * (button_w + gap), row * (button_h + gap),
                                    button_w, button_h)))
        blocks.append((rows * button_h + (rows - 1) * gap, layout))
    return blocks


def _control_need(registry, widget, tokens) -> float:
    """The narrowest a control reads at: a button's words, a toggle or a
    slider at most of its design width."""
    if widget.type == "ShButton":
        return max(72.0, len(str(widget.properties.get("text", "") or "")) * tokens.label_font * 0.62 + 28)
    return _design(registry, widget)[0] * 0.85


def _control_natural(registry, widgets, width, tokens):
    rows_full = [w for w in widgets if w.type in FULL_ROW_CONTROLS]
    switches = [w for w in widgets if w.type in ("ShToggle", "ShCheckbox")]
    buttons = [w for w in widgets if w not in rows_full and w not in switches]
    blocks = _control_blocks(registry, rows_full, switches, buttons, width, tokens)
    return sum(block[0] for block in blocks) + tokens.gap * max(0, len(blocks) - 1)


def _text_band(registry, widgets, width, height, tokens):
    line = tokens.label_font * 1.8
    placed = [Placed(w, (0, i * line, width, line)) for i, w in enumerate(widgets)]
    total = len(widgets) * line
    return placed, 1.0 if total <= height + 0.5 else height / total


def _tile_natural(registry, widgets, width, tokens):
    design_w = max(_design(registry, w)[0] for w in widgets)
    design_h = max(_design(registry, w)[1] for w in widgets)
    columns = max(1, min(len(widgets), int((width + tokens.gap) // (design_w * 0.8 + tokens.gap))))
    rows = math.ceil(len(widgets) / columns)
    return rows * design_h * 1.15 + (rows - 1) * tokens.gap


def _size_score(registry, placed) -> float:
    """1 when every widget is at least its design size, falling as they shrink."""
    if not placed:
        return 0.0
    scores = []
    for item in placed:
        design_w, design_h = _design(registry, item.widget)
        rule = _rule(registry, item.widget)
        width, height = item.rect[2], item.rect[3]
        if width < rule.min_width - 0.5 or height < rule.min_height - 0.5:
            scores.append(max(0.0, min(width / max(1, rule.min_width),
                                       height / max(1, rule.min_height))) * 0.3)
            continue
        scores.append(min(1.0, 0.55 + 0.45 * min(width / design_w, height / design_h)))
    return sum(scores) / len(scores)


# -- one card ---------------------------------------------------------------

def _bands(registry, widgets) -> list:
    """[(kind, [widgets])] in reading order of kinds."""
    groups: dict = {}
    for widget in widgets:
        groups.setdefault(kind_of(registry, widget), []).append(widget)
    return sorted(groups.items(), key=lambda item: KIND_ORDER.get(item[0], 9))


_FLEX = (FACE, CHART, TABLE)


def _natural(registry, kind, widgets, width, tokens):
    """Height a fixed band wants at `width`; None for a band that grows."""
    if kind == CONTROL:
        return _control_natural(registry, widgets, width, tokens)
    if kind == LAMP:
        return _lamp_natural(registry, widgets, width, tokens)
    if kind == TILE:
        return _tile_natural(registry, widgets, width, tokens)
    if kind == STRIP:
        return sum(_design(registry, w)[1] * 1.25 for w in widgets) + tokens.gap * (len(widgets) - 1)
    if kind == TEXT:
        return len(widgets) * tokens.label_font * 1.8
    return None


def _band(registry, kind, widgets, width, height, tokens, hero):
    if kind == FACE:
        return _face_band(registry, widgets, width, height, tokens, hero)
    if kind == TILE:
        return _tile_band(registry, widgets, width, height, tokens)
    if kind == STRIP:
        return _strip_band(registry, widgets, width, height, tokens)
    if kind in (CHART, TABLE):
        return _fill_band(registry, widgets, width, height, tokens)
    if kind == LAMP:
        return _lamp_band(registry, widgets, width, height, tokens)
    if kind == CONTROL:
        return _control_band(registry, widgets, width, height, tokens)
    return _text_band(registry, widgets, width, height, tokens)


def layout_content(registry, widgets, width, height, tokens, hero=False):
    """Lay out a card's widgets in a w x h box; returns (placed, fit 0..1).

    Tries the bands stacked vertically and, for a wide box, side by side
    (faces beside their tiles), and keeps the better fit.
    """
    bands = _bands(registry, widgets)
    if not bands or width < 8 or height < 8:
        return [], 0.0
    best = _stack(registry, bands, width, height, tokens, hero, vertical=True)
    kinds = {kind for kind, _widgets in bands}
    if len(bands) > 1 and width > height * 1.25 and LAMP not in kinds:
        side = _stack(registry, bands, width, height, tokens, hero, vertical=False)
        # Side by side only when it is clearly better: a stack reads in order.
        if side[1] > best[1] + 0.05:
            best = side
    return best


def _stack(registry, bands, width, height, tokens, hero, vertical):
    gap = tokens.gap
    count = len(bands)
    along = height if vertical else width
    across = width if vertical else height
    available = along - gap * (count - 1)
    fixed, flex = {}, []
    for index, (kind, widgets) in enumerate(bands):
        if vertical:
            natural = _natural(registry, kind, widgets, across, tokens)
        else:
            natural = _side_natural(registry, kind, widgets, across, tokens)
        if natural is None:
            flex.append(index)
        else:
            fixed[index] = natural
    fixed_total = sum(fixed.values())
    if not flex:
        # Nothing grows: share the slack so the bands breathe evenly.
        scale = available / fixed_total if fixed_total else 1.0
        sizes = {i: fixed[i] * min(scale, 1.6) if scale >= 1 else fixed[i] * scale
                 for i in fixed}
    else:
        remaining = available - fixed_total
        if remaining < along * 0.3:
            # The fixed bands would starve the faces: they give back first.
            squeeze = max(0.4, (available - along * 0.3) / fixed_total) if fixed_total else 1.0
            fixed = {i: v * min(1.0, squeeze) for i, v in fixed.items()}
            remaining = available - sum(fixed.values())
        weights = {i: (1.0 if bands[i][0] == FACE else 0.8) for i in flex}
        total_weight = sum(weights.values())
        sizes = dict(fixed)
        for i in flex:
            sizes[i] = max(1.0, remaining * weights[i] / total_weight)
    placed, scores, offset = [], [], 0.0
    used = sum(sizes.values()) + gap * (count - 1)
    offset = max(0.0, (along - used) / 2.0)
    for index, (kind, widgets) in enumerate(bands):
        size = sizes[index]
        band_w, band_h = (across, size) if vertical else (size, across)
        items, score = _band(registry, kind, widgets, band_w, band_h, tokens, hero)
        if kind in (CONTROL, LAMP, TEXT, STRIP) and score < 0.999:
            # These report the share of their content that fits; the rest is
            # past the card's edge, which is a defect, not a compromise.
            score = score ** 4
        for item in items:
            x, y, w, h = item.rect
            dx, dy = (0, offset) if vertical else (offset, 0)
            item.rect = (x + dx, y + dy, w, h)
            item.extra = [(e[0], e[1], (e[2][0] + dx, e[2][1] + dy, e[2][2], e[2][3]))
                          for e in item.extra]
            placed.append(item)
        scores.append(score * len(widgets))
        offset += size + gap
    fit = sum(scores) / max(1, sum(len(b[1]) for b in bands))
    # Waste: a card that is mostly empty reads as unfinished.
    ink = sum(item.rect[2] * item.rect[3] for item in placed)
    density = ink / float(max(1.0, width * height))
    if density < 0.18:
        fit *= 0.75 + density
    return placed, fit


def _side_natural(registry, kind, widgets, height, tokens):
    """Width a fixed band wants beside the faces (a column)."""
    if kind == TILE:
        design_w = max(_design(registry, w)[0] for w in widgets)
        design_h = max(_design(registry, w)[1] for w in widgets)
        rows = max(1, min(len(widgets), int((height + tokens.gap) // (design_h * 0.85 + tokens.gap))))
        columns = math.ceil(len(widgets) / rows)
        return columns * design_w * 1.1 + (columns - 1) * tokens.gap
    if kind == CONTROL:
        return max(_design(registry, w)[0] for w in widgets) * 1.6
    if kind == STRIP:
        return max(_design(registry, w)[0] for w in widgets) * 1.1
    if kind == LAMP:
        return max(item[1] for item in _lamp_items(registry, widgets, tokens)) * 1.3
    if kind == TEXT:
        return 220
    return None


# -- regions ----------------------------------------------------------------

def _section_weight(registry, section) -> float:
    area = 0.0
    for widget in section.widgets:
        design_w, design_h = _design(registry, widget)
        area += design_w * design_h
    return max(1.0, area) * ROLE_WEIGHT.get(section.role, 1.0)


def _weights(registry, sections) -> dict:
    """Area-based weights with a floor, so a two-button card is not a sliver."""
    raw = {i: _section_weight(registry, s) for i, s in enumerate(sections)}
    floor = 0.35 * sum(raw.values()) / max(1, len(raw))
    return {i: max(value, floor) for i, value in raw.items()}


def section_minimum(registry, section, tokens) -> tuple:
    """(width, height) below which the section's card cannot hold its content."""
    width = height = 0.0
    bands = _bands(registry, section.widgets)
    for kind, widgets in bands:
        rules = [_rule(registry, w) for w in widgets]
        if kind == FACE:
            band_w = sum(r.min_width for r in rules) + tokens.gap * (len(widgets) - 1)
            band_h = max(r.min_height for r in rules)
            if len(widgets) > 2:      # faces may wrap onto a second row
                band_w = band_w / 2.0 + tokens.gap
                band_h = band_h * 2 + tokens.gap
        elif kind in (CHART, TABLE):
            band_w = max(r.min_width for r in rules)
            band_h = sum(r.min_height for r in rules) + tokens.gap * (len(widgets) - 1)
        elif kind == TILE:
            design_w = max(_design(registry, w)[0] for w in widgets) * 0.75
            design_h = max(_design(registry, w)[1] for w in widgets) * 0.75
            columns = 2 if len(widgets) > 2 else len(widgets)
            rows = math.ceil(len(widgets) / columns)
            band_w = columns * design_w + (columns - 1) * tokens.gap
            band_h = rows * design_h + (rows - 1) * tokens.gap
        elif kind == CONTROL:
            # The narrowest a control card can be is its widest control; its
            # height is measured with the buttons side by side, as laid out.
            needs = [_control_need(registry, w, tokens) for w in widgets]
            band_w = max(needs)
            band_h = _natural(registry, kind, widgets, sum(needs) + tokens.gap * len(needs), tokens)
        elif kind == LAMP:
            items = _lamp_items(registry, widgets, tokens, compact=True)
            band_w = max(item[1] for item in items)
            band_h = _lamp_natural(registry, widgets, band_w * 2 + tokens.gap, tokens)
        else:
            band_w = max(_design(registry, w)[0] for w in widgets) * 0.85
            natural = _natural(registry, kind, widgets, band_w, tokens)
            band_h = natural if natural is not None else 60
        width = max(width, band_w)
        height += band_h
    height += tokens.gap * max(0, len(bands) - 1)
    width += 2 * tokens.pad
    height += 2 * tokens.pad + (tokens.card_title if section.title else 0)
    return width, height


def _compositions(count, limit_parts=4):
    """Every way to cut `count` ordered items into consecutive groups."""
    for cuts in range(0, count):
        for positions in itertools.combinations(range(1, count), cuts):
            bounds = (0,) + positions + (count,)
            groups = [list(range(bounds[i], bounds[i + 1])) for i in range(len(bounds) - 1)]
            if len(groups) <= limit_parts and max(len(g) for g in groups) <= limit_parts:
                yield groups


# Each section's minimum card (width, height) for the search in progress,
# so slicing gives a small card what its content needs before sharing out
# the rest by weight (set by _search).
_MINIMUMS: dict = {}


def _shares(total, weights, minimums):
    """Split `total` by weight, but no share below its minimum: those are
    lifted and the rest re-shared among the others. When even the minimums
    do not fit, everything scales down together."""
    count = len(weights)
    if count == 0:
        return []
    need = sum(minimums)
    if need >= total:
        scale = total / need if need else 0.0
        return [m * scale for m in minimums]
    fixed = [False] * count
    shares = [0.0] * count
    while True:
        free = total - sum(minimums[i] for i in range(count) if fixed[i])
        weight = sum(weights[i] for i in range(count) if not fixed[i]) or 1.0
        lifted = False
        for i in range(count):
            if fixed[i]:
                shares[i] = minimums[i]
                continue
            shares[i] = free * weights[i] / weight
            if shares[i] < minimums[i]:
                fixed[i] = lifted = True
        if not lifted:
            return shares


def _minimum(index, axis):
    pair = _MINIMUMS.get(index)
    return pair[axis] if pair else 0.0


def _slice(rect, groups, weights, gap, horizontal_first):
    """Treemap slice-and-dice: groups across one axis, members along the other,
    each share by weight with every card's minimum honoured first."""
    x, y, w, h = rect
    out = {}
    outer_axis, inner_axis = (1, 0) if horizontal_first else (0, 1)
    totals = [sum(weights[i] for i in group) for group in groups]
    along = (h if horizontal_first else w) - gap * (len(groups) - 1)
    sizes = _shares(along, totals,
                    [max(_minimum(i, outer_axis) for i in group) for group in groups])
    cursor = y if horizontal_first else x
    for group, size in zip(groups, sizes):
        inner_along = (w if horizontal_first else h) - gap * (len(group) - 1)
        parts = _shares(inner_along, [weights[i] for i in group],
                        [_minimum(i, inner_axis) for i in group])
        inner = x if horizontal_first else y
        for i, part in zip(group, parts):
            if horizontal_first:
                out[i] = (inner, cursor, part, size)
            else:
                out[i] = (cursor, inner, size, part)
            inner += part + gap
        cursor += size + gap
    return out


def _candidates(sections, weights, body, gap):
    """(name, {section index: rect}) for every arrangement worth scoring."""
    count = len(sections)
    order = list(range(count))
    for groups in _compositions(count):
        yield "rows " + "/".join(str(len(g)) for g in groups), _slice(body, groups, weights, gap, True)
        yield "cols " + "/".join(str(len(g)) for g in groups), _slice(body, groups, weights, gap, False)
    if count >= 2 and sections[0].role == "hero":
        x, y, w, h = body
        rest = order[1:]
        rest_weights = {i: weights[i] for i in rest}
        for fraction in (0.42, 0.5, 0.58, 0.66):
            hero_w = (w - gap) * fraction
            for groups in _compositions(len(rest), 4):
                mapped = [[rest[i] for i in g] for g in groups]
                for side in ("left", "right"):
                    if side == "left":
                        hero_rect = (x, y, hero_w, h)
                        side_rect = (x + hero_w + gap, y, w - hero_w - gap, h)
                    else:
                        hero_rect = (x + w - hero_w, y, hero_w, h)
                        side_rect = (x, y, w - hero_w - gap, h)
                    for first in (True, False):
                        layout = _slice(side_rect, mapped, rest_weights, gap, first)
                        layout[0] = hero_rect
                        yield f"hero-{side} {fraction:.2f}", layout
            hero_h = (h - gap) * fraction
            for groups in _compositions(len(rest), 4):
                mapped = [[rest[i] for i in g] for g in groups]
                layout = _slice((x, y + hero_h + gap, w, h - hero_h - gap), mapped,
                                rest_weights, gap, False)
                layout[0] = (x, y, w, hero_h)
                yield f"hero-top {fraction:.2f}", layout
        # Hero in the middle, the rest split into a column either side.
        if count >= 3:
            for fraction in (0.4, 0.46, 0.52):
                hero_w = (w - 2 * gap) * fraction
                side_w = (w - 2 * gap - hero_w) / 2.0
                for split in range(1, len(rest)):
                    left, right = rest[:split], rest[split:]
                    layout = {0: (x + side_w + gap, y, hero_w, h)}
                    layout.update(_column(left, (x, y, side_w, h), rest_weights, gap))
                    layout.update(_column(right, (x + side_w + gap + hero_w + gap, y, side_w, h),
                                          rest_weights, gap))
                    yield f"hero-centre {fraction:.2f}", layout


def _column(indices, rect, weights, gap):
    x, y, w, h = rect
    along = h - gap * (len(indices) - 1)
    parts = _shares(along, [weights[i] for i in indices], [_minimum(i, 1) for i in indices])
    out, cursor = {}, y
    for i, part in zip(indices, parts):
        out[i] = (x, cursor, w, part)
        cursor += part + gap
    return out


def _cost(registry, sections, layout, tokens, body):
    """Lower is better: content that does not fit, waste, a weak hero, slivers."""
    cost = 0.0
    hero_area = None
    areas = []
    for index, section in enumerate(sections):
        x, y, w, h = layout[index]
        min_w, min_h = section_minimum(registry, section, tokens)
        # Soft, so the search always has a best answer: every pixel short of
        # what the content needs costs, in proportion.
        short = max(0.0, 1.0 - w / min_w) + max(0.0, 1.0 - h / min_h)
        cost += short * 60.0
        inner_w = w - 2 * tokens.pad
        inner_h = h - 2 * tokens.pad - (tokens.card_title if section.title else 0)
        if inner_w < 16 or inner_h < 16:
            cost += 100.0
            continue
        placed, fit = layout_content(registry, section.widgets, inner_w, inner_h, tokens,
                                     hero=section.role == "hero")
        cost += (1.0 - fit) * 10.0 * (1.6 if section.role == "hero" else 1.0)
        ink = sum(item.rect[2] * item.rect[3] for item in placed)
        density = ink / float(max(1.0, inner_w * inner_h))
        if section.role == "hero":
            # The hero card is the screen's focus: its instrument should fill
            # it, not sit small in a wide band.
            cost += max(0.0, 0.65 - density) * 20.0
        elif section.role not in ("alarms", "trend"):
            # Any card that is mostly air was given room another card needed.
            cost += max(0.0, 0.3 - density) * 6.0
        aspect = w / float(h)
        cost += max(0.0, abs(math.log(aspect)) - math.log(3.2)) * 3.0   # slivers
        if w < body[2] * 0.2 and section.role not in ("status",):
            cost += 3.0                                                 # a column too thin to read
        areas.append(w * h)
        if section.role == "hero":
            hero_area = w * h
    if hero_area is not None:
        others = [a for i, a in enumerate(areas) if sections[i].role != "hero"]
        if others and hero_area < max(others) * 1.15:
            cost += 4.0
    # Fewer distinct edges read calmer: count unique left and top edges.
    lefts = {round(layout[i][0]) for i in layout}
    tops = {round(layout[i][1]) for i in layout}
    cost += 0.15 * (len(lefts) + len(tops))
    return cost


# -- the compiler -----------------------------------------------------------

def compile_page(project, page, registry, sections=None, title: str = "",
                 header_widgets=None, rank: int = 0) -> CompileReport:
    """Lay out `page` from its sections; replaces page.widgets in place.

    Args:
        sections: [Section]; when None they are inferred from the page.
        title: the screen title for the header; inferred when empty.
        header_widgets: widgets to put on the header's right (status, nav).
        rank: 0 for the best arrangement, 1 for the best of another family
            (rows, cols, hero-left, ...), and so on -- the variants offered.
    """
    report = CompileReport()
    _reserve_ids(project, page)
    if sections is None:
        inferred_title, sections, header_auto, notes = infer_sections(page, registry)
        report.notes += notes
        title = title or inferred_title
        header_widgets = list(header_widgets or []) + header_auto
    sections = [s for s in sections if s.widgets]
    # Navigation to a page that does not exist, or to this one, goes nowhere.
    page_ids = {p.id for p in getattr(project, "pages", [])} - {page.id}
    header_widgets = [w for w in (header_widgets or []) if not _dangling(w, page_ids)]
    if not sections and not header_widgets:
        return report
    width, height = int(project.screen.width), int(project.screen.height)
    # A train's cab display (and any other registered family) has one layout
    # drivers or a reader know: it is laid out on the spot by that family, not
    # by the card search below. The family search (designer/layout/families.py)
    # picks the first family that fits a page of this size; no family fits a
    # card screen, which then falls through to the search.
    from . import families
    family = families.family_for(sections, header_widgets, width, height)
    if family is not None:
        _name, family_compile = family
        # The family reads the project's brand accent itself (cab.compile_cab
        # takes project.brand["accent"] when no override is passed).
        family_compile(project, page, registry, sections, title, header_widgets, report, width, height)
        return report
    sections = _consolidate(_ordered(sections), report.notes, section_limit(width, height))
    _hero_caption(sections, report.notes)
    tokens = tokens_for(width, height)
    sections, header_widgets = _promote_status(registry, sections, header_widgets, tokens,
                                               width, report.notes)
    for section in sections:
        _prepare(registry, section, report.notes)
    if len(sections) == 1 and sections[0].role == "hero" and not sections[0].title:
        sections[0].title = ""
    has_header = bool(title or header_widgets)
    # Density: the same search at a few scales of every widget's design size
    # and minimums (and of the spacing and control height). The screen keeps
    # its design sizes unless shrinking clearly lays it out better -- a small
    # charge per step keeps a roomy screen at 1.0.
    density, best_total = 1.0, None
    try:
        for candidate in DENSITIES:
            _SCALE["density"] = candidate
            trial_tokens = tokens_for(width, height, candidate)
            ranked, _count, _body = _search(registry, sections, trial_tokens, width, height, has_header)
            if not ranked:
                break
            total = ranked[0][0] + SHRINK_COST * (1.0 - candidate) / 0.1
            if best_total is None or total < best_total - 0.5:
                density, best_total = candidate, total
    finally:
        _SCALE["density"] = 1.0
    if density < 0.999:
        tokens = tokens_for(width, height, density)
        report.notes.append(f"density {density:.2f}: widgets drawn below their design size to fit")
    report.density = density
    _SCALE["density"] = density
    try:
        return _compile_body(project, page, registry, sections, title, header_widgets,
                             tokens, report, width, height, rank)
    finally:
        _SCALE["density"] = 1.0


# The scales tried, and what each step down costs against the layout's own.
DENSITIES = (1.0, 0.9, 0.8, 0.7, MIN_DENSITY)
SHRINK_COST = 2.0


def _search(registry, sections, tokens, width, height, has_header):
    """(ranked [(cost, name, layout)] one per family, candidates tried, body rect)."""
    top = tokens.margin + ((tokens.header + tokens.gap) if has_header else 0)
    body = (tokens.margin, top, width - 2 * tokens.margin, height - top - tokens.margin)
    if not sections:
        return [], 0, body
    weights = _weights(registry, sections)
    _MINIMUMS.clear()
    _MINIMUMS.update({i: section_minimum(registry, s, tokens) for i, s in enumerate(sections)})
    family_best, count = {}, 0
    for name, layout in _candidates(sections, weights, body, tokens.gap):
        count += 1
        cost = _cost(registry, sections, layout, tokens, body)
        family = name.split(" ")[0]
        if family not in family_best or cost < family_best[family][0] - 1e-6:
            family_best[family] = (cost, name, layout)
    ranked = sorted(family_best.values(), key=lambda item: (item[0], item[1]))
    return ranked, count, body


def _density(registry, sections, tokens, width, height, has_header) -> float:
    """1.0 when the sections' minimum cards fit the body; below it, the
    uniform scale (down to MIN_DENSITY) at which they do."""
    top = tokens.margin + ((tokens.header + tokens.gap) if has_header else 0)
    body_area = (width - 2 * tokens.margin) * (height - top - tokens.margin)
    gaps = tokens.gap * max(0, len(sections) - 1) * min(width, height) * 0.5
    needed = sum(w * h for w, h in (section_minimum(registry, s, tokens) for s in sections))
    if needed <= 0:
        return 1.0
    # Cards never tile perfectly: about 70 % of the body is usable for minimums.
    room = max(1.0, body_area * 0.7 - gaps)
    if needed <= room:
        return 1.0
    return max(MIN_DENSITY, min(1.0, math.sqrt(room / needed)))


def _compile_body(project, page, registry, sections, title, header_widgets, tokens, report,
                  width, height, rank=0):

    chrome = []
    if title or header_widgets:
        chrome += _header(project, registry, title, header_widgets, tokens, width)
    ranked, count, _body = _search(registry, sections, tokens, width, height,
                                   bool(title or header_widgets))
    best = ranked[min(max(0, int(rank)), len(ranked) - 1)] if ranked else None
    widgets = list(chrome)
    if best is not None:
        cost, name, layout = best
        report.layout, report.cost, report.candidates = name, round(cost, 3), count
        for index, section in enumerate(sections):
            rect = tuple(int(round(v)) for v in layout[index])
            widgets.append(_card(project, registry, section, rect, tokens))
            report.sections.append((section.title, section.role, rect))
    page.widgets[:] = widgets
    _tidy_scales(page, registry, report.notes)
    return report


def _promote_status(registry, sections, header_widgets, tokens, width, notes):
    """A few status lamps read best in the header, beside the title, rather
    than in a card of their own that is mostly empty."""
    if len(sections) < 2:
        return sections, header_widgets
    kept = []
    for section in sections:
        lamps = section.widgets
        small = section.role == "status" and len(lamps) <= 4 and all(
            w.type in ("ShStatDot", "ShTelltale") for w in lamps)
        if small and not header_widgets:
            span = sum(48 + len(_lamp_label(w)) * tokens.label_font * 0.6 for w in lamps)
            if span <= width * 0.5:
                header_widgets = list(header_widgets) + list(lamps)
                notes.append(f"{section.title or 'status'}: {len(lamps)} lamps moved to the header")
                continue
        kept.append(section)
    return kept, header_widgets


def _dangling(widget, page_ids) -> bool:
    """A navigate button to a page the project does not have."""
    actions = getattr(widget, "actions", {}) or {}
    targets = [getattr(a, "page", "") for a in actions.values() if getattr(a, "kind", "") == "navigate"]
    return bool(targets) and all(t not in page_ids for t in targets)


MAX_SECTIONS = 6
# Roles whose cards may share one card when there are too many: readings
# with instruments, and status lamps with the controls they report on.
_MERGEABLE = {"readings": "readings", "instruments": "readings", "status": "controls",
              "controls": "controls", "info": "info"}


def section_limit(width: int, height: int) -> int:
    """How many cards a screen holds before they get too small to read:
    six on 1280x800, five on 1024x600, four on 800x480."""
    area = float(width) * float(height) / (1280.0 * 800.0)
    return int(max(3, min(MAX_SECTIONS + 2, round(3.6 + 2.4 * area))))


def _consolidate(sections, notes, limit=MAX_SECTIONS):
    """No more than `limit` cards: the smallest compatible cards share one.

    A plan of nine one-widget cards (or a multi-page plan merged onto one
    page) leaves every card too small for its content; two readings that
    share a card read better than two slivers.
    """
    sections = list(sections)
    while len(sections) > limit:
        best = None
        for i, first in enumerate(sections):
            for j in range(i + 1, len(sections)):
                second = sections[j]
                if first.role == "hero" or second.role == "hero":
                    continue
                if _MERGEABLE.get(first.role) is None or                         _MERGEABLE.get(first.role) != _MERGEABLE.get(second.role):
                    continue
                # Same role first, then the smallest pair.
                size = len(first.widgets) + len(second.widgets) +                     (0 if first.role == second.role else 0.5)
                if best is None or size < best[0]:
                    best = (size, i, j)
        if best is None:
            break
        _size, i, j = best
        first, second = sections[i], sections[j]
        titles = [t for t in (first.title, second.title) if t]
        role = first.role if first.role == second.role else _MERGEABLE[first.role]
        title = " & ".join(titles) if len(" & ".join(titles)) <= 22 else             ROLE_TITLES.get(role, first.title)
        if first.role == "status" or second.role == "status":
            role = "controls" if role != "status" else role
        sections[i] = Section(title, role, first.widgets + second.widgets)
        del sections[j]
        notes.append(f"{' + '.join(titles) or role}: merged onto one card")
    return sections


_ABBREVIATIONS = (("temperature", "temp"), ("pressure", "press"), ("humidity", "humid"),
                  ("position", "pos"), ("differential", "diff"), ("percentage", "%"),
                  ("frequency", "freq"), ("voltage", "volts"), ("current", "amps"))
CAPTION_LIMIT = 15


def _short_caption(text: str) -> str:
    """A cluster gauge's caption sits between its scale numbers; past about
    fifteen characters it runs into them. Abbreviate, then keep the words
    that fit."""
    words = text.split()
    if len(text) <= CAPTION_LIMIT:
        return text
    for long, short in _ABBREVIATIONS:
        words = [(short.title() if w[:1].isupper() and short.islower() else short)
                 if w.lower() == long else w for w in words]
    while len(" ".join(words)) > CAPTION_LIMIT and len(words) > 1:
        words = words[:-1]
    return " ".join(words)[:CAPTION_LIMIT + 4]


def _hero_caption(sections, notes):
    """A long caption on the hero dial collides with its scale; the card's
    title says it instead. A label that only repeats the title goes too."""
    for section in sections:
        if section.widgets and all(w.type == "ShAlarmTable" for w in section.widgets):
            # The table's own header names it; a card heading says it twice.
            section.title = ""
        if section.role == "hero" and len(section.widgets) == 1:
            hero = section.widgets[0]
            caption = str(hero.properties.get("caption", "") or "").strip()
            title = str(section.title or "").strip()
            if caption and title and (caption.lower() in title.lower() or title.lower() in caption.lower()):
                # "Steam Pressure" over a dial captioned "Steam Pressure": the
                # card keeps the fuller name, the dial its readout.
                section.title = caption if len(caption) > len(title) else title
                hero.properties["caption"] = ""
                notes.append(f"{hero.id}: caption folded into the card title")
        for other in section.widgets if section.role != "hero" else ():
            caption = str(other.properties.get("caption", "") or "")
            if other.type == "ShClusterGauge" and len(caption) > CAPTION_LIMIT:
                other.properties["caption"] = _short_caption(caption)
                notes.append(f"{other.id}: caption shortened to fit the dial")
        if section.role != "hero" or len(section.widgets) != 1:
            continue
        widget = section.widgets[0]
        label = str(widget.properties.get("label", "") or "").strip()
        if widget.type == "ShClusterGauge" and len(label) > 6 and not _UNIT_RE.search(label):
            # The cluster gauge's label sits by the scale's end and is meant
            # for "x1000 RPM"; a name there is the card title said again.
            widget.properties["label"] = ""
            notes.append(f"{widget.id}: name-like label cleared")
        caption = str(widget.properties.get("caption", "") or "").strip()
        if len(caption) > 14:
            if len(caption) > len(section.title or ""):
                section.title = caption[:1].upper() + caption[1:]
            widget.properties["caption"] = ""
            notes.append(f"{widget.id}: caption moved to the card title")


def compile_candidates(project, page, registry, brief: str = "", renderer=None,
                       limit: int = 3) -> list:
    """Several compiled versions of `page`, best first; `page` is untouched.

    Returns [(DesignerPage, Critique, name)] -- the shape of
    polish.polish_candidates, so the AI tab's variant strip takes either.
    """
    import copy
    from .critic import critique
    results, seen = [], set()
    for rank in range(max(1, int(limit))):
        trial = copy.deepcopy(page)
        stand_in = copy.copy(project)
        stand_in.pages = [trial if p is page else p for p in project.pages]
        report = compile_page(stand_in, trial, registry, rank=rank)
        if report.layout in seen:
            break
        seen.add(report.layout)
        results.append((trial, critique(stand_in, trial, registry), report.layout))
    return results


def _ordered(sections):
    """Hero first; the rest keep the model's order, which is reading order."""
    heroes = [s for s in sections if s.role == "hero"]
    rest = [s for s in sections if s.role != "hero"]
    if len(heroes) > 1:
        # Two heroes is no hero: the first keeps it.
        for extra in heroes[1:]:
            extra.role = "instruments"
        rest = heroes[1:] + rest
    return heroes[:1] + rest


def _prepare(registry, section, notes):
    """Make every widget in the section say what it is."""
    for widget in section.widgets:
        definition = registry.get(widget.type) if registry is not None else None
        if widget.type == "ShButton":
            _button_variant(widget)
        if definition is None:
            continue
        _live_readout(definition, widget, notes)
        _bands_inside_range(widget, notes)
        _explicit_unit(definition, widget)
        label_prop = _intake.label_property(definition)
        if widget.type == "ShClusterGauge":
            # Its "label" is the small unit text by the scale ("x1000 RPM");
            # the name belongs in "caption", and only when no card says it.
            label_prop = "caption"
            if len(section.widgets) == 1 and section.title:
                continue
        if not label_prop or widget.type in ("Text", "ShButton"):
            continue
        current = str(widget.properties.get(label_prop, "") or "").strip()
        # Only an absent or empty label is filled: one the model wrote stays,
        # even when it happens to be the kit's default ("Active Alarms").
        if not current:
            text = _widget_label(widget)
            if text:
                widget.properties[label_prop] = text
                notes.append(f"{widget.id}: {label_prop} '{text}'")
                current = text
        trimmed = _without_heading(current, section.title)
        if trimmed != current and len(section.widgets) > 1:
            # "Motor Current" in the card "Motor" reads "Current": the card
            # already says whose current it is, and small tiles clip the rest.
            widget.properties[label_prop] = trimmed


_UNIT_PROPERTIES = ("unit", "units", "readoutUnit")


def _explicit_unit(definition, widget):
    """A unit the model left out is the binding's, or none -- never the
    kit's sample unit (a pH readout drew "°C" from ShAutoReadout's default)."""
    binding = (widget.bindings or {}).get("value")
    unit = str(getattr(binding, "unit", "") or "").strip() if binding is not None else ""
    for key in _UNIT_PROPERTIES:
        if key in definition.properties and key not in widget.properties:
            if key == "readoutUnit" and "readout" not in definition.properties:
                continue
            widget.properties[key] = unit


def _bands_inside_range(widget, notes):
    """A chart's warning band past its own scale draws outside the chart."""
    low = widget.properties.get("minValue")
    high = widget.properties.get("maxValue")
    if widget.type != "ShTrendChart" or not isinstance(high, (int, float)):
        return
    low = low if isinstance(low, (int, float)) else 0.0
    for key, default in (("warningHigh", 80.0), ("warningLow", 20.0)):
        value = widget.properties.get(key, default)
        if isinstance(value, (int, float)) and not (low <= value <= high):
            widget.properties[key] = high if key == "warningHigh" else low
            notes.append(f"{widget.id}: {key} {value:g} outside {low:g}..{high:g}, clamped")


def _without_heading(label: str, heading: str) -> str:
    """`label` without a leading `heading` word ("Motor Current", "Motor")."""
    first = str(heading or "").split(" & ")[0].strip()
    if not first or not label.lower().startswith(first.lower() + " "):
        return label
    rest = label[len(first):].strip()
    return rest[:1].upper() + rest[1:] if len(rest) >= 3 else label


def _live_readout(definition, widget, notes):
    """A bound gauge shows its live value: the kit's sample readout ("137
    km/h") stays on the face for good unless the readout is set empty, and
    the readout's unit is the binding's."""
    binding = (widget.bindings or {}).get("value")
    if binding is None or "readout" not in definition.properties:
        return
    if "readout" not in widget.properties:
        widget.properties["readout"] = ""
        notes.append(f"{widget.id}: readout follows the bound value")
    unit = str(getattr(binding, "unit", "") or "").strip()
    if "readoutUnit" in definition.properties and not widget.properties.get("readoutUnit"):
        unit = unit or str(widget.properties.get("label", "") or "")
        widget.properties["readoutUnit"] = unit
    if "label" in definition.properties and "label" not in widget.properties             and widget.type == "ShClusterGauge":
        # Absent, the kit draws its sample "x1000 RPM" by the scale.
        widget.properties["label"] = ""
    # The same unit under the readout and again by the scale says it twice.
    label = str(widget.properties.get("label", "") or "").strip()
    if label and label == str(widget.properties.get("readoutUnit", "")).strip():
        widget.properties["label"] = ""


def _widget_label(widget) -> str:
    for binding in (widget.bindings or {}).values():
        tag = getattr(binding, "tag", "")
        if tag and tag != "*":
            return _intake.humanise(tag)
    return _intake.humanise(widget.id)


def _lamp_label(widget) -> str:
    for key in (LAMP_LABEL_MARK, "label", "text", "title"):
        value = str(widget.properties.get(key, "") or "").strip()
        if value:
            return value
    return _widget_label(widget)


def _button_variant(widget):
    text = str(widget.properties.get("text", "") or "").lower()
    if widget.properties.get("variant") not in (None, "", "default"):
        return
    actions = getattr(widget, "actions", {}) or {}
    navigate = any(getattr(a, "kind", "") == "navigate" for a in actions.values())
    if navigate:
        widget.properties["variant"] = "outline"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in _DESTRUCTIVE_WORDS):
        widget.properties["variant"] = "destructive"
    elif any(re.search(rf"\b{re.escape(word)}\b", text) for word in _SECONDARY_WORDS):
        widget.properties["variant"] = "secondary"
    else:
        widget.properties["variant"] = "default"


def _theme(project, token):
    from .style import theme_colour
    return theme_colour(project, token)


def _new(project, widget_type, base, geometry, properties):
    from designer.model import DesignerWidget
    widget = DesignerWidget(type=widget_type, id=_unique(project, base),
                            geometry={k: int(round(v)) for k, v in geometry.items()},
                            properties=dict(properties))
    widget.properties[CHROME_MARK] = True
    return widget


_TAKEN_KEY = "_compiler_taken_ids"


def _reserve_ids(project, page):
    """Every id in the project except the chrome this compile will rebuild,
    so a recompile names its card `pressuresCard` again, not `pressuresCard2`."""
    taken = set()
    for other in getattr(project, "pages", []):
        for widget in _walk(other.widgets):
            # This page's chrome is rebuilt, and a planned title text is
            # consumed into the header: neither keeps its id.
            if other is page and (widget.properties.get(CHROME_MARK)
                                  or widget.properties.get(SECTION_MARK) == "|title"):
                continue
            taken.add(widget.id)
    try:
        setattr(project, _TAKEN_KEY, taken)
    except Exception:
        pass


def _unique(project, base):
    base = re.sub(r"[^A-Za-z0-9_]", "", base) or "item"
    if not base[0].isalpha():
        base = "w" + base
    base = base[0].lower() + base[1:]
    taken = getattr(project, _TAKEN_KEY, None)
    if taken is None:
        _reserve_ids(project, None)
        taken = getattr(project, _TAKEN_KEY, set())
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}{n}", n + 1
    taken.add(candidate)
    return candidate


def _walk(widgets):
    for widget in widgets:
        yield widget
        yield from _walk(widget.children)


def _text(project, base, rect, text, size, colour, bold=False, align="Text.AlignLeft"):
    # hmi-ui draws a Text from its top edge whatever verticalAlignment says,
    # so the box is made one line tall and centred in the space it was given.
    line = int(round(size * 1.45))
    top = rect[1] + max(0.0, (rect[3] - line) / 2.0)
    rect = (rect[0], top, rect[2], min(rect[3], line) if rect[3] >= line else line)
    return _new(project, "Text", base, {"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]},
                {"text": text, "fontSize": int(size), "bold": bool(bold), "color": colour,
                 "horizontalAlignment": align, "verticalAlignment": "Text.AlignVCenter",
                 "wrapMode": "Text.NoWrap"})


def _place_logo(project, widget, x, y, w, h, out):
    """A header logo at (x, y, w, h); in a dark header, on a light plate.

    Most logos are drawn for paper and their dark lettering vanishes on a
    dark header, so the image sits inset on a white rounded plate.
    """
    widget.geometry.update({"x": int(x), "y": int(y), "width": int(w), "height": int(h)})
    if getattr(project.screen, "theme", "dark") != "light":
        inset = 6
        out.append(_new(project, "Rectangle", f"{widget.id}Plate", dict(widget.geometry),
                        {"color": "#ffffff", "borderWidth": 0, "radius": 8}))
        widget.geometry.update({"x": int(x) + inset, "y": int(y) + inset,
                                "width": int(w) - 2 * inset, "height": int(h) - 2 * inset})
    out.append(widget)


def _header(project, registry, title, header_widgets, tokens, width):
    chrome = []
    x, y = tokens.margin, tokens.margin
    inner_w = width - 2 * tokens.margin
    right = x + inner_w
    # Logos that asked for the left end go before the title, left to right.
    placed_left = []
    for widget in [w for w in header_widgets if w.properties.get(SIDE_MARK) == "left"]:
        design_w, design_h = _design(registry, widget)
        h = min(design_h, tokens.header - 8)
        _place_logo(project, widget, x, y + (tokens.header - h) / 2, design_w, h, placed_left)
        x += design_w + tokens.gap
    header_widgets = [w for w in header_widgets if w.properties.get(SIDE_MARK) != "left"]
    # Header widgets, right to left at their design width.
    placed_right = []
    for widget in reversed(header_widgets):
        kind = kind_of(registry, widget)
        if widget.type == "ShButton":
            _button_variant(widget)
            # Header buttons are chrome: quiet, so the instruments lead.
            if widget.properties.get("variant") == "default":
                widget.properties["variant"] = "outline"
        if widget.type in ("ShStatDot", "ShTelltale"):
            label = _lamp_label(widget)
            if widget.type == "ShTelltale":
                widget.properties[LAMP_LABEL_MARK] = label
                widget.properties["label"] = ""
            dot = 16 if widget.type == "ShStatDot" else 32
            label_w = max(48, len(label) * tokens.label_font * 0.6)
            right -= label_w
            placed_right.append(_text(project, f"{widget.id}Label",
                                      (right, y, label_w, tokens.header), label,
                                      tokens.label_font, _theme(project, "mutedForeground")))
            right -= 8 + dot
            widget.geometry.update({"x": int(right), "y": int(y + (tokens.header - dot) / 2),
                                    "width": dot, "height": dot})
        else:
            design_w, design_h = _design(registry, widget)
            h = min(tokens.control_h if kind == CONTROL else design_h, tokens.header - 8)
            w = design_w if kind != CONTROL else max(design_w, 120)
            right -= w
            if widget.type == "Image":
                _place_logo(project, widget, right, y + (tokens.header - h) / 2, w, h, placed_right)
                right -= tokens.gap
                continue
            widget.geometry.update({"x": int(right), "y": int(y + (tokens.header - h) / 2),
                                    "width": int(w), "height": int(h)})
        placed_right.append(widget)
        right -= tokens.gap
    title_w = max(80, right - x - tokens.gap)
    if title:
        accent = getattr(getattr(project, "brand", None) or {}, "get")("accent")
        heading = _text(project, "screenTitle", (x, y, title_w, tokens.header), title,
                        tokens.title_font, accent or _theme(project, "foreground"), bold=True)
        heading.properties[SECTION_MARK] = "|title"
        chrome.append(heading)
    chrome += placed_left + placed_right
    # A hairline under the header separates the chrome from the instruments.
    chrome.append(_new(project, "Rectangle", "headerRule",
                       {"x": x, "y": y + tokens.header + tokens.gap // 2 - 1, "width": inner_w,
                        "height": 1},
                       {"color": _theme(project, "border"), "borderWidth": 0, "radius": 0}))
    return chrome


def _card(project, registry, section, rect, tokens):
    x, y, w, h = rect
    card = _new(project, "ShCard", (_slug(section.title) or section.role) + "Card",
                {"x": x, "y": y, "width": w, "height": h},
                {"color": _theme(project, "card"), "borderColor": _theme(project, "border"),
                 "borderWidth": 1, "radius": tokens.radius})
    inner_top = tokens.pad
    if section.title:
        heading = _fit_heading(section.title, w - 2 * tokens.pad, tokens.card_title_font)
        card.children.append(_text(project, (_slug(section.title) or "card") + "Heading",
                                   (tokens.pad, tokens.pad - 2, w - 2 * tokens.pad,
                                    tokens.card_title),
                                   heading, tokens.card_title_font,
                                   _theme(project, "mutedForeground"), bold=True))
        inner_top += tokens.card_title
    inner_w = w - 2 * tokens.pad
    inner_h = h - inner_top - tokens.pad
    placed, _fit = layout_content(registry, section.widgets, inner_w, inner_h, tokens,
                                  hero=section.role == "hero")
    for item in placed:
        bx, by, bw, bh = item.rect
        rule = _rule(registry, item.widget)
        if rule.square:
            side = min(bw, bh)
            bx, by = bx + (bw - side) / 2.0, by + (bh - side) / 2.0
            bw = bh = side
        item.widget.geometry.update({"x": int(round(tokens.pad + bx)),
                                     "y": int(round(inner_top + by)),
                                     "width": int(round(bw)), "height": int(round(bh))})
        item.widget.children = list(item.widget.children)
        card.children.append(item.widget)
        for _kind, text, (ex, ey, ew, eh) in item.extra:
            card.children.append(_text(project, f"{item.widget.id}Label",
                                       (tokens.pad + ex, inner_top + ey, ew, eh), text,
                                       tokens.label_font, _theme(project, "foreground")))
    return card


def _fit_heading(title: str, width: float, font: int) -> str:
    """A card heading that fits its card: the full title, else the part
    before " & " (a merged card), else cut with an ellipsis."""
    def fits(text):
        return len(text) * font * 0.6 <= width
    if fits(title):
        return title
    first = title.split(" & ")[0].strip()
    if first != title and fits(first):
        return first
    keep = max(3, int(width / (font * 0.6)) - 1)
    return title[:keep].rstrip() + "…"


def _slug(text):
    words = re.findall(r"[A-Za-z0-9]+", str(text or ""))
    if not words:
        return ""
    return words[0].lower() + "".join(w.title() for w in words[1:])


def _tidy_scales(page, registry, notes):
    """The style pass's scale repairs: sane ranges and 1-2-5 tick steps."""
    try:
        from . import style as _style
        for fn in (_style.sane_ranges, _style.paired_ranges, _style.live_readouts,
                   _style.sane_scales):
            notes.extend(fn(page, registry) or [])
    except Exception as exc:          # a repair is a bonus, never a failure
        notes.append(f"scale repair skipped: {exc}")


# -- sections from a geometry draft ------------------------------------------

def strip_chrome(widgets):
    """Unwrap a compiled page: cards give back their widgets, chrome goes."""
    out = []
    for widget in widgets:
        if widget.properties.get(CHROME_MARK):
            if widget.children:
                out.extend(strip_chrome(widget.children))
            continue
        out.append(widget)
    return out


def infer_sections(page, registry):
    """(title, [Section], header_widgets, notes) from a page of placed widgets.

    For a design that arrived as geometry (the model's usual format, or a
    hand-drawn page): the title is the top text, captions are folded into the
    faces they describe, and widgets are grouped by what they are.
    """
    notes = []
    planned_title = next((w for w in _walk(page.widgets)
                          if w.properties.get(SECTION_MARK) == "|title"), None)
    widgets = strip_chrome(list(page.widgets))
    if any(w.properties.get(SECTION_MARK) for w in widgets) or planned_title is not None:
        return _sections_from_marks(page, registry, widgets, planned_title, notes)
    # Containers the model drew are unwrapped: the compiler draws its own.
    flat = []
    for widget in widgets:
        if widget.type in ("ShCard", "Rectangle", "Item", "Column", "Row", "Grid") and widget.children:
            for child in widget.children:
                child.geometry["x"] = float(child.geometry.get("x", 0)) + float(widget.geometry.get("x", 0))
                child.geometry["y"] = float(child.geometry.get("y", 0)) + float(widget.geometry.get("y", 0))
                flat.append(child)
            continue
        if widget.type in ("ShCard", "Rectangle") and not widget.children:
            notes.append(f"{widget.id}: empty {widget.type} dropped")
            continue
        flat.append(widget)
    flat.sort(key=lambda w: (float(w.geometry.get("y", 0)), float(w.geometry.get("x", 0))))

    texts = [w for w in flat if w.type == "Text"]
    others = [w for w in flat if w.type != "Text"]
    title = ""
    if texts:
        title_widget = min(texts, key=lambda w: (float(w.geometry.get("y", 0)),
                                                 -float(w.properties.get("fontSize", 0) or 0)))
        top_limit = 0.2 * max((float(w.geometry.get("y", 0)) + float(w.geometry.get("height", 0))
                               for w in flat), default=1)
        if float(title_widget.geometry.get("y", 0)) <= top_limit:
            title = str(title_widget.properties.get("text", "") or "").strip()
            texts.remove(title_widget)
    # Captions -> the label of the face nearest them; headings -> dropped.
    for text_widget in texts:
        text = str(text_widget.properties.get("text", "") or "").strip()
        target = _nearest(text_widget, others)
        if target is not None:
            definition = registry.get(target.type)
            label_prop = _intake.label_property(definition)
            current = str(target.properties.get(label_prop, "") or "") if label_prop else ""
            default = str(definition.defaults.get(label_prop, "") or "") if definition else ""
            if label_prop and text and (not current or current == default):
                target.properties[label_prop] = re.sub(r"\s*\(.*?\)\s*$", "", text)
                notes.append(f"{text_widget.id}: caption folded into {target.id}.{label_prop}")
                continue
        notes.append(f"{text_widget.id}: loose text '{text[:24]}' dropped (cards carry headings)")

    header = [w for w in others if w.type == "ShButton" and
              any(getattr(a, "kind", "") == "navigate" for a in (w.actions or {}).values())]
    body = [w for w in others if w not in header]
    groups = {}
    for widget in body:
        groups.setdefault(kind_of(registry, widget), []).append(widget)

    sections = []
    faces = groups.pop(FACE, [])
    if faces:
        hero = _pick_hero(registry, faces)
        if hero is not None:
            sections.append(Section(_widget_title(hero), "hero", [hero]))
            faces = [f for f in faces if f is not hero]
        if faces:
            name = _widget_title(faces[0]) if len(faces) == 1 else "Instruments"
            sections.append(Section(name, "instruments", faces))
    for kind, role, name in ((TILE, "readings", "Readings"), (CHART, "trend", "Trend"),
                             (TABLE, "alarms", "Alarms"), (LAMP, "status", "Status"),
                             (CONTROL, "controls", "Controls"), (TEXT, "info", "Information")):
        members = groups.pop(kind, [])
        if not members:
            continue
        if kind == CHART and len(members) == 1:
            name = _widget_title(members[0]) or name
        sections.append(Section(name, role, members))
    if sections and sections[0].role != "hero":
        # No dial to build around: the biggest chart or table leads instead.
        lead = next((s for s in sections if s.role in ("trend", "alarms")), None)
        if lead is not None and len(sections) > 2:
            lead.role = "hero"
    # A table titles itself; its card heading would say it twice.
    for section in sections:
        if section.role in ("alarms",) and all(w.type == "ShAlarmTable" for w in section.widgets):
            section.title = ""
    return title, sections, header, notes


_UNIT_RE = re.compile(r"^[^A-Za-z]*$|/|^(x?\d+\s*)?[a-zA-Z%°³²]{1,5}$")


def _sections_from_marks(page, registry, widgets, planned_title, notes):
    """Sections exactly as planned; widgets added since (unmarked) are grouped
    by kind after them."""
    title = str(planned_title.properties.get("text", "") or "").strip() if planned_title else ""
    header, order, groups, loose = [], [], {}, []
    for widget in widgets:
        mark = str(widget.properties.get(SECTION_MARK, "") or "")
        if mark == "|title":
            continue
        if mark == "|header":
            header.append(widget)
            continue
        if not mark:
            loose.append(widget)
            continue
        heading, _bar, role = mark.rpartition("|")
        key = (heading, role)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(widget)
    sections = [Section(heading, role_of(role), groups[(heading, role)]) for heading, role in order]
    # A picture dropped into the header band by hand is a logo for the
    # header: it keeps the end it was dropped at, and stays there from now on.
    right_edge = max((float(w.geometry.get("x", 0)) + float(w.geometry.get("width", 0))
                      for w in _walk(page.widgets)), default=0.0)
    for widget in [w for w in loose if w.type == "Image"]:
        g = widget.geometry
        if float(g.get("y", 0)) + float(g.get("height", 0)) / 2.0 <= 80:
            if float(g.get("x", 0)) + float(g.get("width", 0)) / 2.0 < right_edge / 2.0:
                widget.properties[SIDE_MARK] = "left"
            widget.properties[SECTION_MARK] = "|header"
            loose.remove(widget)
            header.append(widget)
            notes.append(f"{widget.id}: placed in the header as a logo")
    if loose:
        stand_in = type(page)(id=page.id, name=page.name, widgets=loose)
        _t, extra, extra_header, extra_notes = infer_sections(stand_in, registry)
        sections += extra
        header += extra_header
        notes += extra_notes
    return title, sections, header, notes


def _widget_title(widget) -> str:
    """What a card holding only this widget is called: its caption or title,
    its tag in words, and its label only when the label is not a unit
    ("km/h" and "bar" are what a cluster gauge's label usually holds)."""
    for key in ("caption", "title"):
        value = str(widget.properties.get(key, "") or "").strip()
        if value and not _UNIT_RE.search(value):
            return value
    label = str(widget.properties.get("label", "") or "").strip()
    if label and not _UNIT_RE.search(label) and len(label) > 3:
        return label
    return _widget_label(widget)


def _pick_hero(registry, faces):
    def size(widget):
        return float(widget.geometry.get("width", 0)) * float(widget.geometry.get("height", 0))
    ranked = sorted(faces, key=size, reverse=True)
    if len(ranked) == 1:
        return ranked[0]
    if size(ranked[0]) >= size(ranked[1]) * 1.4:
        return ranked[0]
    # Equal faces: no hero is better than an arbitrary one.
    return None


def _nearest(text_widget, widgets, reach=70):
    tx = float(text_widget.geometry.get("x", 0)) + float(text_widget.geometry.get("width", 0)) / 2
    ty = float(text_widget.geometry.get("y", 0)) + float(text_widget.geometry.get("height", 0)) / 2
    best, best_d = None, None
    for widget in widgets:
        x = float(widget.geometry.get("x", 0))
        y = float(widget.geometry.get("y", 0))
        w = float(widget.geometry.get("width", 0))
        h = float(widget.geometry.get("height", 0))
        dx = max(x - tx, 0, tx - (x + w))
        dy = max(y - ty, 0, ty - (y + h))
        d = math.hypot(dx, dy)
        if d <= reach and (best_d is None or d < best_d):
            best, best_d = widget, d
    return best


# -- sections from a plan -----------------------------------------------------

def _distribute(section: dict, widgets: list) -> None:
    """Bindings or actions written on the section instead of its widgets go
    to the widgets: "value" to the first, "value_1" to the second, ..."""
    for key in ("bindings", "actions"):
        shared = section.get(key)
        if not isinstance(shared, dict):
            continue
        for name, value in shared.items():
            match = re.fullmatch(r"([A-Za-z]+)(?:_(\d+))?", str(name))
            if not match:
                continue
            index = int(match.group(2) or 0)
            if index < len(widgets) and not widgets[index].get(key):
                widgets[index][key] = {match.group(1): value}

def sections_from_plan(page_data: dict, convert) -> tuple:
    """(title, [Section], header_widgets) from a planned page.

    `convert` turns a list of widget dicts into DesignerWidgets (the AI
    generator's own converter, so aliasing, bindings and actions behave the
    same as in a geometry design).
    """
    title = str(page_data.get("title") or page_data.get("name") or "").strip()
    sections = []
    entries = []
    for entry in page_data.get("sections") or []:
        if not isinstance(entry, dict):
            continue
        entries.append(entry)
        # A section that swallowed the next one through a duplicate key
        # (designer.layout.intake._pairs) gives it back.
        entries.extend(d for d in entry.get("__spill__") or []
                       if isinstance(d, dict) and d.get("widgets"))
    for entry in entries:
        raw = [dict(w) for w in entry.get("widgets") or [] if isinstance(w, dict)]
        _distribute(entry, raw)
        # "size": "compact" | "normal" | "large", on the section or a widget.
        # Popped before conversion: ShButton has a "size" property of its own
        # ("sm", "lg"), which is not a size wish and stays.
        section_wish = str(entry.get("size") or "").lower()
        wishes = []
        for item in raw:
            wish = str(item.get("size") or "").lower()
            if wish in SIZE_FACTORS:
                item.pop("size")
            else:
                wish = ""
            wishes.append(wish or (section_wish if section_wish in SIZE_FACTORS else ""))
        widgets = convert(raw)
        if len(widgets) == len(wishes):
            for widget, wish in zip(widgets, wishes):
                if wish and wish not in ("normal", "medium", "default"):
                    widget.properties[SIZE_MARK] = wish
        if not widgets:
            continue
        role = role_of(entry.get("role") or entry.get("kind") or "")
        heading = str(entry.get("title") or entry.get("name") or "").strip()
        if not heading and role != "hero":
            heading = ROLE_TITLES.get(role, "")
        sections.append(Section(heading, role, widgets))
    raw_header = [w for w in page_data.get("header") or [] if isinstance(w, dict)]
    # A logo may ask for the left end ("side": "left", beside or inside its
    # properties); the converter drops keys the kit does not declare, so the
    # wish is read here and carried as a mark.
    sides = {}
    for item in raw_header:
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        wish = " ".join(str(d.get(k) or "") for d in (item, props) for k in ("side", "align", "position"))
        if "left" in wish.lower():
            sides[str(item.get("id") or "")] = "left"
    # A logo with no picture is an empty white plate on the glass: leave it out.
    header = [w for w in convert(raw_header)
              if not (w.type == "Image" and not str(w.properties.get("source") or "").strip())]
    for widget in header:
        if widget.type == "Image" and sides.get(widget.id) == "left":
            widget.properties[SIDE_MARK] = "left"
    return title, sections, header
