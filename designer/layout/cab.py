"""The cab display: how a planned train screen is laid out.

A driver's cab display is not a dashboard of cards. Drivers read it the same
way on every train: the line, the train and its signalling across the top;
speed and traction on the left, where the eye rests; the route and the next
station in the middle; the train itself -- its cars, doors and on-board
systems -- on the right. When a plan holds the Rail widgets (a speed arc, a
station line, a consist) the compiler lays it out that way instead of
searching card arrangements, and the model's plan still decides everything
that is on it: the line, the stations, the readings, which systems are shown
and what each is bound to.

Like the rest of the compiler this never reads model geometry. Widgets from
the plan keep their section mark, so a recompile ("Tidy up", Size on screen)
rebuilds the same screen; what the compiler adds itself (cards, captions, the
header bar) is chrome and is rebuilt every time.
"""
from __future__ import annotations

import copy
import re

#: The widgets that make a plan a cab display.
RAIL_TYPES = ("ShSpeedArc", "ShTractionBar", "ShStationLine", "ShTrainConsist")
#: A reading's caption, carried on the Text that shows it (the Text has no
#: caption of its own, and the compiler draws the caption as chrome).
LABEL_MARK = "_cabLabel"
#: What a cab Text is for: "next" (the next station's name), "clock".
ROLE_MARK = "_cabRole"

#: The reference layout is 1024 x 768; other screens scale it.
BASE_W, BASE_H = 1024.0, 768.0

BAR = "#121218"
CARD = "#16161c"
CARD_BORDER = "#26262e"
WHITE = "#f4f4f5"
MUTED = "#a1a1aa"
FAINT = "#71717a"
GREEN = "#4ade80"
CYAN = "#38bdf8"
#: A line is named for its colour; its accent follows the name.
LINE_COLOURS = (("purple", "#a855f7"), ("green", "#4ade80"), ("blue", "#60a5fa"),
                ("yellow", "#facc15"), ("pink", "#f472b6"), ("red", "#f87171"),
                ("orange", "#fb923c"), ("aqua", "#22d3ee"), ("grey", "#a1a1aa"))
DEFAULT_ACCENT = "#a855f7"

READING_TYPES = ("ShValueTile", "ShNumDisplay", "ShAutoReadout", "ShDataField", "ShTripInfo",
                 "ShGearIndicator", "Text")
LAMP_TYPES = ("ShStatDot", "ShAnnunciator", "ShLamp")
_STATUS_ICONS = ((("hvac", "air", "climate", "cool"), "snowflake", CYAN),
                 (("pa", "announce", "audio", "speaker", "pis"), "volume", MUTED),
                 (("pea", "emergency", "alarm", "alert", "intercom"), "bell", "#f87171"),
                 (("fire", "smoke"), "flame", "#f87171"),
                 (("door",), "door", GREEN),
                 (("battery", "aux", "power", "supply"), "battery", GREEN),
                 (("brake",), "gauge", "#fbbf24"),
                 (("radio", "comm", "wifi", "cbtc"), "wifi", CYAN))


def applies(sections, header_widgets=()) -> bool:
    """True when the plan is a cab display: two or more Rail widgets."""
    types = {w.type for s in sections for w in s.widgets} | {w.type for w in header_widgets or ()}
    return len(types & set(RAIL_TYPES)) >= 2


def accent_for(title: str) -> str:
    lowered = (title or "").lower()
    return next((colour for word, colour in LINE_COLOURS if word in lowered), DEFAULT_ACCENT)


def _label(widget) -> str:
    props = widget.properties
    for key in (LABEL_MARK, "title", "label", "_lampLabel", "caption", "name"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().rstrip(":")
    tag = next((b.tag for b in widget.bindings.values() if getattr(b, "tag", "")), "")
    return tag.rsplit(".", 1)[-1].replace("_", " ").title() if tag else ""


def _value(widget) -> str:
    props = widget.properties
    if widget.type == "Text":
        return str(props.get("text", "") or "")
    value = props.get("value", "")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value if value is not None else "")
    unit = str(props.get("unit") or props.get("units") or "")
    binding = next(iter(widget.bindings.values()), None)
    unit = unit or str(getattr(binding, "unit", "") or "")
    return f"{text} {unit}".strip() if unit and text and not text.endswith(unit) else text


