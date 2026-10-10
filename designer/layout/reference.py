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

A plant overview (SCADA) is drawn differently, and three plan shapes say so:
- a clock that shows a date, or none at all, with a title: the title sits
  in a box in the middle of the strip and the clock joins the right end;
- bottom sections that are bars across the screen (a status banner, a row
  of navigation buttons): full-width bands under everything, the right
  column included, each only as tall as a banner or a button;
- a card of reading lines (ShProcessValue, ShDataField side by side): one
  row each, as a picture's process cards are.

Like the rest of the compiler this never reads model geometry: the regions,
accents and side marks are on the widgets, so a recompile ("Tidy up", Size on
screen) rebuilds the same screen.
"""
from __future__ import annotations

import dataclasses
import math
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
#: The types a reference's pictures are cut into.
_PICTURES = ("Image", "ShAnimatedImage")
#: Widgets drawn as one line each in a card: a reading line of a process card.
_ROW_TYPES = ("ShProcessValue", "ShStatusRow")
#: Widgets that are a card of their own (a title bar, a tile): alone in a
#: section they fill it, with no card or heading around them.
_SELF_FRAMED = ("ShKpiTile", "ShAlarmTable", "ShStatusCard")
#: A date in a clock's text ("12-10-2026", "2026/10/12").
_DATE_RE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}"
                      r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{2,4}"         # 26 Apr 2024
                      r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}")        # Apr 26, 2024


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
    if _reading_rows(section):
        return total + len(section.widgets) * _reading_row_h(tokens) \
            + tokens.gap * 0.5 * (len(section.widgets) - 1)
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


def _reading_rows(section) -> bool:
    """True when the section is reading lines, one row each (a process
    card's "Hot Blast Temp: [1185] °C")."""
    return bool(section.widgets) and all(
        w.type in _ROW_TYPES or (w.type == "ShDataField" and w.properties.get("stacked") is False)
        for w in section.widgets)


def _reading_row_h(tokens) -> float:
    return max(24.0, tokens.label_font * 2.0)


def _band_kind(section) -> str:
    """"banner" for a status bar across the screen, "buttons" for a row of
    navigation buttons, "" for anything else."""
    widgets = section.widgets
    if widgets and len(widgets) <= 3 and all(w.type == "ShAnnunciator" for w in widgets):
        return "banner"
    if len(widgets) >= 3 and all(w.type in ("ShButton", "ShIconTile") for w in widgets):
        return "buttons"
    return ""


def _band_h(kind, tokens) -> float:
    if kind == "banner":
        return max(28.0, tokens.label_font * 2.5)
    return max(float(tokens.control_h), tokens.label_font * 3.4)


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

def _strip(project, registry, title, items, tokens, width, report, height=0):
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
    # A plant overview's strip leads with its title in a box in the middle;
    # its clock shows the date too and is one more reading at the right end.
    boxed = bool(title) and (clock is None or bool(_DATE_RE.search(str(clock.properties.get("text") or ""))))
    if boxed:
        # The title is the box's: a header Text with the same words (the
        # flash model wrote both) would print it twice.
        same = (lambda text: re.sub(r"[^a-z0-9]+", "", str(text or "").lower()))
        items = [w for w in items if not (w.type == "Text" and w is not clock
                                          and same(w.properties.get("text")) == same(title))]
    dated = clock if boxed else None
    if boxed and clock is not None:
        clock.properties.update({"fontSize": int(tokens.label_font + 1), "bold": False,
                                 "color": c._theme(project, "foreground"),
                                 "horizontalAlignment": "Text.AlignHCenter",
                                 "verticalAlignment": "Text.AlignVCenter", "wrapMode": "Text.NoWrap"})
        clock = None
    for widget in items:
        # A header reading's unit is its binding's or none, never the kit's
        # sample unit (ShDataField draws "KTS" by default).
        definition = registry.get(widget.type) if registry is not None else None
        if definition is not None and widget is not clock:
            c._explicit_unit(definition, widget)
    left = [w for w in items if w is not clock and w.properties.get(c.SIDE_MARK) == "left"]
    right = [w for w in items if w is not clock and w not in left]
    # The date goes under the status reading beside it, two lines in one
    # column at the right end, as a plant overview's strip draws them.
    if boxed:
        # The strip's left end is the plant's: its name and logo lead, before
        # the title box, and the readings (status, alarm, date) follow it,
        # whatever "side" the plan wrote -- Ornith put the status and the
        # alarm at the left, and the title box split them from the date.
        everything = left + right
        left = [w for w in everything if w is not dated and (w.type == "Text" or w.type in _PICTURES)]
        right = [w for w in everything if w not in left]
    partner = None
    if dated is not None and dated in right:
        # The status line, not an alarm lamp: paired with the date, a lamp
        # left the status capped at its design width and cut off.
        partner = next((w for w in right if w.type == "ShDataField"), None) or next(
            (w for w in right if w.type == "ShAnnunciator"
             and len(str(w.properties.get("text") or "")) > 8), None)
        if partner is not None:
            right.remove(dated)
    if boxed:
        for widget in left:
            text = str(widget.properties.get("text") or "")
            if widget.type == "Text" and "\n" not in text and len(text) > 14 and " " in text:
                # A plant's name on two lines, as it is printed beside its logo.
                mid = len(text) / 2.0
                cut_at = min((i for i, ch in enumerate(text) if ch == " "), key=lambda i: abs(i - mid))
                widget.properties["text"] = text[:cut_at] + "\n" + text[cut_at + 1:]
                widget.properties.setdefault("bold", True)
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

    def text_size(widget):
        return int(widget.properties.get("fontSize") or tokens.label_font + 1)

    def field_w(widget, design_w, ih):
        """A header reading is as wide as its text, never wider than its
        design: at the kit's 150 px a driver's name and the outside
        temperature left no room beside the clock."""
        if widget.type == "Text":
            lines = str(widget.properties.get("text") or "").split("\n")
            per = 0.68 if widget.properties.get("bold") else 0.6     # capitals in bold run wide
            return max(len(line) for line in lines) * text_size(widget) * per + 8
        if widget.type == "ShAnnunciator":
            return len(str(widget.properties.get("text") or "")) * tokens.label_font * 0.62 + 20
        if widget.type in ("Image", "ShAnimatedImage") and widget.properties.get(c.CROP_MARK):
            # A logo cut from the picture keeps the crop's proportion (the
            # reference is drawn at about the screen's).
            left_, top_, right_, bottom_ = widget.properties[c.CROP_MARK]
            aspect = (right_ - left_) / max(0.01, bottom_ - top_) * width / max(1.0, float(height))
            return ih * max(0.5, min(4.0, aspect))
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
        if widget.type == "Text":
            # A name or the date: one line, as wide as its words.
            size = text_size(widget)
            widget.properties.update({"fontSize": size, "verticalAlignment": "Text.AlignVCenter",
                                      "wrapMode": "Text.NoWrap"})
            widget.properties.setdefault("color", c._theme(project, "foreground"))
            lines = str(widget.properties.get("text") or "").count("\n") + 1
            tw, th = field_w(widget, 0, 0), size * 1.3 * lines
            if not towards_right:
                x -= tw
            _set(widget, x, y0 + (h - th) / 2.0, tw, th)
            return x + tw if towards_right else x
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

    def pair(widget, end):
        """The status reading over the date, right-aligned at `end`; returns
        the left edge reached."""
        col = max(span(widget, alone=True), field_w(dated, 0, 0))
        if widget.type == "ShDataField":
            # Side by side at the kit's sizes (a 12 px label, a 14 px
            # semibold value), not capped at its design width: capped,
            # "OPERATIONAL (ON-LINE)" was drawn as "OPERATIO".
            props = widget.properties
            value = str(props.get("value", "") or "") + str(props.get("units", "") or "")
            col = max(col, len(str(props.get("label", "") or "")) * 12 * 0.62 + 8
                      + len(value) * 14 * 0.72 + 14)
        x = end - col
        half = h / 2.0
        if widget.type == "ShDataField":
            widget.properties["stacked"] = False
        top_h = min(c._design(registry, widget)[1], half - 3)
        _set(widget, x, y0 + 3 + (half - 3 - top_h) / 2.0, col, top_h)
        size = text_size(dated)
        line = size * 1.3
        dated.properties["horizontalAlignment"] = "Text.AlignHCenter"
        _set(dated, x, y0 + half + (half - 3 - line) / 2.0, col, line)
        placed.append(dated)
        return x

    def span(widget, alone=False):
        """How wide an item is drawn in the strip (as lamp/other place it)."""
        if widget is partner and not alone:
            return max(span(widget, alone=True), field_w(dated, 0, 0))
        if widget.type == "Text":
            return field_w(widget, 0, 0)
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
        if widget is partner:
            end = pair(widget, end) - tokens.gap
        else:
            end = (lamp if widget.type in _LAMPS else other)(widget, end, False) - tokens.gap
        placed.append(widget)
    if partner is not None and dated not in placed:
        # Its status reading went elsewhere: the date stands on its own.
        end = other(dated, end, False) - tokens.gap
        placed.append(dated)
    if boxed:
        # The title box fills the strip between the two ends' items.
        left_end, right_end = x, end
        if right_end - left_end >= 120:
            inset = max(4, int(round(h * 0.1)))
            out.append(c._new(project, "Rectangle", "titleBox",
                              {"x": left_end, "y": y0 + inset, "width": right_end - left_end,
                               "height": h - 2 * inset},
                              {"color": c._theme(project, "background"),
                               "borderColor": c._theme(project, "border"), "borderWidth": 1,
                               "radius": max(4, tokens.radius // 2)}))
            room = right_end - left_end - 2 * tokens.pad
            size = int(max(11, min(tokens.title_font * 0.8, room / max(1, len(title) * 0.6))))
            heading = c._text(project, "screenTitle", (left_end, y0, right_end - left_end, h), title,
                              size, c._theme(project, "foreground"), bold=True,
                              align="Text.AlignHCenter")
            heading.properties[c.SECTION_MARK] = "|title"
            out.append(heading)
        else:
            report.notes.append(f"title '{title}' left off: the strip is full")
    # The title: in the strip's left end when it is free, small after the
    # left items when there is room before the clock, else left off -- a
    # picture's status strip has no title, and the clock is what it leads with.
    elif title:
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
    if lone is not None and lone.type in _SELF_FRAMED:
        # The tile or the table is the card: its own title bar names it.
        heading, framed = "", False
        if lone.type == "ShAlarmTable" and section.title and not str(lone.properties.get("title") or "").strip():
            lone.properties["title"] = section.title
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
    laid = True              # False when only c._card's layout placed them
    if lone is not None and lone.type in _SELF_FRAMED:
        _set(lone, 0, 0, w, h)
    elif lone is not None and (kind == c.FACE or lone.type == "Image" or
                             min(c._design(registry, lone)) >= 200):
        # One instrument fills its region at its own proportion.
        if lone.type == "Image":
            fw, fh = inner[2], inner[3]
        else:
            fw, fh = _fit(registry, lone, inner[2], inner[3])
        _set(lone, inner[0] + (inner[2] - fw) / 2.0, inner[1] + (inner[3] - fh) / 2.0, fw, fh)
    elif pictures and len(pictures) < len(section.widgets) and _overlays(section, pictures):
        _picture_overlays(project, registry, card, pictures[0], section, inner, tokens, report)
    elif pictures and len(pictures) < len(section.widgets):
        _picture_with_readings(project, registry, card, pictures, section, inner, tokens)
    elif not framed and _face_with_readings(registry, section):
        # A dial with its readings (speed with pitch and roll): the readings
        # in a row above it, the dial as large as the rest allows -- left to
        # the tile layout it shrank to a thumbnail beside two numbers.
        faces = [wd for wd in section.widgets if _is_dial(registry, wd)]
        _picture_with_readings(project, registry, card, faces, section, inner, tokens, fit=True)
    elif _reading_rows(section):
        # Reading lines, one row each, spread down the card at a line's
        # height: label, value box and unit read across, as the picture's.
        n = len(section.widgets)
        slot = inner[3] / n
        row_h = min(slot, _reading_row_h(tokens) * 1.25)
        for index, widget in enumerate(section.widgets):
            _set(widget, inner[0], inner[1] + index * slot + (slot - row_h) / 2.0, inner[2], row_h)
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
    else:
        laid = False
    missing = [wd for wd in section.widgets if not any(wd is ch for ch in card.children)]
    spill = [wd for wd in section.widgets if any(wd is ch for ch in card.children)
             and wd.geometry.get("y", 0) + wd.geometry.get("height", 0) > h + 2]
    if spill and not laid:
        # Placed below the card's foot (a control panel's buttons under its
        # setpoints): the same as left out.
        missing = section.widgets
    if missing and laid:
        card.children.extend(missing)
    elif missing:
        # The card's layout leaves out what does not fit: a KPI tile drawn
        # at the picture's 55 px kept its heading and lost its readings, and
        # the next recompile never saw them again. Nothing is lost: all of
        # them, in a grid that fits.
        _squeeze(project, registry, card, section, (x, y, w, h), tokens, pad, heading)
    if not framed:
        _frameless(card)
    _accent_card(card, section.accent if framed else "", tokens)
    report.sections.append((section.title, section.role, tuple(int(round(v)) for v in rect)))
    return card


def _overlays(section, pictures) -> list:
    """The section's readings that say where they sit on its picture (their
    own box inside the picture's crop): a process drawing's live values."""
    from . import compiler as c
    crop = pictures[0].properties.get(c.CROP_MARK) if len(pictures) == 1 else None
    if not crop:
        return []
    out = []
    for widget in section.widgets:
        spot = widget.properties.get(c.WIDGET_BOX_MARK)
        if widget in pictures or not spot:
            continue
        mid_x, mid_y = (spot[0] + spot[2]) / 2.0, (spot[1] + spot[3]) / 2.0
        if crop[0] <= mid_x <= crop[2] and crop[1] <= mid_y <= crop[3]:
            out.append(widget)
    return out


def _picture_overlays(project, registry, card, picture, section, inner, tokens, report=None):
    """The picture filling the card at its crop's proportion, each reading
    with a box laid over it where the picture draws it -- the live value
    over the printed one; readings without a box ride in a row above."""
    from . import compiler as c
    ix, iy, iw, ih = inner
    over = _overlays(section, [picture])
    rest = [wd for wd in section.widgets if wd is not picture and wd not in over]
    if len(rest) > 4:
        # The drawing prints them, and a row of twenty cells is noise.
        if report is not None:
            report.notes.append("left out, the picture prints them: " + ", ".join(wd.id for wd in rest))
        section.widgets[:] = [wd for wd in section.widgets if wd not in rest]
        rest = []
    for widget in over:
        if widget.type == "ShProcessValue":
            # Over the drawing it is the value box and its unit: the drawing
            # prints the label.
            widget.properties["label"] = ""
            widget.properties["trend"] = False
    if rest:
        row_h = min(ih * 0.2, max(c._design(registry, wd)[1] for wd in rest) * 1.1)
        cell = (iw - tokens.gap * (len(rest) - 1)) / len(rest)
        for index, widget in enumerate(rest):
            fw, fh = c._fit_in_cell(registry, widget, cell, row_h)
            _set(widget, ix + index * (cell + tokens.gap), iy, fw, fh)
        iy, ih = iy + row_h + tokens.gap, ih - row_h - tokens.gap
    l, t, r, b = picture.properties[c.CROP_MARK]
    # The reference is drawn at about the screen's proportions.
    aspect = (r - l) / max(0.01, b - t) * project.screen.width / max(1.0, float(project.screen.height))
    pw, ph = (ih * aspect, ih) if iw / max(1.0, ih) > aspect else (iw, iw / aspect)
    px, py = ix + (iw - pw) / 2.0, iy + (ih - ph) / 2.0
    _set(picture, px, py, pw, ph)
    picture.properties["fillMode"] = "Image.Stretch"     # the mapping below is exact
    sx, sy = pw / max(0.01, r - l), ph / max(0.01, b - t)
    for widget in over:
        spot = widget.properties[c.WIDGET_BOX_MARK]
        ww = max(48.0, (spot[2] - spot[0]) * sx)
        wh = max(18.0, (spot[3] - spot[1]) * sy)
        wx = min(max(px, px + (spot[0] - l) * sx), px + pw - ww)
        wy = min(max(py, py + (spot[1] - t) * sy), py + ph - wh)
        _set(widget, wx, wy, ww, wh)
    # The card's own chrome, then the picture, then what lies over it
    # (children paint in order); the captions the card layout drew for the
    # readings no longer line up with them.
    placed = [picture] + rest + over
    chrome = [ch for ch in card.children
              if not any(ch is wd for wd in placed)
              and not (ch.properties.get(c.CHROME_MARK) and ch.type == "Text"
                       and any(ch.id.startswith(wd.id) for wd in rest + over))]
    card.children[:] = chrome + placed


def _squeeze(project, registry, card, section, rect, tokens, pad, heading):
    """Every widget of the section in `card`, in a grid of the columns that
    suit them best; the heading goes when the card is too short for it."""
    from . import compiler as c
    x, y, w, h = rect
    keep = [ch for ch in card.children if ch.type == "Text" and ch.properties.get(c.CHROME_MARK)
            and re.search(r"Heading\d*$", ch.id or "")]
    top = pad + (tokens.card_title if keep else 0)
    if keep and h - top - pad < 22:
        keep, top = [], pad                     # no room for a heading and content
    card.children[:] = keep
    widgets = section.widgets
    iw, ih = max(1.0, w - 2 * pad), max(1.0, h - top - pad)
    aspects = [max(0.3, c._aspect(registry, wd)) for wd in widgets]
    want = sum(aspects) / len(aspects)
    best = None
    for cols in range(1, len(widgets) + 1):
        rows = -(-len(widgets) // cols)
        cell = (iw / cols) / (ih / rows)
        score = abs(math.log(cell / want))
        if best is None or score < best[0]:
            best = (score, cols, rows)
    _score, cols, rows = best
    gap = max(2.0, tokens.gap / 2.0)
    cw = (iw - gap * (cols - 1)) / cols
    rh = (ih - gap * (rows - 1)) / rows
    for index, widget in enumerate(widgets):
        r, col = divmod(index, cols)
        _set(widget, pad + col * (cw + gap), top + r * (rh + gap), cw, rh)
        card.children.append(widget)


#: Small readings that ride above a dial or a picture in their section.
_READINGS = ("ShDataField", "ShProcessValue", "ShValueTile", "ShNumDisplay", "ShAutoReadout", "Text",
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


def _row(project, registry, sections, rect, tokens, framed, report, span=None):
    """Sections side by side in `rect`, in plan order; with `span` (the
    picture's x extent the row covers) each at its box's place and width,
    as the picture spaces them (a payload dial under the truck, not beside
    the RPM dial)."""
    from . import compiler as c
    x, y, w, h = rect
    if span and all(s.box for s in sections):
        u0, u1 = span
        scale = w / max(0.05, u1 - u0)
        rects, edge = [], x
        for section in sorted(sections, key=lambda s: s.box[0]):
            sx = max(edge, x + (section.box[0] - u0) * scale)
            sw = min((section.box[2] - section.box[0]) * scale, x + w - sx)
            rects.append((section, sx, sw))
            edge = sx + sw + tokens.gap
        if all(sw >= 40 for _s, _x, sw in rects):
            # (A box too small or squeezed out: the plain row, nothing lost.)
            return [_section_card(project, registry, section, (sx, y, sw, h), tokens, framed, report)
                    for section, sx, sw in rects]
    weights = [max(1.0, c._section_weight(registry, s)) ** 0.5 for s in sections]
    widths = _shares(w, weights, tokens.gap, floor=max(weights) * 0.5)
    out = []
    for section, sw in zip(sections, widths):
        out.append(_section_card(project, registry, section, (x, y, sw, h), tokens, framed, report))
        x += sw + tokens.gap
    return out


def _union(sections):
    """The box around the sections' boxes, or None when one has none."""
    if not sections or not all(s.box for s in sections):
        return None
    return (min(s.box[0] for s in sections), min(s.box[1] for s in sections),
            max(s.box[2] for s in sections), max(s.box[3] for s in sections))


def _clamp(value, low, high):
    return max(low, min(high, value))


def _box_shares(rail, left, center, right, bottom) -> dict:
    """The picture's proportions from its blocks' boxes: the right column's
    share of the body's width, the rail's, the left column's share of left
    and center, the bottom row's share of the body's height. {} unless
    every body section has a box -- a guess for some of them would skew
    the rest."""
    body = list(rail) + list(left) + list(center) + list(right) + list(bottom)
    whole = _union(body)
    if whole is None or len(body) < 2:
        return {}
    width, height = whole[2] - whole[0], whole[3] - whole[1]
    if width < 0.2 or height < 0.2:
        return {}
    shares = {}
    if right:
        shares["right"] = _clamp((whole[2] - _union(right)[0]) / width, 0.16, 0.45)
    if rail:
        shares["rail"] = _clamp((_union(rail)[2] - whole[0]) / width, 0.04, 0.15)
    if left and center:
        lw = _union(left)[2] - _union(left)[0]
        cw = _union(center)[2] - _union(center)[0]
        shares["left"] = _clamp(lw / max(0.01, lw + cw), 0.2, 0.7)
    upper = _union(list(rail) + list(left) + list(center))
    if bottom and upper:
        bh = _union(bottom)[3] - _union(bottom)[1]
        uh = upper[3] - upper[1]
        shares["bottom"] = _clamp(bh / max(0.01, bh + uh), 0.2, 0.65)
    return shares


def _into_columns(left, center, bottom):
    """(left, center, bottom) with the bottom blocks that sit under one
    column moved into it, when the other column runs down beside the row.

    A haul truck's picture has the RPM dial at the lower left, as tall as
    the payload dial under the truck; laid as a row under both columns the
    payload was squeezed into a strip. Only with every box known.
    """
    lu, cu, bu = _union(left), _union(center), _union(bottom)
    if not (lu and cu and bu):
        return left, center, bottom
    band = bu[3] - bu[1]
    left, center, rest = list(left), list(center), []
    for section in bottom:
        mid = (section.box[0] + section.box[2]) / 2.0
        if cu[0] <= mid <= cu[2] and lu[3] > bu[1] + 0.3 * band:
            center.append(section)        # left runs down beside it
        elif lu[0] <= mid <= lu[2] and cu[3] > bu[1] + 0.3 * band:
            left.append(section)
        else:
            rest.append(section)
    key = (lambda s: s.box[1])
    return sorted(left, key=key), sorted(center, key=key), rest


def _box_heights(sections):
    """The sections' heights in the picture, for a column stacked in its
    proportions; None unless every one has a box."""
    if not sections or not all(s.box for s in sections):
        return None
    # In thousandths: _shares takes weights of 1 and up (it divides by at
    # least 1), and fractions squeezed every column to about 70 %.
    return [1000.0 * max(0.02, s.box[3] - s.box[1]) for s in sections]


def _row_span(rail, left, center, bottom):
    """The picture's x extent a bottom row covers: from the body's left edge
    to the right end of left, center and the row itself."""
    whole = _union(list(rail) + list(left) + list(center) + list(bottom))
    return (whole[0], whole[2]) if whole else None


def _band(project, registry, section, rect, tokens, report, title=""):
    """A bar across the screen: a status banner filling it, or buttons side
    by side in one row, equal widths (a picture's navigation row)."""
    from . import compiler as c
    x, y, w, h = rect
    # Not c._card: its padding leaves a banner's height no room, and the
    # banner was dropped from its own band.
    card = c._new(project, "ShCard", (c._slug(section.title) or section.role) + "Card",
                  {"x": x, "y": y, "width": w, "height": h}, {"radius": tokens.radius})
    _frameless(card)
    kind = _band_kind(section)
    gap = tokens.gap if kind == "buttons" else tokens.gap // 2
    palette = getattr(project.screen, "palette", None) or {}
    if kind == "buttons" and palette.get("success") and title and not any(
            str(w.properties.get("borderColor") or "").strip() for w in section.widgets):
        # No tab highlighted in the plan: the page shown is the one the
        # screen's title names (FURNACE on "BLAST FURNACE - 5"), lit in the
        # picture's signal colour as its active tab is.
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        named = [w for w in section.widgets
                 if set(re.findall(r"[a-z0-9]+", str(w.properties.get("text") or "").lower())) <= words
                 and str(w.properties.get("text") or "").strip()]
        if len(named) == 1:
            named[0].properties["borderColor"] = palette["success"]
            named[0].properties.setdefault("textColor", palette["success"])
    widths = _shares(w, [1.0] * len(section.widgets), gap)
    left = 0.0
    for widget, cw in zip(section.widgets, widths):
        if kind == "buttons" and not str(widget.properties.get("backgroundColor") or "").strip() \
                and str(widget.properties.get("variant") or "default") == "default":
            # A navigation row is a set of tabs, not calls to action: the
            # kit's primary blue on all seven read as seven alarms.
            widget.properties["variant"] = "secondary"
        if kind == "buttons" and str(widget.properties.get("borderColor") or "").strip() \
                and not widget.properties.get("borderWidth"):
            # The highlighted tab (the page shown): its colour needs a width
            # to be drawn at all.
            widget.properties["borderWidth"] = 2
        palette = getattr(project.screen, "palette", None) or {}
        if kind == "buttons" and palette:
            # The picture's button grey and text, raised; the highlighted tab
            # glows in its own colour.
            props = widget.properties
            if not str(props.get("backgroundColor") or "").strip():
                props["backgroundColor"] = palette.get("secondary", "")
            if not str(props.get("textColor") or "").strip():
                props["textColor"] = palette.get("foreground", "")
            if _has(registry, "ShButton", "gradient"):
                props.setdefault("gradient", True)
            if _has(registry, "ShButton", "glowColor") and str(props.get("borderColor") or "").strip():
                props.setdefault("glowColor", props["borderColor"])
        _set(widget, left, 0, cw, h)
        card.children.append(widget)
        left += cw + gap
    report.sections.append((section.title, section.role, tuple(int(round(v)) for v in rect)))
    return card


def _cut(crop, box):
    """`crop` inside `box` (both fractions of the picture), or None when
    hardly anything of it is left."""
    l, t, r, b = max(crop[0], box[0]), max(crop[1], box[1]), min(crop[2], box[2]), min(crop[3], box[3])
    return [round(l, 4), round(t, 4), round(r, 4), round(b, 4)] if r - l >= 0.02 and b - t >= 0.02 else None


def _cuttable(widget) -> bool:
    from . import compiler as c
    return widget.type in _PICTURES and bool(widget.properties.get(c.CROP_MARK))         and not str(widget.properties.get("source") or "").strip()


def _strip_pictures(items, strip_bottom, height, notes):
    """The strip's items less any logo whose crop is not in the picture's top
    strip at all: it names some other part of the picture (Ornith put a
    plant's logo in the middle of its drawing), and a wrong picture is worse
    than none. A crop that only runs past the strip is cut back to it."""
    from . import compiler as c
    strip = (0.0, 0.0, 1.0, min(1.0, strip_bottom / float(height) + 0.03))
    kept = []
    for widget in items:
        if _cuttable(widget):
            crop = widget.properties[c.CROP_MARK]
            inside = _cut(crop, strip)
            if inside is None or inside[3] - inside[1] < 0.5 * (crop[3] - crop[1]):
                notes.append(f"{widget.id}: its crop is not in the top strip; left out")
                continue
            widget.properties[c.CROP_MARK] = inside
        kept.append(widget)
    return kept


def _clamp_crops(by_region, width, height, strip_bottom, right_x, foot):
    """Each body picture's crop kept out of the other blocks.

    The layout mirrors the reference's regions, so a block's place on the
    glass says roughly where it is in the picture too. A side of a crop that
    runs well into a neighbour's region (Ornith cropped a blast furnace's
    drawing as the whole screenshot, cards and all) is cut back to that
    region's edge; one that only reaches a little past it is the picture's
    own proportions differing from the layout's, and is kept.
    """
    from . import compiler as c
    W, H = float(width), float(height)
    reach = 0.05
    # A little short of the neighbours' edges: their frames are not part of it.
    top_edge = max(0.0, strip_bottom / H - 0.015) if strip_bottom else 0.0
    right_edge = min(1.0, right_x / W)
    foot_edge = min(1.0, foot / H - 0.02)
    body = [s for name in ("left", "center") for s in by_region.get(name, ())]
    lone = body[0].widgets[0] if len(body) == 1 and len(body[0].widgets) == 1 else None
    if lone is not None and lone.type in _PICTURES and not str(lone.properties.get("source") or "").strip() \
            and not lone.properties.get(c.CROP_MARK):
        # No crop given: the picture is still the body of the reference,
        # cut to the body's box below.
        lone.properties[c.CROP_MARK] = [0.0, 0.0, 1.0, 1.0]
    if lone is not None and _cuttable(lone):
        # The body is one picture (a plant's process drawing): it sits where
        # the layout's body does, and that box is a better crop than the
        # model's guess unless the guess is nearly it. Ornith's guesses for
        # one furnace ran from the whole screenshot to a box 13 % too low.
        widget = body[0].widgets[0]
        box = [0.0, round(top_edge, 4), round(right_edge, 4), round(foot_edge, 4)]
        crop = _cut(widget.properties[c.CROP_MARK], box)
        area = (lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        widget.properties[c.CROP_MARK] = crop if crop and area(crop) >= 0.9 * area(box) else box
        return
    for name in ("left", "center"):
        for section in by_region.get(name, ()):
            for widget in section.widgets:
                if not _cuttable(widget):
                    continue
                l, t, r, b = widget.properties[c.CROP_MARK]
                if t < top_edge - reach:
                    t = top_edge
                if r > right_edge + reach:
                    r = right_edge
                if b > foot_edge + reach:
                    b = foot_edge
                widget.properties[c.CROP_MARK] = _cut([l, t, r, b], (0.0, 0.0, 1.0, 1.0)) \
                    or [0.0, round(top_edge, 4), round(right_edge, 4), round(foot_edge, 4)]


def _snap(values, tolerance):
    """Values within `tolerance` of each other replaced by their mean, so
    blocks the picture draws edge to edge share an edge."""
    order = sorted(set(values))
    groups, out = [], {}
    for value in order:
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    for group in groups:
        mean = sum(group) / len(group)
        for value in group:
            out[value] = mean
    return out


def _box_rects(sections, rect, gap):
    """Each section's box mapped from the picture onto `rect` (x, y, w, h),
    edges snapped into a grid, gutters cut between neighbours and overlaps
    taken off the later block. [(section, (x, y, w, h))]."""
    whole = _union(sections)
    rx, ry, rw, rh = rect
    sx = rw / max(0.05, whole[2] - whole[0])
    sy = rh / max(0.05, whole[3] - whole[1])
    raw = [(s, [rx + (s.box[0] - whole[0]) * sx, ry + (s.box[1] - whole[1]) * sy,
                rx + (s.box[2] - whole[0]) * sx, ry + (s.box[3] - whole[1]) * sy]) for s in sections]
    xs = _snap([v for _s, b in raw for v in (b[0], b[2])], rw * 0.02)
    ys = _snap([v for _s, b in raw for v in (b[1], b[3])], rh * 0.02)
    boxes = []
    for section, (x0, y0, x1, y1) in raw:
        x0, x1, y0, y1 = xs[x0], xs[x1], ys[y0], ys[y1]
        # Half a gutter off every side that has a neighbour, none at the rect's edge.
        x0 += gap / 2.0 if x0 > rx + 1 else 0
        x1 -= gap / 2.0 if x1 < rx + rw - 1 else 0
        y0 += gap / 2.0 if y0 > ry + 1 else 0
        y1 -= gap / 2.0 if y1 < ry + rh - 1 else 0
        boxes.append([section, [x0, y0, x1, y1]])
    for i, (_a, a) in enumerate(boxes):
        for _b, b in boxes[i + 1:]:
            ix = min(a[2], b[2]) - max(a[0], b[0])
            iy = min(a[3], b[3]) - max(a[1], b[1])
            if ix <= 0 or iy <= 0:
                continue
            # Cut along the axis of least overlap, from whichever block loses
            # the smaller share of itself: a navigation rail drawn 5 % too
            # tall gives way to the alarm table under it, which would lose a
            # third of its height.
            if ix < iy:
                lose_a, lose_b = ix / max(1.0, a[2] - a[0]), ix / max(1.0, b[2] - b[0])
                giver, keeper = (a, b) if lose_a < lose_b else (b, a)
                if giver[0] >= keeper[0]:
                    giver[0] = keeper[2] + gap
                else:
                    giver[2] = keeper[0] - gap
            else:
                lose_a, lose_b = iy / max(1.0, a[3] - a[1]), iy / max(1.0, b[3] - b[1])
                giver, keeper = (a, b) if lose_a < lose_b else (b, a)
                if giver[1] >= keeper[1]:
                    giver[1] = keeper[3] + gap
                else:
                    giver[3] = keeper[1] - gap
    return [(s, (b[0], b[1], max(1.0, b[2] - b[0]), max(1.0, b[3] - b[1]))) for s, b in boxes]


def _nav_rail(project, registry, section, rect, tokens, report, title=""):
    """A column of navigation items down the screen's edge (Overview, Raw
    Mill, Alarms ...): full-width items stacked from the top, a list's
    height each; the page shown highlighted. Not the gear selector's pill:
    there ten items were squeezed to "Over", "Raw", "Coal"."""
    from . import compiler as c
    x, y, w, h = rect
    palette = getattr(project.screen, "palette", None) or {}
    card = c._new(project, "ShCard", (c._slug(section.title) or "nav") + "Card",
                  {"x": x, "y": y, "width": w, "height": h},
                  {"color": palette.get("card", c._theme(project, "card")),
                   "borderColor": palette.get("border", c._theme(project, "border")),
                   "borderWidth": 1, "radius": max(6, tokens.radius // 2)})
    items = section.widgets
    pad = max(4, tokens.gap // 2)
    item_h = min((h - 2 * pad) / max(1, len(items)), tokens.control_h * 1.35)
    lit = [wd for wd in items if str(wd.properties.get("borderColor") or wd.properties.get("backgroundColor") or "").strip()]
    if not lit and items:
        words = set(re.findall(r"[a-z0-9]+", title.lower()))
        named = [wd for wd in items if set(re.findall(r"[a-z0-9]+", str(wd.properties.get("text") or wd.properties.get("label") or "").lower())) & words]
        lit = named[:1] or items[:1]
    accent = section.accent or palette.get("success") or c._theme(project, "primary")
    for index, widget in enumerate(items):
        props = widget.properties
        if widget.type == "ShButton":
            props.setdefault("variant", "ghost")
            if widget in lit and not str(props.get("backgroundColor") or "").strip():
                props["backgroundColor"] = accent
                props.setdefault("textColor", "#ffffff")
        _set(widget, pad, pad + index * item_h, w - 2 * pad, item_h - 2)
        card.children.append(widget)
    report.sections.append((section.title, section.role, tuple(int(round(v)) for v in rect)))
    return card


def _is_nav(section) -> bool:
    """A rail of three or more navigation items."""
    return len(section.widgets) >= 3 and all(
        w.type in ("ShButton", "ShIconTile") for w in section.widgets)


def _compile_boxes(project, registry, sections, rect, tokens, report, title=""):
    """The body laid out where the picture's blocks are: every section at
    its box, mapped onto `rect` (a dashboard's rows of tiles, panels and
    tables, which the region columns cannot hold)."""
    out = []
    for section, box in _box_rects(sections, rect, tokens.gap):
        if section.region == "rail" and _is_nav(section):
            out.append(_nav_rail(project, registry, section, box, tokens, report, title=title))
        elif section.region == "rail":
            # A gear selector or mode lamps: the rail's pill, as in the regions.
            out.append(_rail_card(project, registry, section, box, tokens, report))
        elif _band_kind(section):
            out.append(_band(project, registry, section, box, tokens, report, title=title))
        else:
            lone = section.widgets[0] if len(section.widgets) == 1 else None
            bare = lone is not None and (lone.type in _PICTURES or _is_dial(registry, lone))
            # The right column's blocks are cards whatever they hold (a tyre
            # diagram's), as the region layout draws them.
            framed = section.region == "right" or (not bare and section.role != "hero")
            out.append(_section_card(project, registry, section, box, tokens, framed, report))
    return out


def _has(registry, widget_type, prop) -> bool:
    definition = registry.get(widget_type) if registry is not None else None
    return definition is not None and prop in definition.properties


def _dress(project, registry, widgets, tokens) -> None:
    """A picture's palette (screen.palette) on what draws its own colours,
    and the kit's finish where the kit has it: title bands on the cards,
    raised buttons, a glow on the lit banner and the highlighted tab, inset
    value boxes. Only colours the plan left empty are filled."""
    from . import compiler as c
    palette = getattr(project.screen, "palette", None) or {}
    if not palette:
        return

    def fill(widget, prop, value):
        if value and _has(registry, widget.type, prop) and not str(widget.properties.get(prop) or "").strip():
            widget.properties[prop] = value

    # A picture whose chrome carries vivid accents (a cockpit's glowing blue
    # speed arc and orange RPM dial) draws its dials and bars in the kit's
    # neon style, and so does one drawn on near-black glass (the truck's
    # thin arcs are under 1 % of its pixels); a flat SCADA picture on grey
    # keeps the classic ones. The plan's own "style" wins.
    from .palette import _lum, _rgb
    neon = bool(palette.get("primary")) or _lum(_rgb(palette.get("background", "#ffffff"))) < 0.008
    for widget in c._walk(widgets):
        props = widget.properties
        if neon and widget.type in ("ShClusterGauge", "ShSpeedArc") and _has(registry, widget.type, "style"):
            props.setdefault("style", "neon")
        elif neon and widget.type == "ShSegmentBar" and _has(registry, widget.type, "style"):
            props.setdefault("style", "solid")
        elif neon and widget.type == "ShEngineBar" and _has(registry, widget.type, "glow"):
            props.setdefault("glow", True)
        if widget.id == "titleBox" and props.get(c.CHROME_MARK):
            props["color"] = palette.get("inset", props.get("color"))
        elif widget.type == "Text" and props.get(c.CHROME_MARK) and re.search(r"Heading\d*$", widget.id or ""):
            props["color"] = palette.get("foreground", props.get("color"))
        elif widget.type == "ShCard" and props.get(c.CHROME_MARK) and _has(registry, "ShCard", "headerHeight"):
            headings = [ch for ch in widget.children
                        if ch.type == "Text" and re.search(r"Heading\d*$", ch.id or "")]
            if headings:
                # The band under the heading, as the picture's cards have it.
                props["headerHeight"] = int(max(ch.geometry["y"] + ch.geometry["height"] for ch in headings) + 3)
                props["headerColor"] = palette.get("header", "")
        elif widget.type == "ShKpiTile":
            fill(widget, "tileColor", palette.get("card"))
            fill(widget, "barColor", palette.get("success"))
        elif widget.type == "ShProcessValue":
            value = props.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and "decimals" in props:
                # As many decimals as the picture's reading shows: a plan's
                # decimals 3 drew its "4,500 tpd" as 4500.000.
                text = repr(value)                     # 4500 -> 0, 63.0 -> 1, 0.033 -> 3
                props["decimals"] = len(text.split(".", 1)[1]) if "." in text and "e" not in text else 0
            fill(widget, "boxColor", palette.get("inset"))
            fill(widget, "valueColor", palette.get("success"))
            if _has(registry, widget.type, "bevel"):
                props.setdefault("bevel", True)
        elif widget.type == "ShAnnunciator" and props.get("lit") and \
                str(props.get("severity") or "") in ("advisory", "normal", ""):
            fill(widget, "litColor", palette.get("success"))
            if _has(registry, widget.type, "glow"):
                props.setdefault("glow", True)


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
        if section.region == "right" and len(section.widgets) >= 2 and all(
                w.type == "ShDataField" for w in section.widgets):
            # A card of readouts in the column reads as lines, label beside
            # value, as a process card's do; stacked they overran the card.
            for widget in section.widgets:
                widget.properties["stacked"] = False
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
    for name in ("left", "center"):
        for index, section in enumerate(by_region[name]):
            if any(w.type in _PICTURES and w.properties.get(c.CROP_MARK) for w in section.widgets):
                # A picture cut from the reference already prints its labels:
                # words planned beside it ("IRON ORE ->", "HOT AIR/PIPES") are
                # those labels again, squeezed into a band under the picture.
                printed = [w for w in section.widgets if w.type == "Text" and not w.bindings
                           and not w.actions]
                if printed:
                    report.notes.append("left out, the picture prints them: "
                                        + ", ".join(w.id for w in printed))
                    by_region[name][index] = dataclasses.replace(
                        section, widgets=[w for w in section.widgets if w not in printed])

    # The body's sections as bucketed (captions may have been folded in), in
    # plan order: in the box layout a later block gives way to an earlier one.
    order = {id(s.widgets[0]): i for i, s in enumerate(sections) if s.widgets}
    body_sections = sorted((b for name in ("rail", "left", "center", "right", "bottom")
                            for b in by_region[name] if b.widgets),
                           key=lambda s: order.get(id(s.widgets[0]), 0))
    boxed = len(body_sections) >= 2 and all(s.box for s in body_sections)
    plant = bool(by_region["bottom"]) and all(_band_kind(s) for s in by_region["bottom"])
    if plant or boxed:
        # A plant overview is drawn to its edges: four cards of reading lines
        # beside a process drawing need the room a cockpit's margins take.
        tokens = dataclasses.replace(tokens, margin=max(8, tokens.margin // 2),
                                     gap=max(6, tokens.gap // 2))
    widgets = []
    strip_items = list(header_widgets or []) + [w for s in by_region["top"] for w in s.widgets]
    strip_items = _strip_pictures(strip_items, tokens.margin + tokens.header, height, report.notes)
    has_strip = bool(title or strip_items)
    for section in by_region["top"]:
        report.sections.append((section.title, section.role,
                                (tokens.margin, tokens.margin, width - 2 * tokens.margin, tokens.header)))
    if has_strip:
        widgets += _strip(project, registry, title, strip_items, tokens, width, report, height)

    m, gap = tokens.margin, tokens.gap
    bx0, bx1 = m, width - m
    by0 = m + (tokens.header + gap if has_strip else 0)
    by1 = height - m
    body_w, body_h = bx1 - bx0, by1 - by0
    rail, left, center = by_region["rail"], by_region["left"], by_region["center"]
    right, bottom = by_region["right"], by_region["bottom"]

    if boxed:
        # Every block says where it sits: the picture's own arrangement,
        # whatever its rows and columns are.
        for section in body_sections:
            pad = (-0.02, -0.02, 0.02, 0.02)
            around = tuple(_clamp(v + d, 0.0, 1.0) for v, d in zip(section.box, pad))
            for widget in section.widgets:
                if _cuttable(widget):
                    widget.properties[c.CROP_MARK] = _cut(widget.properties[c.CROP_MARK], around) \
                        or [round(v, 4) for v in around]
        widgets += _compile_boxes(project, registry, body_sections, (bx0, by0, body_w, body_h),
                                  tokens, report, title=title)
        report.notes.append("layout from the picture's boxes")
        _dress(project, registry, widgets, tokens)
        page.widgets[:] = widgets
        report.layout = FAMILY_NAME
        c._tidy_scales(page, registry, report.notes)
        return report

    # Bars across the foot of the screen (a status banner, a navigation row)
    # run under everything, the right column too, each a bar's height.
    bands = [s for s in bottom if _band_kind(s)] if bottom and all(_band_kind(s) for s in bottom) else []
    if bands:
        band_hs = [_band_h(_band_kind(s), tokens) for s in bands]
        band_y = by1 - sum(band_hs) - gap * (len(bands) - 1)
        for section, bh in zip(bands, band_hs):
            widgets.append(_band(project, registry, section, (bx0, band_y, body_w, bh), tokens, report,
                                 title=title))
            band_y += bh + gap
        by1 -= sum(band_hs) + gap * len(bands)
        body_h = by1 - by0
        bottom = []
    if bottom and left and center:
        left, center, bottom = _into_columns(left, center, bottom)
    # The picture's own proportions, when its blocks came with their boxes.
    shares = _box_shares(rail, left, center, right, bottom)
    if shares:
        report.notes.append("proportions from the picture: " + ", ".join(
            f"{k} {v:.2f}" for k, v in sorted(shares.items())))
    right_w = round(body_w * shares.get("right", RIGHT_SHARE)) if right else 0
    rail_w = max(44, round(body_w * shares["rail"]) if "rail" in shares
                 else round(width * RAIL_SHARE)) if rail else 0
    main_x1 = bx1 - (right_w + gap if right else 0)
    upper = bool(rail or left or center)
    if bottom and upper:
        bottom_h = round(body_h * shares.get("bottom", BOTTOM_SHARE))
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
                          column, True, report, needs=_box_heights(right))
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
        left_w = round(span * shares.get("left", LEFT_SHARE))
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
        widgets += _stack(project, registry, group, rect, tokens, False, report,
                          needs=_box_heights(group) or weights)
    if bottom:
        # The row runs under the rail too, as the picture's dials do.
        widgets += _row(project, registry, bottom, (bx0, by1 - bottom_h, main_x1 - bx0, bottom_h),
                        tokens, False, report, span=_row_span(rail, left, center, bottom))

    _clamp_crops(by_region, width, height, strip_bottom=m + tokens.header if has_strip else 0,
                 right_x=bx1 - right_w if right else width, foot=by1 + gap if bands else height)
    _dress(project, registry, widgets, tokens)
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
