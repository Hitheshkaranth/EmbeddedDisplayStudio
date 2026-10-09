"""The reference layout: a planned screen arranged the way a picture is.

When a user attaches a reference picture, the plan says where each section
sits on the screen (compiler.REGIONS: top, rail, left, center, right,
bottom). This family lays the page out by those regions instead of searching
card arrangements:

    +-------------------------------------------------------------+
    | left items            CLOCK                      right items |  top strip
    +----+-----------------+------------------+---------+---------+
    |rail|      left       |      center      |  right  |  card   |
    |pill|  (frameless)    |   (frameless)    | column  |  card   |
    |    +-----------------+------------------+  of     |  card   |
    |        bottom row, sections side by side| cards   |  card   |
    +-----------------------------------------+---------+---------+

The status strip carries the header (the clock centred and big, items marked
"side": "left" at the left end, the rest at the right) and any "top"
sections. The rail is a narrow rounded pill at the left edge (a gear
selector); the right column stacks its sections as cards in plan order,
each as tall as its content asks; left and center share the upper body and
the bottom row runs under them. A region the plan leaves empty gives its
room to its neighbours, and a section with no region joins the center.

Left, center and bottom sections are frameless, as instruments on the glass
are in such pictures; the rail and the right column keep their cards. A
section's accent tints its card and fills its widgets' empty colours.

Like the rest of the compiler this never reads model geometry: the regions,
accents and side marks are on the widgets, so a recompile ("Tidy up", Size on
screen) rebuilds the same screen.
"""
from __future__ import annotations

import dataclasses
import re

#: The name this family is registered under in designer.layout.families.
FAMILY_NAME = "reference layout"

#: Share of the screen's width the rail and the right column take.
RAIL_SHARE = 0.075
RIGHT_SHARE = 0.28
#: Share of the upper body (left + center) the left column takes.
LEFT_SHARE = 0.40
#: Share of the body's height the bottom row takes, before content adjusts it.
BOTTOM_SHARE = 0.42

#: Colour properties an accent fills when the plan left them empty.
ACCENT_PROPERTIES = ("accentColor", "barColor", "outerColor", "innerColor")
#: Transparent, in the 8-digit form both the QML kit and the panel read
#: (the panel's colour parser takes hex only: "transparent" draws magenta).
CLEAR = "#00000000"
_LAMPS = ("ShStatDot", "ShTelltale")


def _applies(sections, header, width, height) -> bool:
    """True for a landscape page whose plan places two or more sections.

    A cab display (two Rail widgets) stays a cab display even when its plan
    names regions: that family is registered first, and this test says no
    to its plans too, so the order of registration is not all that decides.
    """
    if width <= height:
        return False
    if sum(1 for s in sections if getattr(s, "region", "")) < 2:
        return False
    try:
        from . import cab
        if cab.applies(sections, header):
            return False
    except Exception:
        pass
    return True


# -- helpers -----------------------------------------------------------------

def _darker(colour: str, factor: float = 0.62) -> str:
    """The accent's deeper shade, for a gauge's inner ring."""
    value = colour.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    value = value[-6:]
    try:
        r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return colour
    return "#%02x%02x%02x" % tuple(int(round(c * factor)) for c in (r, g, b))


def _apply_accent(registry, section) -> None:
    """Fill the section's widgets' empty colour properties with its accent."""
    accent = section.accent
    if not accent:
        return
    for widget in section.widgets:
        definition = registry.get(widget.type) if registry is not None else None
        if definition is None:
            continue
        for prop in ACCENT_PROPERTIES:
            if prop not in definition.properties:
                continue
            if str(widget.properties.get(prop) or "").strip():
                continue
            widget.properties[prop] = _darker(accent) if prop == "innerColor" else accent


def _words(widget) -> str:
    tags = " ".join(str(getattr(b, "tag", "") or "") for b in (widget.bindings or {}).values())
    props = widget.properties
    return " ".join([widget.id, tags, str(props.get("label") or ""),
                     str(props.get("title") or "")]).lower()


