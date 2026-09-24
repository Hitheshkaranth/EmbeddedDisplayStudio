"""designer/layout/style.py -- surfaces, type scale and semantic colour.

Geometry alone does not make a screen look designed: related things have to
sit on a surface, text has to come in three or four deliberate sizes rather
than a dozen accidental ones, and colour has to mean something. This pass
applies the kit's own tokens (Theme.qml, the same ones hmi-ui renders with)
to a laid-out page.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from . import constraints as _constraints
from . import grid as _grid
# Imported by name, not as a module: designer.layout re-exports the function
# `archetypes`, which shadows the submodule on the package.
from .archetypes import _clamp_rect, role_for

# The type scale, in px, for a 1024x768 screen; scaled with the screen's
# diagonal for other sizes. display: the hero readout; title: a screen or
# card heading; body: a readout; caption: a label under a value.
TYPE_SCALE = {"display": 44, "title": 20, "body": 15, "caption": 12}

# The screen the scale above was drawn for.
REFERENCE_DIAGONAL = math.hypot(1024, 768)
# A 480x272 panel gets smaller type, a 1920x1080 one larger, but neither
# gets a scale nobody can read.
SCALE_LIMITS = (0.6, 1.8)

# Where the kit keeps its tokens. Parsed, not imported: this module runs in
# the Designer, in the AI tab and in a plain unittest with no QML engine.
_THEME_QML = Path(__file__).resolve().parents[2] / "ui" / "qml" / "Shadcn" / "Theme.qml"

# Enough of the kit to style a page when the QML file is not on disk (a
# packaged Studio, a test fixture directory). Same values as Theme.qml.
_FALLBACK_TOKENS = {
    "background": ("#ffffff", "#09090b"), "foreground": ("#020817", "#ecedee"),
    "card": ("#ffffff", "#18181b"), "cardForeground": ("#020817", "#ecedee"),
    "primary": ("#0f172a", "#006fee"), "primaryForeground": ("#f8fafc", "#ffffff"),
    "secondary": ("#f1f5f9", "#27272a"), "muted": ("#f1f5f9", "#27272a"),
    "mutedForeground": ("#64748b", "#a1a1aa"), "accent": ("#f1f5f9", "#3f3f46"),
    "destructive": ("#ef4444", "#f31260"), "border": ("#e2e8f0", "#303036"),
    "input": ("#e2e8f0", "#27272a"), "ring": ("#020817", "#006fee"),
    "success": ("#22c55e", "#17c964"), "warning": ("#f59e0b", "#f5a524"),
    "brand": ("#006fee", "#006fee"), "info": ("#3b82f6", "#006fee"),
}
_FALLBACK_NUMBERS = {"radiusSm": 4.0, "radiusMd": 12.0, "radiusLg": 16.0,
                     "radiusXl": 20.0, "spacing8": 8.0, "spacing12": 12.0}

# What a colour property called <name> means, so a raw hex the model invented
# can be swapped for the token that already says it.
_COLOUR_TOKENS = (
    ("fault", "destructive"), ("critical", "destructive"), ("alarm", "destructive"),
    ("danger", "destructive"), ("destructive", "destructive"),
    ("warn", "warning"), ("caution", "warning"),
    ("normal", "success"), ("success", "success"), ("good", "success"), ("ok", "success"),
    ("border", "border"), ("track", "muted"), ("background", "card"),
    ("text", "foreground"),
)
# The zone colours a widget bound to a threshold should be showing.
_ZONE_TOKENS = {"warn": "warning", "fault": "destructive", "normal": "success"}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}")
_COLOR_LINE_RE = re.compile(
    r"readonly\s+property\s+color\s+(\w+)\s*:\s*(.+)")
_NUMBER_LINE_RE = re.compile(
    r"readonly\s+property\s+(?:real|int)\s+(\w+)\s*:\s*(-?[0-9.]+)\s*$")

_TOKEN_CACHE: dict = {}


def _tokens() -> tuple:
    """(light, dark, numbers, every literal any token ever holds)."""
    cached = _TOKEN_CACHE.get("tokens")
    if cached is not None:
        return cached
    light, dark = {}, {}
    numbers = dict(_FALLBACK_NUMBERS)
    text = ""
    try:
        text = _THEME_QML.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        match = _COLOR_LINE_RE.search(line)
        if match:
            name, rest = match.group(1), match.group(2)
            literals = [_normalise_hex(value) for value in _HEX_RE.findall(rest)]
            literals = [value for value in literals if value]
            if not literals:
                continue
            # `mode === "light" ? <light> : <dark>`; an instrument colour that
            # does not follow the theme has one literal and uses it for both.
            light[name] = literals[0]
            dark[name] = literals[1] if len(literals) > 1 else literals[0]
            continue
        match = _NUMBER_LINE_RE.search(line)
        if match:
            try:
                numbers[match.group(1)] = float(match.group(2))
            except ValueError:
                pass
    for name, (light_value, dark_value) in _FALLBACK_TOKENS.items():
        light.setdefault(name, light_value)
        dark.setdefault(name, dark_value)
    values = frozenset(list(light.values()) + list(dark.values()))
    cached = (light, dark, numbers, values)
    _TOKEN_CACHE["tokens"] = cached
    return cached


def _normalise_hex(value) -> str:
    """'#ABC', '#aabbcc', '#ffaabbcc' -> '#aabbcc'; anything else -> ''."""
    text = str(value or "").strip().lower()
    if not text.startswith("#"):
        return ""
    digits = text[1:]
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    elif len(digits) == 8:          # #aarrggbb, the way Qt writes it
        digits = digits[2:]
    if len(digits) != 6 or any(ch not in "0123456789abcdef" for ch in digits):
        return ""
    return "#" + digits


def theme_colour(project, token: str) -> str:
    """The '#rrggbb' of a kit theme token ('warning', 'destructive',
    'success', 'card', 'border', 'mutedForeground', ...) for the project's
    theme, read from the same tokens the panel renders with."""
    light, dark, _numbers, _values = _tokens()
    mode = "light" if getattr(getattr(project, "screen", None), "theme", "dark") == "light" else "dark"
    table = light if mode == "light" else dark
    value = table.get(str(token))
    if value:
        return value
    fallback = _FALLBACK_TOKENS.get(str(token))
    if fallback:
        return fallback[0 if mode == "light" else 1]
    return table.get("foreground", "#ecedee")


def theme_number(token: str, default: float = 0.0) -> float:
    """A kit metric token ('radiusMd', 'spacing12', ...)."""
    _light, _dark, numbers, _values = _tokens()
    return float(numbers.get(str(token), default))


def _is_token_value(value) -> bool:
    """True when this colour already is one of the kit's own."""
    normalised = _normalise_hex(value)
    if not normalised:
        return False
    return normalised in _tokens()[3]