def _tag_words(widget) -> str:
    return " ".join(str(getattr(b, "tag", "") or "") for b in widget.bindings.values()).lower()


def _is_next(widget) -> bool:
    if widget.properties.get(ROLE_MARK) == "next":
        return True
    words = (_label(widget) + " " + _tag_words(widget)).lower()
    return "next" in words and not any(w in words for w in ("eta", "arrival", "distance", "time"))


def _names_a_station(widget) -> bool:
    words = (_label(widget) + " " + _tag_words(widget)).lower()
    value = _value(widget)
    return "station" in words and bool(value) and not re.match(r"^[\d.,:\s-]", value)


def _is_clock(widget) -> bool:
    if widget.properties.get(ROLE_MARK) == "clock":
        return True
    words = (_label(widget) + " " + _tag_words(widget) + " " + widget.id).lower()
    return "clock" in words or re.search(r"\btime\b", words) is not None and "arrival" not in words


class _Layout:
    def __init__(self, project, width, height):
        from . import compiler
        self.c = compiler
        self.project = project
        self.sx, self.sy = width / BASE_W, height / BASE_H
        self.sf = min(self.sx, self.sy)
        self.out = []

    def rect(self, x, y, w, h):
        return {"x": int(round(x * self.sx)), "y": int(round(y * self.sy)),
                "width": int(round(w * self.sx)), "height": int(round(h * self.sy))}

    def font(self, size):
        return max(9, int(round(size * self.sf)))

    def chrome(self, wtype, base, x, y, w, h, props):
        widget = self.c._new(self.project, wtype, base, self.rect(x, y, w, h), props)
        self.out.append(widget)
        return widget

    def panel(self, base, x, y, w, h):
        return self.chrome("Rectangle", base, x, y, w, h,
                           {"color": CARD, "borderColor": CARD_BORDER, "borderWidth": 1,
                            "radius": int(round(18 * self.sf))})

    def caption(self, base, x, y, w, h, text, size, colour=MUTED, bold=False, align="Text.AlignLeft"):
        return self.chrome("Text", base, x, y, w, h, _text_props(text, self.font(size), colour, bold, align))

    def place(self, widget, x, y, w, h):
        widget.geometry.update(self.rect(x, y, w, h))
        widget.children = list(widget.children)
        self.out.append(widget)
        return widget

    def reading(self, source, x, y, w, h, size, colour=WHITE, bold=True, role="",
                align="Text.AlignLeft"):
        """A plan reading drawn the cab way: a plain value, its caption as chrome."""
        text = _as_text(self.project, source, role)
        text.properties.update(_text_props(_value(text) or "--", self.font(size), colour, bold, align))
        return self.place(text, x, y, w, h)


def _text_props(text, size, colour, bold, align):
    return {"text": text, "fontSize": int(size), "bold": bool(bold), "color": colour,
            "horizontalAlignment": align, "verticalAlignment": "Text.AlignVCenter",
            "wrapMode": "Text.NoWrap"}


def _as_text(project, source, role=""):
    """A reading as a Text that keeps its id, plan mark and binding."""
    from designer.model import DesignerWidget
    if source.type == "Text":
        widget = source
    else:
        widget = DesignerWidget(type="Text", id=source.id, geometry=dict(source.geometry),
                                properties={}, bindings={})
        from .compiler import SECTION_MARK
        for key in (SECTION_MARK,):
            if key in source.properties:
                widget.properties[key] = source.properties[key]
        widget.properties["text"] = _value(source)
        # The value's binding moves to the text it now shows.
        binding = source.bindings.get("value") or next(iter(source.bindings.values()), None)
        if binding is not None:
            widget.bindings["text"] = copy.deepcopy(binding)
    widget.properties[LABEL_MARK] = _label(source)
    if role:
        widget.properties[ROLE_MARK] = role
    return widget