def _is_clock(widget) -> bool:
    """A header Text that tells the time: its id, tag or label says so, or it
    reads like a time ("14:32")."""
    if widget.type != "Text":
        return False
    if re.search(r"clock|\btime\b|_time\b|\.time\b", _words(widget)):
        return True
    return bool(re.fullmatch(r"\s*\d{1,2}:\d\d(:\d\d)?\s*([AaPp][Mm])?\s*",
                             str(widget.properties.get("text") or "")))


def _labels_itself(registry, widget) -> bool:
    """True when the widget draws its own name or unit, so a heading over it
    says it twice (a gauge's caption, a speed arc's unit)."""
    definition = registry.get(widget.type) if registry is not None else None
    if definition is None:
        return False
    return any(key in definition.properties for key in ("caption", "label", "title", "unit", "units"))


def _fit(registry, widget, w, h):
    """The largest box of the widget's proportion inside w x h."""
    from . import compiler as c
    aspect = c._aspect(registry, widget)
    if w / max(1.0, h) > aspect:
        return h * aspect, h
    return w, w / aspect


def _set(widget, x, y, w, h) -> None:
    widget.geometry.update({"x": int(round(x)), "y": int(round(y)),
                            "width": int(round(max(1, w))), "height": int(round(max(1, h)))})
    widget.children = list(widget.children)


def _need(registry, section, width, tokens) -> float:
    """The height a framed section's card asks for at `width`."""
    from . import compiler as c
    inner = max(1.0, width - 2 * tokens.pad)
    total = 2 * tokens.pad + (tokens.card_title if section.title else 0)
    if _bar_rows(section):
        return total + len(section.widgets) * _bar_row_h(tokens) + tokens.gap * (len(section.widgets) - 1)
    bands = c._bands(registry, section.widgets)
    for index, (kind, widgets) in enumerate(bands):
        natural = c._natural(registry, kind, widgets, inner, tokens)
        if natural is None:
            # Faces side by side across the card, each at its proportion,
            # no taller than they are drawn for.
            per = (inner - tokens.gap * (len(widgets) - 1)) / len(widgets)
            natural = max(min(per / c._aspect(registry, w), c._design(registry, w)[1])
                          for w in widgets)
        total += natural + (tokens.gap if index else 0)
    return total


def _bar_rows(section) -> bool:
    """True when the section is bars drawn lying down, one row each."""
    return bool(section.widgets) and all(
        w.type == "ShEngineBar" and str(w.properties.get("orientation") or "") == "horizontal"
        for w in section.widgets)


def _bar_row_h(tokens) -> float:
    return tokens.label_font * 2.4


def _water_fill(needs, room):
    """Share `room` among `needs`: the smallest are met in full while the
    rest share what is left evenly; spare room goes in proportion to need."""
    if sum(needs) <= room:
        scale = room / max(1.0, sum(needs))
        return [n * scale for n in needs]
    given = [0.0] * len(needs)
    left, open_ = room, sorted(range(len(needs)), key=lambda i: needs[i])
    while open_:
        level = left / len(open_)
        i = open_[0]
        if needs[i] <= level:
            given[i] = needs[i]
            left -= needs[i]
            open_.pop(0)
            continue
        for j in open_:
            given[j] = level
        break
    return given


def _shares(total, needs, gap, floor=0.0):
    """Split `total` (less the gaps) in proportion to `needs`."""
    if not needs:
        return []
    room = total - gap * (len(needs) - 1)
    needs = [max(n, floor) for n in needs]
    scale = room / max(1.0, sum(needs))
    return [n * scale for n in needs]


# -- the strip -----------------------------------------------------------------