def _type_scale(project) -> dict:
    diagonal = math.hypot(float(project.screen.width), float(project.screen.height))
    scale = diagonal / REFERENCE_DIAGONAL if REFERENCE_DIAGONAL else 1.0
    scale = min(max(scale, SCALE_LIMITS[0]), SCALE_LIMITS[1])
    return {name: max(1, int(round(size * scale))) for name, size in TYPE_SCALE.items()}


def _absolute_rects(page):
    """(widget, x, y, w, h) for the whole tree, in screen coordinates."""
    out = []

    def walk(widgets, dx, dy):
        for widget in widgets:
            geometry = widget.geometry or {}
            x = float(geometry.get("x", 0) or 0) + dx
            y = float(geometry.get("y", 0) or 0) + dy
            w = float(geometry.get("width", 0) or 0)
            h = float(geometry.get("height", 0) or 0)
            out.append((widget, x, y, w, h))
            if widget.children:
                walk(widget.children, x, y)

    walk(page.widgets, 0.0, 0.0)
    return out


def _text_roles(project, page, grid):
    """Which step of the scale every Text on the page belongs to."""
    rects = _absolute_rects(page)
    texts = [item for item in rects if item[0].type == "Text"]
    others = [item for item in rects if item[0].type != "Text"]
    roles = {}
    gap = max(8, int(getattr(grid, "gutter", 8) or 8) * 2)
    for widget, x, y, w, _h in texts:
        role = "body"
        for _other, ox, oy, ow, oh in others:
            if oy + oh <= y <= oy + oh + gap and _overlap(x, w, ox, ow) >= 0.5:
                role = "caption"
                break
        if float(widget.properties.get("fontSize", 0) or 0) >= TYPE_SCALE["display"] * 0.75:
            role = "display"
        roles[id(widget)] = role
    # Exactly one title: the biggest type in the top band, topmost wins a tie.
    band = float(project.screen.height) * 0.25
    heading = [item for item in texts
               if item[2] <= band and roles[id(item[0])] != "display"]
    if heading:
        heading.sort(key=lambda item: (-float(item[0].properties.get("fontSize", 0) or 0),
                                       item[2], item[1], item[0].id))
        roles[id(heading[0][0])] = "title"
    return roles