def _status_card(project, source):
    """A system's state as a status card; a lamp becomes one."""
    from designer.model import DesignerWidget
    if source.type == "ShStatusCard":
        return source
    from .compiler import SECTION_MARK
    label = _label(source) or "System"
    words = (label + " " + _tag_words(source)).lower()
    icon, colour = "check", GREEN
    for keys, kit_icon, tint in _STATUS_ICONS:
        if any(re.search(r"\b" + re.escape(k), words) for k in keys):
            icon, colour = kit_icon, tint
            break
    card = DesignerWidget(type="ShStatusCard", id=source.id, geometry=dict(source.geometry),
                          properties={"icon": icon, "title": label.upper() + ":",
                                      "status": "NORMAL" if colour == "#f87171" else "OK",
                                      "state": "ok", "iconColor": colour}, bindings={})
    if SECTION_MARK in source.properties:
        card.properties[SECTION_MARK] = source.properties[SECTION_MARK]
    binding = next(iter(source.bindings.values()), None)
    if binding is not None:
        card.bindings["state"] = copy.deepcopy(binding)
    return card


def _area(widgets) -> str:
    """The namespace most of the screen's tags live in ("train")."""
    areas = [b.tag.split(".")[0] for w in widgets for b in w.bindings.values()
             if "." in str(getattr(b, "tag", "") or "")]
    return max(set(areas), key=areas.count) if areas else "train"


def _bind(widget, prop, tag) -> None:
    """Bind `prop` to `tag` unless the plan already bound it."""
    if prop not in widget.bindings:
        from designer.model import DesignerBinding
        widget.bindings[prop] = DesignerBinding(tag=tag)


def _live_clock(clock, widgets) -> None:
    """A cab clock tells the time: bound to the plan's own clock tag, or to
    <area>.clock beside the tags the rest of the screen uses."""
    if not clock.bindings:
        _bind(clock, "text", f"{_area(widgets)}.clock")
    if not re.search(r"\d:\d\d", str(clock.properties.get("text") or "")):
        clock.properties["text"] = "12:35:04 PM"


def _live_parts(area, arc, traction, line, consist, progress, next_name, route, fields) -> None:
    """What is always live on a cab display is bound even when the plan left
    it static: a next station that never changes is the screen lying. Each
    gets the tag a cab's PLC map names it by, beside the screen's own tags."""
    for widget, prop, leaf in ((arc, "value", "speed"), (arc, "target", "target_speed"),
                               (traction, "value", "traction_pct"),
                               (line, "current", "station_index"), (line, "details", "station_details"),
                               (consist, "doorsLeft", "doors_left"), (progress, "value", "segment_progress"),
                               (next_name, "text", "next_station")):
        if widget is not None:
            _bind(widget, prop, f"{area}.{leaf}")
    for reading in route:
        words = (_label(reading) + " " + _tag_words(reading)).lower()
        if any(w in words for w in ("arrival", "eta", "time")):
            _bind(reading, "text", f"{area}.eta")
        elif any(w in words for w in ("distance", "dist", "to go")):
            _bind(reading, "text", f"{area}.distance_to_go")
    for field in fields:
        if "door" in (_label(field) + " " + _tag_words(field)).lower():
            _bind(field, "text", f"{area}.doors")


def _consist_from(source):
    from designer.model import DesignerWidget
    from .compiler import SECTION_MARK
    consist = DesignerWidget(type="ShTrainConsist", id=source.id, geometry=dict(source.geometry),
                             properties={"cars": "MC1,M1,T1,T2,M2,MC2", "doorsLeft": "closed",
                                         "doorsRight": "closed"}, bindings={})
    if SECTION_MARK in source.properties:
        consist.properties[SECTION_MARK] = source.properties[SECTION_MARK]
    binding = next(iter(source.bindings.values()), None)
    if binding is not None:
        consist.bindings["doorsLeft"] = copy.deepcopy(binding)
    return consist


def _tidy_consist(consist) -> None:
    """Car names, not a count; door captions that say which side."""
    props = consist.properties
    cars = props.get("cars")
    count = cars if isinstance(cars, (int, float)) else (
        int(cars) if isinstance(cars, str) and cars.strip().isdigit() else None)
    if count is not None:
        # Driving motor cars at the ends; motors either side of the trailers.
        k = max(2, min(12, int(count))) - 2
        motors, trailers = (k + 1) // 2, k // 2
        middle = (["M1"] if motors else []) + ["T%d" % (i + 1) for i in range(trailers)] + \
                 ["M%d" % (i + 2) for i in range(motors - 1)]
        props["cars"] = ",".join(["MC1"] + middle + ["MC2"])
    for key, side in (("leftLabel", "L"), ("rightLabel", "R")):
        label = str(props.get(key) or "")
        if len(label) < 8:
            props[key] = f"DOORS {side}"