def _strip(project, registry, title, items, tokens, width, report):
    """The status strip across the top: its chrome and the planned items placed."""
    from . import compiler as c
    out = []
    x0, y0 = tokens.margin, tokens.margin
    x1 = width - tokens.margin
    h = tokens.header
    strip_props = {"color": c._theme(project, "card"), "borderColor": c._theme(project, "border"),
                   "borderWidth": 1, "radius": tokens.radius}
    out.append(c._new(project, "Rectangle", "topStrip",
                      {"x": x0, "y": y0, "width": x1 - x0, "height": h}, strip_props))
    clock = next((w for w in items if _is_clock(w)), None)
    for widget in items:
        # A header reading's unit is its binding's or none, never the kit's
        # sample unit (ShDataField draws "KTS" by default).
        definition = registry.get(widget.type) if registry is not None else None
        if definition is not None and widget is not clock:
            c._explicit_unit(definition, widget)
    left = [w for w in items if w is not clock and w.properties.get(c.SIDE_MARK) == "left"]
    right = [w for w in items if w is not clock and w not in left]
    placed = []
    clock_left = clock_right = width / 2.0
    if clock is not None:
        size = int(round(h * 0.66))
        text = str(clock.properties.get("text") or "") or "12:00"
        cw = max(len(text), 5) * size * 0.62 + 2 * tokens.pad
        line = size * 1.4
        clock.properties.update({"fontSize": size, "bold": False,
                                 "color": c._theme(project, "foreground"),
                                 "horizontalAlignment": "Text.AlignHCenter",
                                 "verticalAlignment": "Text.AlignVCenter", "wrapMode": "Text.NoWrap"})
        if not str(clock.properties.get("text") or "").strip():
            clock.properties["text"] = text
        clock_left, clock_right = (width - cw) / 2.0, (width + cw) / 2.0
        # The clock sits on a tab that hangs a little below the strip, as
        # the picture's does; the tab stays inside the gap above the body.
        tab_w = cw + 2 * tokens.gap
        out.append(c._new(project, "Rectangle", "clockTab",
                          {"x": (width - tab_w) / 2.0, "y": y0, "width": tab_w,
                           "height": h + tokens.gap * 0.6}, strip_props))
        _set(clock, clock_left, y0 + (h - line) / 2.0 + tokens.gap * 0.3, cw, line)
        placed.append(clock)

    def lamp(widget, x, towards_right):
        """A lamp and its caption; returns the edge reached."""
        label = c._lamp_label(widget)
        if widget.type == "ShTelltale":
            widget.properties[c.LAMP_LABEL_MARK] = label
            widget.properties["label"] = ""
        dot = 16 if widget.type == "ShStatDot" else 28
        label_w = max(32, len(label) * tokens.label_font * 0.62)
        if towards_right:
            _set(widget, x, y0 + (h - dot) / 2.0, dot, dot)
            out.append(c._text(project, f"{widget.id}Label", (x + dot + 6, y0, label_w, h), label,
                               tokens.label_font, c._theme(project, "mutedForeground")))
            return x + dot + 6 + label_w
        out.append(c._text(project, f"{widget.id}Label", (x - label_w, y0, label_w, h), label,
                           tokens.label_font, c._theme(project, "mutedForeground")))
        x -= label_w + 6 + dot
        _set(widget, x, y0 + (h - dot) / 2.0, dot, dot)
        return x

    def field_w(widget, design_w, ih):
        """A header reading is as wide as its text, never wider than its
        design: at the kit's 150 px a driver's name and the outside
        temperature left no room beside the clock."""
        if widget.type != "ShDataField":
            return design_w
        props = widget.properties
        label = str(props.get("label", "") or "")
        value = str(props.get("value", "") or "") + str(props.get("units", "") or "")
        side = props.get("stacked") is False
        label_w = len(label) * tokens.label_font * 0.62
        value_w = len(value) * ih * 0.42 * 0.62
        need = (label_w + 8 + value_w) if side else max(label_w, value_w)
        return min(design_w, max(48.0, need + 12))

    def other(widget, x, towards_right):
        design_w, design_h = c._design(registry, widget)
        definition = registry.get(widget.type) if registry is not None else None
        if design_h > h - 8 and widget.type == "ShDataField" and definition is not None \
                and "stacked" in definition.properties:
            # A strip too short for a label over its value: side by side.
            widget.properties["stacked"] = False
            design_h = h - 8
        ih = min(design_h, h - 8)
        iw = design_w * ih / float(design_h) if design_h > h - 8 else design_w
        iw = field_w(widget, iw, ih)
        if not towards_right:
            x -= iw
        _set(widget, x, y0 + (h - ih) / 2.0, iw, ih)
        return x + iw if towards_right else x

    def span(widget):
        """How wide an item is drawn in the strip (as lamp/other place it)."""
        if widget.type in _LAMPS:
            dot = 16 if widget.type == "ShStatDot" else 28
            return dot + 6 + max(32, len(c._lamp_label(widget)) * tokens.label_font * 0.62)
        design_w, design_h = c._design(registry, widget)
        if design_h > h - 8 and widget.type == "ShDataField":
            return field_w(widget, design_w, h - 8)   # side by side, no taller than the strip
        ih = min(design_h, h - 8)
        return field_w(widget, design_w * ih / float(design_h) if design_h > h - 8 else design_w, ih)

    # The clock's tab is the strip's middle: the right-hand items fill from
    # the right edge towards it and never into it; one that would reach it
    # goes to the left half after the lamps there, or stays (noted) when
    # neither half has room.
    stop = clock_right + tokens.gap if clock is not None else x0
    end = x1 - tokens.pad
    keep, moved = [], []
    for widget in reversed(right):
        need = span(widget)
        if clock is not None and end - need < stop:
            moved.append(widget)
            continue
        keep.append(widget)
        end -= need + tokens.gap
    x = x0 + tokens.pad
    limit = clock_left - tokens.gap
    for widget in left + list(reversed(moved)):
        if widget in moved and x + span(widget) > limit:
            keep.append(widget)
            report.notes.append(f"{widget.id}: the status strip is full; it overlaps the clock")
            continue
        x = (lamp if widget.type in _LAMPS else other)(widget, x, True) + tokens.gap
        placed.append(widget)
    end = x1 - tokens.pad
    for widget in keep:
        end = (lamp if widget.type in _LAMPS else other)(widget, end, False) - tokens.gap
        placed.append(widget)
    # The title: in the strip's left end when it is free, small after the
    # left items when there is room before the clock, else left off -- a
    # picture's status strip has no title, and the clock is what it leads with.
    if title:
        room_end = limit if clock is not None else end
        small = int(round(tokens.title_font * 0.7))
        for size in ((small,) if left else (tokens.title_font, small)):
            need = len(title) * size * 0.62
            if x + need <= room_end:
                heading = c._text(project, "screenTitle", (x, y0, need + 4, h), title, size,
                                  c._theme(project, "mutedForeground") if left else
                                  c._theme(project, "foreground"), bold=True)
                heading.properties[c.SECTION_MARK] = "|title"
                out.append(heading)
                break
        else:
            report.notes.append(f"title '{title}' left off: the strip is full")
    return out + placed