def _overlap(a, aw, b, bw) -> float:
    """How much of the narrower of two spans the two share, 0..1."""
    span = min(a + aw, b + bw) - max(a, b)
    narrower = min(aw, bw)
    if span <= 0 or narrower <= 0:
        return 0.0
    return span / narrower


def _caption_text(widget) -> str:
    """'engine.coolant_temp' -> 'Coolant Temp'; 'fuelQty' -> 'Fuel Qty'."""
    source = ""
    for name in ("value", "readout"):
        binding = widget.bindings.get(name)
        if binding is not None and binding.tag:
            source = binding.tag
            break
    if not source:
        for binding in widget.bindings.values():
            if binding.tag:
                source = binding.tag
                break
    if source:
        words = re.split(r"[._\-]+", source)[-1]
        words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", words)
        words = words.replace("_", " ")
    else:
        words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", widget.id)
    words = re.sub(r"\s+", " ", words).strip()
    return words.title() or widget.id


def apply_style(project, page, registry, grid=None) -> list[str]:
    """Style `page` in place; returns a note per change worth explaining.

    In order:
      1. Type scale: every Text widget's fontSize snaps to the nearest step
         of TYPE_SCALE for its role (the page's one title -> "title", labels
         under widgets -> "caption", the rest -> "body"), scaled for the
         screen; nothing ends up between two steps.
      2. Semantic colour: a widget bound to a tag with warning/critical
         thresholds gets the kit's warning/destructive tokens for its zones;
         success/ok states get the success token; nothing keeps a raw hex
         the model invented when a token means the same thing.
      3. Captions: a face with no label of its own (constraints.wants_caption)
         gets a Text caption under it, from its binding's tag or its id,
         sized "caption" and aligned to the face's left edge.
      4. Consistency: every widget that carries a corner radius or border
         colour takes the theme's radius/border so cards, tiles and buttons
         agree.
    The background of the screen is left alone: it is the design's own.
    """
    notes: list[str] = []
    notes.extend(sane_scales(page, registry))
    if grid is None:
        grid = _grid.grid_for(project.screen.width, project.screen.height)
    scale = _type_scale(project)

    # 1. Type scale.
    roles = _text_roles(project, page, grid)
    for widget, _x, _y, _w, _h in _absolute_rects(page):
        if widget.type != "Text":
            continue
        role = roles.get(id(widget), "body")
        size = scale[role]
        before = widget.properties.get("fontSize")
        if before is None or int(round(float(before))) != size:
            widget.properties["fontSize"] = size
            notes.append(f"{widget.id}: {role} type, {before or '-'} -> {size} px")

    # 2. Semantic colour.
    notes.extend(_apply_colour(project, page, registry))

    # 3. Captions under the faces that carry no label of their own.
    notes.extend(_apply_captions(project, page, registry, grid, scale))

    # 4. One radius and one border across the screen.
    notes.extend(_apply_consistency(project, page, registry))
    return notes


def _apply_colour(project, page, registry) -> list[str]:
    notes = []
    for widget in page.walk():
        definition = registry.get(widget.type) if registry is not None else None
        if definition is None:
            continue
        thresholds = any(binding.warning or binding.critical
                         for binding in widget.bindings.values())
        for prop in definition.color_properties:
            token = _token_for_property(prop)
            if not token:
                continue
            current = widget.properties.get(prop, None)
            if current in (None, ""):
                # Only a widget that actually says "this zone is a warning"
                # gets a zone colour written onto it; the rest keep the kit's
                # own defaults, which are already tokens.
                if not (thresholds and _zone_token(prop)):
                    continue
            elif _is_token_value(current):
                continue            # already one of the kit's own
            elif not _normalise_hex(current):
                continue            # a named colour or an expression: not ours
            value = theme_colour(project, token)
            if _normalise_hex(widget.properties.get(prop, "")) == value:
                continue
            widget.properties[prop] = value
            notes.append(f"{widget.id}.{prop}: {current or 'unset'} -> the "
                         f"{token} token ({value})")
    return notes