def _short_title(text: str) -> str:
    """A status card title that fits: "Passenger Emergency Alarm" ->
    "PEA\\n(Emergency Alarm)", the way cab displays abbreviate."""
    text = text.strip().rstrip(":")
    words = text.split()
    if len(text) <= 16 or len(words) < 3:
        return text.upper() + ":" if len(text) <= 16 else text.upper()
    acronym = "".join(w[0] for w in words if w[0].isalpha()).upper()
    return f"{acronym}\n({' '.join(words[-2:]).title()})"


_TITLE_NOISE = re.compile(r"\b(driver'?s?|cab|display|screen|hmi|dashboard|panel)\b", re.IGNORECASE)


def line_title(title: str) -> str:
    """The line's name for the header: "Purple Line Cab Display" -> "Purple Line"."""
    cleaned = re.sub(r"\s{2,}", " ", _TITLE_NOISE.sub("", title or "")).strip(" -·|")
    return cleaned or (title or "Cab")


def station_window(line, next_name: str = "", keep: int = 6) -> None:
    """At most `keep` stations on the line: from the one before the train,
    through the next station and those after it, to the terminus -- a cab
    shows where the train is, not the whole line."""
    stations = [s.strip() for s in str(line.properties.get("stations") or "").split(",") if s.strip()]
    if len(stations) <= keep:
        return
    details = [s.strip() for s in str(line.properties.get("details") or "").split(",")]
    names = [s.lower() for s in stations]
    at = names.index(next_name.lower()) if next_name and next_name.lower() in names else 2
    start = max(0, min(at - 2, len(stations) - keep))
    picked = list(range(start, start + keep - 1)) + [len(stations) - 1]
    line.properties["stations"] = ",".join(stations[i] for i in picked)
    if len(details) == len(stations):
        line.properties["details"] = ",".join(details[i] for i in picked)
    line.properties["current"] = max(0, min(at - start - 1, keep - 1))