# -- the body ------------------------------------------------------------------

def _frameless(card):
    card.properties.update({"color": CLEAR, "borderColor": CLEAR, "borderWidth": 1})


def _accent_card(card, accent, tokens):
    if not accent:
        return
    card.properties["borderColor"] = accent
    for child in card.children:
        # The heading only: a lamp's caption keeps the foreground colour.
        if child.type == "Text" and child.properties.get("_compiledChrome") \
                and re.search(r"Heading\d*$", child.id or ""):
            child.properties["color"] = accent


#: Bars: a lone one is drawn at a bar's height, not stretched to its card.
_BARS = ("ShSegmentBar", "ShProgress", "ShEngineBar", "ShTractionBar")


def _captions(section) -> list:
    """Plain text in a section that holds instruments: words printed beside
    them in the picture ("x1000", "7350 t max", "Thermal/Health"). They are
    captions, not content to lay out between the instruments."""
    notes = [w for w in section.widgets if w.type == "Text" and not w.bindings and not w.actions]
    return notes if len(notes) < len(section.widgets) else []


def _section_card(project, registry, section, rect, tokens, framed, report):
    """One section in its rect: a card (framed) or the widgets on the glass."""
    from . import compiler as c
    x, y, w, h = rect
    notes = _captions(section)
    if notes:
        # The instruments keep the section; the captions get a band under
        # them, small and muted. Laid out with the instruments, three lines of
        # a picture's printed text shrank an RPM dial to a thumbnail.
        line = tokens.label_font * 1.5
        band = min(len(notes) * line, h * 0.35)
        # Lines that do not fit at the label size are drawn smaller, never
        # on top of each other.
        font = max(8, min(tokens.label_font, int(band / len(notes) / 1.3)))
        content = dataclasses.replace(section, widgets=[wd for wd in section.widgets if wd not in notes])
        card = _section_card(project, registry, content, (x, y, w, h - band), tokens, framed, report)
        card.geometry["height"] = h
        pad = tokens.pad if framed else max(4, tokens.gap // 2)
        each = band / len(notes)
        for index, note in enumerate(notes):
            note.geometry.update({"x": pad, "y": int(round(h - band - pad / 2.0 + index * each)),
                                  "width": int(w - 2 * pad), "height": int(each)})
            note.properties.update({"fontSize": int(font), "bold": False,
                                    "color": c._theme(project, "mutedForeground"),
                                    "horizontalAlignment": "Text.AlignHCenter",
                                    "verticalAlignment": "Text.AlignVCenter",
                                    "wrapMode": "Text.NoWrap"})
            note.children = list(note.children)
            card.children.append(note)
        return card
    lone = section.widgets[0] if len(section.widgets) == 1 else None
    pictures = [wd for wd in section.widgets if wd.type == "Image"]
    heading = section.title
    if not framed and (section.role == "hero" or pictures or
                       (lone is not None and _labels_itself(registry, lone))):
        # On the glass a lone instrument names itself, and a picture is the
        # subject: a heading over either only crowds it.
        heading = ""
    if lone is not None and not heading and lone.type == "ShClusterGauge" \
            and not str(lone.properties.get("caption") or "").strip() and section.title:
        lone.properties["caption"] = section.title
    built = dataclasses.replace(section, title=heading)
    card = c._card(project, registry, built, rect, tokens)
    # A frameless section has no frame to keep its content off: half a gap
    # around it is enough to keep it off its neighbours.
    pad = tokens.pad if framed else max(4, tokens.gap // 2)
    top = pad + (tokens.card_title if heading else 0)
    inner = (pad, top, w - 2 * pad, h - top - pad)
    kind = c.kind_of(registry, lone) if lone is not None else ""
    if lone is not None and (kind == c.FACE or lone.type == "Image" or
                             min(c._design(registry, lone)) >= 200):
        # One instrument fills its region at its own proportion.
        if lone.type == "Image":
            fw, fh = inner[2], inner[3]
        else:
            fw, fh = _fit(registry, lone, inner[2], inner[3])
        _set(lone, inner[0] + (inner[2] - fw) / 2.0, inner[1] + (inner[3] - fh) / 2.0, fw, fh)
    elif pictures and len(pictures) < len(section.widgets):
        _picture_with_readings(project, registry, card, pictures, section, inner, tokens)
    elif not framed and _face_with_readings(registry, section):
        # A dial with its readings (speed with pitch and roll): the readings
        # in a row above it, the dial as large as the rest allows -- left to
        # the tile layout it shrank to a thumbnail beside two numbers.
        faces = [wd for wd in section.widgets if _is_dial(registry, wd)]
        _picture_with_readings(project, registry, card, faces, section, inner, tokens, fit=True)
    elif _bar_rows(section):
        # Bars lying down, one row each across the card (a picture's vitals).
        rows = _shares(inner[3], [1.0] * len(section.widgets), tokens.gap)
        row_h = min(rows[0], _bar_row_h(tokens) * 1.4)
        used = row_h * len(rows) + tokens.gap * (len(rows) - 1)
        y0 = inner[1] + (inner[3] - used) / 2.0
        for index, widget in enumerate(section.widgets):
            _set(widget, inner[0], y0 + index * (row_h + tokens.gap), inner[2], row_h)
    elif lone is not None and lone.type in _BARS:
        # A lone bar keeps a bar's height, centred: stretched to its card's
        # height a fuel bar's cells became thin vertical lines.
        bar_h = min(inner[3], c._design(registry, lone)[1] * 1.3)
        _set(lone, inner[0], inner[1] + (inner[3] - bar_h) / 2.0, inner[2], bar_h)
    if not framed:
        _frameless(card)
    _accent_card(card, section.accent if framed else "", tokens)
    report.sections.append((section.title, section.role, tuple(int(round(v)) for v in rect)))
    return card


#: Small readings that ride above a dial or a picture in their section.
_READINGS = ("ShDataField", "ShValueTile", "ShNumDisplay", "ShAutoReadout", "Text",
             "ShStatDot", "ShTelltale")


def _is_dial(registry, widget) -> bool:
    """A round instrument: a face, or a speed arc (the Rail kit's speedometer,
    which the compiler files as a tile)."""
    from . import compiler as c
    return widget.type == "ShSpeedArc" or c.kind_of(registry, widget) == c.FACE


def _face_with_readings(registry, section) -> bool:
    """One dial and only small readings beside it."""
    faces = [wd for wd in section.widgets if _is_dial(registry, wd)]
    rest = [wd for wd in section.widgets if wd not in faces]
    return len(faces) == 1 and bool(rest) and all(wd.type in _READINGS for wd in rest)


def _picture_with_readings(project, registry, card, pictures, section, inner, tokens, fit=False):
    """A picture (or, with `fit`, a dial) with its readings: the readings in
    a row above it (where a picture's callouts sit), the picture filling the
    rest -- a dial at its own proportion, centred."""
    from . import compiler as c
    rest = [wd for wd in section.widgets if wd not in pictures]
    ix, iy, iw, ih = inner
    dials = [] if fit else [wd for wd in rest if _is_dial(registry, wd)]
    if dials:
        # A dial grouped with the picture (a speedometer beside the truck)
        # is not a small reading: it takes a column of its own at the left,
        # and the picture with its readings the rest.
        col = min(iw * 0.4, ih / max(1, len(dials)))
        each = (ih - tokens.gap * (len(dials) - 1)) / len(dials)
        for index, dial in enumerate(dials):
            fw, fh = _fit(registry, dial, col, each)
            _set(dial, ix + (col - fw) / 2.0, iy + index * (each + tokens.gap) + (each - fh) / 2.0, fw, fh)
        rest = [wd for wd in rest if wd not in dials]
        ix, iw = ix + col + tokens.gap, iw - col - tokens.gap
        if not rest:
            for index, picture in enumerate(pictures):
                _set(picture, ix, iy, iw, ih)
            return
    # Drop the readings layout_content made and lay them out in one row.
    row_h = max(c._design(registry, wd)[1] for wd in rest) * 1.1
    row_h = min(row_h, ih * 0.3)
    cell = (iw - tokens.gap * (len(rest) - 1)) / len(rest)
    for index, widget in enumerate(rest):
        fw, fh = c._fit_in_cell(registry, widget, cell, row_h)
        _set(widget, ix + index * (cell + tokens.gap) + (cell - fw) / 2.0, iy + (row_h - fh) / 2.0, fw, fh)
    # Labels layout_content drew for them (lamp captions) no longer line up.
    card.children[:] = [ch for ch in card.children
                        if not (ch.properties.get(c.CHROME_MARK) and ch.type == "Text"
                                and any(ch.id.startswith(r.id) for r in rest))]
    top = iy + row_h + tokens.gap
    each = (ih - row_h - tokens.gap - tokens.gap * (len(pictures) - 1)) / len(pictures)
    for index, picture in enumerate(pictures):
        if fit:
            fw, fh = _fit(registry, picture, iw, each)
            _set(picture, ix + (iw - fw) / 2.0, top + index * (each + tokens.gap) + (each - fh) / 2.0, fw, fh)
        else:
            _set(picture, ix, top + index * (each + tokens.gap), iw, each)


def _rail_card(project, registry, section, rect, tokens, report):
    """The rail: a rounded pill at the left edge, as tall as its content."""
    from . import compiler as c
    x, y, w, h = rect
    pad = max(6, int(round(w * 0.12)))
    inner_w = w - 2 * pad
    widgets = section.widgets
    needs = []
    for widget in widgets:
        definition = registry.get(widget.type) if registry is not None else None
        if widget.type == "ShGearIndicator":
            if definition is not None and "orientation" in definition.properties \
                    and not widget.properties.get("orientation"):
                widget.properties["orientation"] = "vertical"
        if widget.type == "ShGearIndicator" and widget.properties.get("orientation") == "vertical":
            # A selector standing up: a square or so per gear.
            gears = [g for g in str(widget.properties.get("gears") or "P,R,N,D").split(",") if g.strip()]
            needs.append(inner_w * 0.95 * max(3, len(gears)))
        else:
            needs.append(inner_w / max(0.2, c._aspect(registry, widget)))
    want = sum(needs) + tokens.gap * (len(widgets) - 1) + 2 * pad
    ph = min(h, want)
    py = y + (h - ph) / 2.0
    pill = c._new(project, "ShCard", (c._slug(section.title) or "rail") + "Card",
                  {"x": x, "y": py, "width": w, "height": ph},
                  {"color": c._theme(project, "card"),
                   "borderColor": section.accent or c._theme(project, "border"),
                   "borderWidth": 1, "radius": int(w // 2)})
    sizes = _shares(ph - 2 * pad, needs, tokens.gap)
    top = pad
    for widget, size in zip(widgets, sizes):
        _set(widget, pad, top, inner_w, size)
        pill.children.append(widget)
        top += size + tokens.gap
    report.sections.append((section.title, section.role, (int(x), int(py), int(w), int(ph))))
    return pill


def _stack(project, registry, sections, rect, tokens, framed, report, needs=None):
    """Sections one under another in `rect`, in plan order."""
    x, y, w, h = rect
    if needs is None:
        # Cards: each keeps its chrome (heading and padding) whole, and the
        # room left is shared by what their content asks for, water-filled:
        # a card that asks for little gets it all, and the ones that ask for
        # more share the rest evenly. Scaling every card by one factor
        # starves the card of small faces (a compass beside an attitude
        # indicator) to feed the tall ones, which shrink without harm.
        chrome = [2 * tokens.pad + (tokens.card_title if s.title else 0) for s in sections]
        content = [max(1.0, _need(registry, s, w, tokens) - c) for s, c in zip(sections, chrome)]
        room = max(1.0, h - tokens.gap * (len(sections) - 1) - sum(chrome))
        given = _water_fill(content, room)
        heights = [c + v for c, v in zip(chrome, given)]
    else:
        heights = _shares(h, needs, tokens.gap, floor=max(needs) * 0.3 if needs else 0)
    out = []
    for section, sh in zip(sections, heights):
        out.append(_section_card(project, registry, section, (x, y, w, sh), tokens, framed, report))
        y += sh + tokens.gap
    return out


def _row(project, registry, sections, rect, tokens, framed, report):
    """Sections side by side in `rect`, in plan order."""
    from . import compiler as c
    x, y, w, h = rect
    weights = [max(1.0, c._section_weight(registry, s)) ** 0.5 for s in sections]
    widths = _shares(w, weights, tokens.gap, floor=max(weights) * 0.5)
    out = []
    for section, sw in zip(sections, widths):
        out.append(_section_card(project, registry, section, (x, y, sw, h), tokens, framed, report))
        x += sw + tokens.gap
    return out


def compile_reference(project, page, registry, sections, title, header_widgets, report,
                      width, height):
    """Lay `page` out by its sections' regions; replaces page.widgets in place."""
    from . import compiler as c
    tokens = c.tokens_for(width, height)
    sections = [s for s in sections if s.widgets]
    for section in sections:
        c._prepare(registry, section, report.notes)
        _apply_accent(registry, section)
        for widget in section.widgets:
            # A speed arc with no target in the plan is a vehicle's
            # speedometer, not a cab's: the kit's sample "TARGET: 60" flag
            # would be a target nobody set.
            if widget.type == "ShSpeedArc" and "target" not in widget.properties \
                    and "target" not in (widget.bindings or {}) and "showTarget" not in widget.properties:
                widget.properties["showTarget"] = False
        if section.region == "right" and any(w.type == "ShEngineBar" for w in section.widgets) and all(
                w.type == "ShEngineBar" or w in _captions(section) for w in section.widgets):
            # In a column of cards, bars lie down, one row each, when the
            # kit's bar can (a picture's vitals are drawn that way).
            for widget in section.widgets:
                definition = registry.get(widget.type) if registry is not None else None
                if definition is not None and "orientation" in definition.properties \
                        and not widget.properties.get("orientation"):
                    widget.properties["orientation"] = "horizontal"
    by_region = {name: [] for name in c.REGIONS}
    for section in sections:
        bucket = by_region[section.region if section.region in c.REGIONS else "center"]
        plain = section.widgets and all(w.type == "Text" and not w.bindings and not w.actions
                                        for w in section.widgets)
        if plain and bucket:
            # Words printed under an instrument in the picture, planned as a
            # section of their own: they caption the section before them.
            bucket[-1] = dataclasses.replace(bucket[-1], widgets=bucket[-1].widgets + section.widgets)
            continue
        bucket.append(section)

    widgets = []
    strip_items = list(header_widgets or []) + [w for s in by_region["top"] for w in s.widgets]
    has_strip = bool(title or strip_items)
    for section in by_region["top"]:
        report.sections.append((section.title, section.role,
                                (tokens.margin, tokens.margin, width - 2 * tokens.margin, tokens.header)))
    if has_strip:
        widgets += _strip(project, registry, title, strip_items, tokens, width, report)

    m, gap = tokens.margin, tokens.gap
    bx0, bx1 = m, width - m
    by0 = m + (tokens.header + gap if has_strip else 0)
    by1 = height - m
    body_w, body_h = bx1 - bx0, by1 - by0
    rail, left, center = by_region["rail"], by_region["left"], by_region["center"]
    right, bottom = by_region["right"], by_region["bottom"]

    right_w = round(body_w * RIGHT_SHARE) if right else 0
    rail_w = max(44, round(width * RAIL_SHARE)) if rail else 0
    main_x1 = bx1 - (right_w + gap if right else 0)
    upper = bool(rail or left or center)
    if bottom and upper:
        bottom_h = round(body_h * BOTTOM_SHARE)
    elif bottom:
        bottom_h = body_h
    else:
        bottom_h = 0
    upper_y1 = by1 - (bottom_h + gap if bottom else 0)
    upper_h = upper_y1 - by0

    if right:
        # A column of several cards: tighter card chrome, so the readings
        # get the height (the picture's cards have slim headings).
        column = dataclasses.replace(tokens, pad=max(8, tokens.pad * 3 // 4),
                                     card_title=int(round(tokens.card_title_font * 1.6)))
        widgets += _stack(project, registry, right, (bx1 - right_w, by0, right_w, body_h),
                          column, True, report)
    if rail:
        rail_sizes = _shares(upper_h if upper_h > 0 else body_h,
                             [len(s.widgets) for s in rail], gap)
        ry = by0
        for section, size in zip(rail, rail_sizes):
            widgets.append(_rail_card(project, registry, section, (bx0, ry, rail_w, size), tokens, report))
            ry += size + gap
    mx0 = bx0 + (rail_w + gap if rail else 0)
    span = main_x1 - mx0
    if left and center:
        left_w = round(span * LEFT_SHARE)
        parts = ((left, (mx0, by0, left_w, upper_h)),
                 (center, (mx0 + left_w + gap, by0, span - left_w - gap, upper_h)))
    elif left or center:
        parts = (((left or center), (mx0, by0, span, upper_h)),)
    else:
        parts = ()
    for group, rect in parts:
        weights = [c._section_weight(registry, s) ** 0.5 for s in group]
        # Dials and pictures stacked in one column are shown alike: by role
        # weight a "hero" speed arc took the column and the RPM dial under it
        # was left a thumbnail.
        top = max(weights) if weights else 1.0
        weights = [top if any(_is_dial(registry, wd) or wd.type in ("Image", "ShAnimatedImage")
                              for wd in s.widgets) else wgt for s, wgt in zip(group, weights)]
        widgets += _stack(project, registry, group, rect, tokens, False, report, needs=weights)
    if bottom:
        # The row runs under the rail too, as the picture's dials do.
        widgets += _row(project, registry, bottom, (bx0, by1 - bottom_h, main_x1 - bx0, bottom_h),
                        tokens, False, report)

    page.widgets[:] = widgets
    report.layout = FAMILY_NAME
    c._tidy_scales(page, registry, report.notes)
    return report


#: Register this family when the module is imported. families._builtin()
#: imports cab.py first, so a cab display is still found first.
try:
    from . import families as _families
    _families.register(FAMILY_NAME, _applies, compile_reference)
except Exception:  # pragma: no cover - import guard for early callers
    pass