def _token_for_property(prop: str) -> str:
    name = str(prop).lower()
    for needle, token in _COLOUR_TOKENS:
        if needle in name:
            return token
    return ""


def _zone_token(prop: str) -> str:
    name = str(prop).lower()
    for needle, token in _ZONE_TOKENS.items():
        if needle in name:
            return token
    return ""


def _intersects(a, b) -> bool:
    return (min(a[0] + a[2], b[0] + b[2]) > max(a[0], b[0])
            and min(a[1] + a[3], b[1] + b[3]) > max(a[1], b[1]))


def _apply_captions(project, page, registry, grid, scale) -> list[str]:
    notes = []
    margin = int(getattr(grid, "margin", 0) or 0)
    gutter = int(getattr(grid, "gutter", 8) or 8)
    gap = max(4, gutter // 2)
    height = max(1, int(round(scale["caption"] * 1.6)))
    colour = theme_colour(project, "mutedForeground")
    existing = {widget.id for widget in project.all_widgets()}
    added = []
    for widget in list(page.widgets):
        if not _constraints.wants_caption(registry, widget.type):
            continue
        caption_id = f"{widget.id}Caption"
        if caption_id in existing:
            continue                # already captioned: styling is idempotent
        geometry = widget.geometry or {}
        x = int(round(float(geometry.get("x", 0) or 0)))
        y = int(round(float(geometry.get("y", 0) or 0)))
        w = int(round(float(geometry.get("width", 0) or 0)))
        h = int(round(float(geometry.get("height", 0) or 0)))
        width = max(40, min(w, project.screen.width - margin - x))
        # A caption that lands on the neighbour below undoes the composition's
        # one achievement: nothing on top of anything else. Under the face is
        # where it belongs, so the face gives back the band it needs before
        # the caption is moved above it.
        occupied = [(item[1], item[2], item[3], item[4]) for item in _absolute_rects(page)
                    if item[0] is not widget] + [
            (c.geometry["x"], c.geometry["y"], c.geometry["width"], c.geometry["height"])
            for c in added]

        def free(candidate_top):
            if candidate_top < margin or candidate_top + height > project.screen.height - margin:
                return False
            return not any(_intersects((x, candidate_top, width, height), rect)
                           for rect in occupied)

        top, shrink_to = y + h + gap, 0
        if not free(top):
            floor = _constraints.rule_for(registry, widget.type).min_height
            shorter = h - (height + gap)
            if shorter >= floor and free(y + shorter + gap):
                top, shrink_to = y + shorter + gap, shorter
            elif free(y - gap - height):
                top = y - gap - height
            else:
                notes.append(f"{widget.id}: no room for a caption around it")
                continue
        if shrink_to:
            widget.geometry["height"] = shrink_to
            notes.append(f"{widget.id}: {h} -> {shrink_to} px tall, to make room "
                         f"for its caption")
        caption = type(widget)(
            type="Text", id=project.unique_id(caption_id),
            geometry={"x": x, "y": top, "width": width, "height": height},
            properties={"text": _caption_text(widget), "fontSize": scale["caption"],
                        "bold": False, "color": colour,
                        "horizontalAlignment": "Text.AlignLeft",
                        "verticalAlignment": "Text.AlignVCenter"},
        )
        existing.add(caption.id)
        added.append(caption)
        notes.append(f"{widget.id}: captioned {caption.properties['text']!r} under it")
    # Appended, never inserted: a caller comparing the page before and after
    # finds its own widgets in the order it left them.
    page.widgets.extend(added)
    return notes


def _apply_consistency(project, page, registry) -> list[str]:
    notes = []
    radius = int(round(theme_number("radiusMd", 12.0)))
    border = theme_colour(project, "border")
    for widget in page.walk():
        definition = registry.get(widget.type) if registry is not None else None
        if definition is None:
            continue
        for prop in ("radius", "cornerRadius"):
            if prop in definition.properties and widget.properties.get(prop) != radius:
                widget.properties[prop] = radius
                notes.append(f"{widget.id}.{prop}: the theme's radius ({radius} px)")
        for prop in definition.color_properties:
            if "border" not in prop.lower():
                continue
            current = widget.properties.get(prop, "")
            if current in (None, "") or _is_token_value(current):
                continue
            if _normalise_hex(current) and _normalise_hex(current) != border:
                widget.properties[prop] = border
                notes.append(f"{widget.id}.{prop}: the theme's border ({border})")
    return notes


# -- surfaces -------------------------------------------------------------


def group_into_cards(project, page, registry, grid=None) -> list[str]:
    """Put related widgets on ShCard surfaces, in place.

    Widgets that sit in the same grid band and share a role (a row of
    readouts, a column of status lamps) are wrapped in one ShCard with a
    title from what they have in common (the tag prefix, or the role), the
    children re-laid inside the card's content box with the grid's gutter.
    A group of one is not worth a card. Returns a note per card created.
    """
    notes: list[str] = []
    if grid is None:
        grid = _grid.grid_for(project.screen.width, project.screen.height)
    gutter = int(getattr(grid, "gutter", 8) or 8)
    pad = max(8, gutter)

    candidates = []
    for widget in page.widgets:
        definition = registry.get(widget.type) if registry is not None else None
        if definition is not None and definition.container:
            continue                # a surface is not put on a surface
        role = role_for(registry, widget)
        if role in ("caption", "hero", "table"):
            continue
        geometry = widget.geometry or {}
        cx = float(geometry.get("x", 0) or 0) + float(geometry.get("width", 0) or 0) / 2.0
        cy = float(geometry.get("y", 0) or 0) + float(geometry.get("height", 0) or 0) / 2.0
        col, row = grid.nearest_cell(cx, cy)
        candidates.append((widget, role, col, row))

    taken: set = set()
    groups = []
    # A row of three or more peers first, then a column of two or more of
    # what is left: a row reads as a band, a column as a stack.
    for axis, minimum in (("row", 3), ("col", 2)):
        buckets: dict = {}
        for widget, role, col, row in candidates:
            if id(widget) in taken:
                continue
            key = (role, row if axis == "row" else col)
            buckets.setdefault(key, []).append(widget)
        for key in sorted(buckets, key=lambda k: (k[0], k[1])):
            members = buckets[key]
            if len(members) < minimum:
                continue
            prefix = _common_tag_prefix(members)
            if not prefix:
                continue
            members.sort(key=lambda w: (float(w.geometry.get("x", 0) or 0),
                                        float(w.geometry.get("y", 0) or 0), w.id))
            for member in members:
                taken.add(id(member))
            groups.append((key[0], axis, prefix, members))

    for role, axis, prefix, members in groups:
        notes.extend(_make_card(project, page, registry, grid, role, axis, prefix,
                                members, pad, gutter))
    return notes


def _common_tag_prefix(widgets) -> str:
    """The first tag segment every member shares, '' when they share none."""
    prefixes = set()
    for widget in widgets:
        tags = [binding.tag for binding in widget.bindings.values() if binding.tag]
        if not tags:
            return ""
        prefixes.update(tag.split(".")[0] for tag in tags)
    if len(prefixes) != 1:
        return ""
    return prefixes.pop()


_ROLE_NAMES = {"primary": "Readings", "secondary": "Readouts", "control": "Controls",
               "status": "Status", "rail": "Details", "table": "Records"}


def _make_card(project, page, registry, grid, role, axis, prefix, members,
               pad, gutter) -> list[str]:
    left = min(float(w.geometry.get("x", 0) or 0) for w in members)
    top = min(float(w.geometry.get("y", 0) or 0) for w in members)
    right = max(float(w.geometry.get("x", 0) or 0) + float(w.geometry.get("width", 0) or 0)
                for w in members)
    bottom = max(float(w.geometry.get("y", 0) or 0) + float(w.geometry.get("height", 0) or 0)
                 for w in members)
    rect = _clamp_rect(grid, (left - pad, top - pad,
                              right - left + 2 * pad, bottom - top + 2 * pad))
    title = (prefix or _ROLE_NAMES.get(role, "Group")).replace("_", " ").title()
    card_id = project.unique_id(f"{re.sub(r'[^A-Za-z0-9_]', '', prefix) or role}Card")
    card = type(members[0])(
        type="ShCard", id=card_id,
        geometry={"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]},
        properties={"color": theme_colour(project, "card"),
                    "borderColor": theme_colour(project, "border"),
                    "borderWidth": 1,
                    "radius": int(round(theme_number("radiusMd", 12.0)))},
    )
    # ShCard has no title property in the registry, so the title lives in the
    # note rather than being invented on the widget (see the summary).
    definition = registry.get("ShCard") if registry is not None else None
    if definition is not None and "title" in definition.properties:
        card.properties["title"] = title

    inner_x, inner_y = pad, pad
    inner_w = max(1, rect[2] - 2 * pad)
    inner_h = max(1, rect[3] - 2 * pad)
    count = len(members)
    for index, member in enumerate(members):
        if axis == "row":
            box_w = (inner_w - (count - 1) * gutter) / float(count)
            box = (inner_x + round(index * (box_w + gutter)), inner_y,
                   int(round(box_w)), inner_h)
        else:
            box_h = (inner_h - (count - 1) * gutter) / float(count)
            box = (inner_x, inner_y + round(index * (box_h + gutter)),
                   inner_w, int(round(box_h)))
        rule = _constraints.rule_for(registry, member.type)
        width, height = _constraints.fit_size(rule, box[2], box[3])
        width = max(1, min(int(round(width)), box[2]))
        height = max(1, min(int(round(height)), box[3]))
        member.geometry.update({
            "x": int(box[0] + (box[2] - width) // 2),
            "y": int(box[1] + (box[3] - height) // 2),
            "width": width, "height": height,
        })
        card.children.append(member)

    first = min(page.widgets.index(member) for member in members)
    for member in members:
        page.widgets.remove(member)
    page.widgets.insert(min(first, len(page.widgets)), card)
    return [f"{title}: {count} {role} widgets onto one card ({card.id})"]

# -- readable scales ---------------------------------------------------------
# A model changes a gauge's range and leaves the kit's step behind: 0..100
# with the ShClusterGauge default step of 1 draws a hundred major ticks and
# five hundred minor ones, and the dial turns into a scribble. A tick step is
# not a matter of taste, so it is repaired rather than reported: the nearest
# 1-2-5 step that leaves between MIN_TICKS and MAX_TICKS divisions.
TICK_PROPERTIES = (("minimumValue", "maximumValue", "majorStep"),
                   ("minimumValue", "maximumValue", "step"),
                   ("minValue", "maxValue", "step"))
MIN_TICKS = 4
MAX_TICKS = 12


def _nice_step(span: float) -> float:
    """The 1-2-5 step that divides `span` into MIN_TICKS..MAX_TICKS parts."""
    import math
    if span <= 0:
        return 1.0
    rough = span / float(MAX_TICKS - 2)
    magnitude = 10.0 ** math.floor(math.log10(rough)) if rough > 0 else 1.0
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = factor * magnitude
        if MIN_TICKS <= span / step <= MAX_TICKS:
            return step
    return max(span / float(MAX_TICKS), 1e-6)


def _walk(widgets):
    for widget in widgets:
        yield widget
        yield from _walk(widget.children)


def sane_scales(page, registry) -> list:
    """Repair unreadable tick scales on `page`, in place; one note each."""
    notes = []
    for widget in _walk(page.widgets):
        definition = registry.get(widget.type) if registry is not None else None
        if definition is None:
            continue
        for low_key, high_key, step_key in TICK_PROPERTIES:
            if step_key not in definition.properties or low_key not in definition.properties:
                continue
            defaults = definition.defaults or {}
            try:
                low = float(widget.properties.get(low_key, defaults.get(low_key, 0.0)))
                high = float(widget.properties.get(high_key, defaults.get(high_key, 0.0)))
                step = float(widget.properties.get(step_key, defaults.get(step_key, 0.0)))
            except (TypeError, ValueError):
                break
            span = high - low
            if span <= 0:
                break
            ticks = span / step if step > 0 else float("inf")
            if MIN_TICKS <= ticks <= MAX_TICKS:
                break
            better = _nice_step(span)
            if abs(better - step) < 1e-9:
                break
            widget.properties[step_key] = better
            notes.append(f"{widget.id}: {int(round(ticks)) if ticks != float('inf') else 'countless'} "
                         f"ticks over {low:g}..{high:g} is unreadable; step {step:g} -> {better:g}")
            break
    return notes