def compile_cab(project, page, registry, sections, title, header_widgets, report, width, height,
                accent_override=None):
    """Lay `page` out as a cab display; replaces page.widgets in place."""
    from .compiler import SECTION_MARK
    lay = _Layout(project, width, height)
    brand = getattr(project, "brand", None) or {}
    accent = accent_override or brand.get("accent") or accent_for(title)
    everything = [w for s in sections for w in s.widgets]
    header = list(header_widgets or [])
    used = set()

    def first(wtype):
        widget = next((w for w in everything if w.type == wtype and id(w) not in used), None)
        if widget is not None:
            used.add(id(widget))
        return widget

    arc, traction = first("ShSpeedArc"), first("ShTractionBar")
    line, consist = first("ShStationLine"), first("ShTrainConsist")
    progress = first("ShProgress")
    if progress is not None:
        # ShProgress is a fraction; a plan that wrote a percentage means it.
        value = progress.properties.get("value")
        if isinstance(value, (int, float)) and value > 1:
            progress.properties["value"] = round(min(value, 100) / 100.0, 3)
    if consist is None:
        # The doors live on the train, not on a card: a doors status becomes
        # the consist, keeping its id, plan mark and binding.
        doors = next((w for w in everything if id(w) not in used and w.type in ("ShStatusCard",) + LAMP_TYPES
                      and "door" in (_label(w) + " " + _tag_words(w)).lower()), None)
        if doors is not None:
            consist = _consist_from(doors)
            used.add(id(doors))
    # Readings: the route's (the next station, its ETA and distance) and the
    # rest, which sit under the speed. Which is which comes from the section
    # they were planned in, then from what they say.
    route_words = ("route", "next", "journey", "station", "arrival", "trip")
    route_sections = {id(s) for s in sections
                      if any(w in (s.title or "").lower() for w in route_words)
                      or any(w is line for w in s.widgets)}
    route, drive, statuses, callouts, clock = [], [], [], [], None
    for section in sections:
        for widget in section.widgets:
            if id(widget) in used:
                continue
            if _is_clock(widget) and clock is None:
                clock = widget
            elif widget.type == "ShTelltale":
                callouts.append(widget)
            elif widget.type == "ShStatusCard" or widget.type in LAMP_TYPES:
                statuses.append(widget)
            elif widget.type in READING_TYPES:
                (route if id(section) in route_sections or _is_next(widget) else drive).append(widget)
            else:
                report.notes.append(f"{widget.id}: {widget.type} has no place on a cab display")
                continue
            used.add(id(widget))
    logos = [w for w in header if w.type == "Image"]
    fields = []
    for widget in header:
        if widget.type == "Image":
            continue
        if _is_clock(widget) and clock is None:
            clock = widget
        elif widget.type in LAMP_TYPES:
            statuses.append(widget)
        elif widget.type in READING_TYPES:
            fields.append(widget)
    # The next station's name leads the NEXT card; the rest of the route's
    # readings go under it, two at most, and any left over join the drive's.
    next_name = next((w for w in route if _is_next(w)), None) or next(
        (w for w in route if _names_a_station(w)), None)
    route = [w for w in route if w is not next_name]
    if line is not None:
        # The station line already shows where the train is.
        for reading in [w for w in route + drive if _names_a_station(w)]:
            report.notes.append(f"{reading.id}: the station line shows the current station")
            (route if reading in route else drive).remove(reading)
    drive += route[2:]
    route = route[:2]
    # Header fields: the plan's, then readings that read like the train's
    # identity or mode when the header has room.
    while len(fields) < 4 and len(drive) > 2:
        fields.append(drive.pop())

    # -- header --------------------------------------------------------------
    lay.chrome("Rectangle", "headerBar", 0, 0, BASE_W, 64,
               {"color": BAR, "borderColor": CARD_BORDER, "borderWidth": 0, "radius": 0})
    left = [w for w in logos if w.properties.get(lay.c.SIDE_MARK) == "left"]
    right = [w for w in logos if w not in left]
    if len(logos) == 2 and not left:
        left, right = logos[:1], logos[1:]
    x = 16
    if left:
        lay.chrome("Rectangle", f"{left[0].id}Plate", 10, 10, 104, 44,
                   {"color": "#ffffff", "radius": int(round(8 * lay.sf)), "borderWidth": 0})
        lay.place(left[0], 14, 13, 96, 38)
        x = 124
    name = line_title(title).upper()
    title_w = min(260, max(110, len(name) * 13 + 8))
    heading = lay.caption("screenTitle", x, 14, title_w, 36, name, 20, accent, bold=True)
    heading.properties[SECTION_MARK] = "|title"
    end = 1024 - 16
    if right:
        lay.chrome("Rectangle", f"{right[0].id}Plate", 886, 10, 128, 44,
                   {"color": "#ffffff", "radius": int(round(8 * lay.sf)), "borderWidth": 0})
        lay.place(right[0], 890, 14, 120, 36)
        end = 876
    if clock is not None:
        _live_clock(clock, everything + header)
        lay.reading(clock, end - 160, 14, 160, 36, 20, WHITE, bold=False, role="clock",
                    align="Text.AlignRight").properties[SECTION_MARK] = "|header"
        end -= 170
    fx, room = x + title_w + 2, end - (x + title_w + 2) - 8
    fields = fields[:4]
    if fields and room > 120:
        # Room for the longest word a live field shows ("LOCKED", "ATO (AUTO)").
        weights = [max(len(_label(f)), len(_value(f)), 9) for f in fields]
        for field, weight in zip(fields, weights):
            fw = room * weight / sum(weights)
            label = _label(field).upper()
            lay.caption(f"{field.id}Label", fx, 10, fw - 6, 20, label + ":", 11)
            ok = _value(field).strip().lower() in ("ok", "clear", "normal")
            lay.reading(field, fx, 30, fw - 6, 24, 15, GREEN if ok else WHITE).properties[SECTION_MARK] = "|header"
            lay.chrome("Rectangle", f"{field.id}Rule", fx + fw - 4, 14, 1, 36,
                       {"color": CARD_BORDER, "borderWidth": 0, "radius": 0})
            fx += fw

    # -- left: speed and traction ----------------------------------------------
    lay.panel("driveCard", 12, 76, 336, 680)
    if arc is not None:
        # The cab's two rings: speed in cyan, the line's colour inside.
        arc.properties.update({"outerColor": "#22d3ee", "innerColor": accent})
        lay.place(arc, 14, 136, 262 if traction is not None else 330, 262 if traction is not None else 330)
    if traction is not None:
        if len(str(traction.properties.get("title") or "")) > 5:
            traction.properties["title"] = "T/B"
        lay.place(traction, 262, 96, 78, 520)
    for i, reading in enumerate(drive[:2]):
        rx = 32 + i * 158
        lay.caption(f"{reading.id}Label", rx, 650, 150, 22, _label(reading).upper() + ":", 13)
        lay.reading(reading, rx, 676, 150, 40, 30)
    for reading in drive[2:]:
        report.notes.append(f"{reading.id}: no room for a third reading under the speed")

    # -- middle: route and the next station ------------------------------------
    if line is not None:
        lay.panel("routeCard", 360, 76, 320, 480)
        line.properties["accent"] = accent
        station_window(line, _value(next_name) if next_name is not None else "")
        lay.place(line, 368, 84, 304, 464)
    if next_name is not None or route or progress is not None:
        top = 568 if line is not None else 76
        height = 188 if line is not None else 680
        lay.panel("nextCard", 360, top, 320, height)
        if next_name is not None:
            lay.caption("nextLabel", 380, top + 14, 92, 40, "NEXT:", 26, FAINT, bold=True)
            lay.reading(next_name, 470, top + 14, 204, 40, 26, role="next")
        for i, reading in enumerate(route):
            rx = 380 + i * 150
            lay.caption(f"{reading.id}Label", rx, top + 68, 140, 20, _label(reading).upper() + ":", 12)
            lay.reading(reading, rx, top + 90, 140, 36, 26)
        if progress is not None:
            lay.place(progress, 380, top + 148, 280, 10)

    # -- right: the train ------------------------------------------------------
    lay.panel("trainCard", 692, 76, 320, 680)
    if consist is not None:
        consist.properties["accent"] = accent
        _tidy_consist(consist)
        lay.place(consist, 700, 92, 140, 600)
    cards = [_status_card(project, w) for w in statuses]
    for i, card in enumerate(cards[:3]):
        title_text = str(card.properties.get("title") or "")
        if "\n" not in title_text:
            card.properties["title"] = _short_title(title_text)
        lay.place(card, 848, 96 + i * 138, 156, 126)
    for card in cards[3:]:
        report.notes.append(f"{card.id}: a cab shows three systems; this one was left off")
    if callouts:
        tell = callouts[0]
        words = (_label(tell) or "Aligned").upper().split()
        lay.place(tell, 900, 530, 52, 52)
        tell.properties.setdefault("color", "blue")
        if any(w in words for w in ("ALIGNED", "OK", "READY", "CLEAR")):
            tell.properties["icon"] = "check"
        tell.properties[LABEL_MARK] = _label(tell)
        tell.properties["label"] = ""
        lines = [words[0]] + words[1:2] + [" ".join(words[2:])]
        for i, text in enumerate(t for t in lines if t):
            lay.caption(f"{tell.id}Line{i + 1}", 852, 588 + (0 if i == 0 else 38 + (i - 1) * 26),
                        150, 40 if i == 0 else 26, text, 30 if i == 0 else 20, CYAN,
                        bold=i == 0, align="Text.AlignHCenter")

    placed = {w.id: w for w in lay.out}

    def on_page(widget):
        return placed.get(widget.id) if widget is not None else None

    _live_parts(_area(everything + header), on_page(arc), on_page(traction), on_page(line),
                on_page(consist), on_page(progress), on_page(next_name),
                [p for p in map(on_page, route) if p is not None],
                [p for p in map(on_page, fields) if p is not None])
    page.widgets[:] = lay.out
    report.layout = "cab display"
    report.sections = [("Drive", "hero", (12, 76, 336, 680)), ("Route", "readings", (360, 76, 320, 680)),
                        ("Train", "status", (692, 76, 320, 680))]
    return report


#: The name this family is registered under in designer.layout.families.
FAMILY_NAME = "cab display"


def _applies(sections, header, width, height) -> bool:
    """True when the page is a cab display: two or more Rail widgets.

    A cab is recognised by its content, not its size, so the width and height
    the family search gives are ignored here -- only the widget types matter.
    """
    return applies(sections, header)


#: Register this family when the module is imported, so the compiler's search
#: (family_for) lays a cab display out the standard way.
try:
    from . import families as _families
    _families.register(FAMILY_NAME, _applies, compile_cab)
except Exception:  # pragma: no cover - import guard for early callers
    pass
