"""Canvas previews that mirror ui/qml/Shadcn.

The Designer used to draw every component as the same rounded box with its
caption centred in it, so a Button, a Gauge, a Progress bar and an Alarm
indicator were indistinguishable until the page was generated and deployed.
Laying out a screen means judging it by eye, and there was nothing to judge.

Each painter here reproduces what the matching QML component actually renders,
reading the same properties and the same theme tokens. They are deliberately
approximations of static appearance: no hover, focus, or animation states --
the canvas shows a component at rest, which is the state an author is
positioning.

Tokens come from ui/qml/Shadcn/Theme.qml. The panel ships dark (the deployed
manifests set theme: dark), so the dark column is the default; light is kept
alongside it because the Studio's own theme can be switched and a preview in
the wrong palette is worse than no preview.

When a component changes in ui/qml/Shadcn, the painter here is what has to
follow it. tests/test_designer_previews.py holds the pairs that matter.
"""
import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainterPath, QPen,
                           QPolygonF)
from ui.python.shadcn import load_tokens

# ---------------------------------------------------------------------------
# Theme tokens -- ui/qml/Shadcn/Theme.qml
# ---------------------------------------------------------------------------

_PALETTES = load_tokens()["palettes"]
DARK = dict(_PALETTES["dark"])
LIGHT = dict(_PALETTES["light"])

# Avionics instrument colours -- Theme.qml's efis* block. Deliberately not
# part of DARK/LIGHT: an EFIS is read the same way in any cockpit, and the
# conventions (blue sky, brown ground, amber caution, red warning) are the
# information. Theming them would make the instrument wrong, not restyled.
EFIS = {
    "sky": "#2b6fb5", "ground": "#7a5230", "panel": "#05070a",
    "line": "#ffffff", "text": "#ffffff", "aircraft": "#ffd400",
    "normal": "#12b32a", "caution": "#ffb000", "warning": "#e01b24",
    "nav": "#ff31d3", "bug": "#00d4ff",
}


# Automotive cluster colours -- Theme.qml's auto* block; same reasoning.
AUTO = {
    "panel": "#0b0f16",
    "track": "#1a222e",
    "accent": "#22a8ff",
    "accentDeep": "#0a4f8a",
    "glow": "#7fd4ff",
    "redline": "#ff2d55",
    "text": "#ffffff",
    "muted": "#8a97a8",
    "line": "#c9d3df",
    "amber": "#ffb000",
    "green": "#2fe07f",
    "red": "#ff3b3b",
    "blue": "#4f9dff",
    "tileBg": "#141c28",
    "tileBorder": "#22304a",
}


def auto(name: str) -> QColor:
    """An automotive cluster colour. Unknown names are loud rather than black."""
    if name not in AUTO:
        raise KeyError(f"no automotive colour named {name!r}")
    return QColor(AUTO[name])


def efis(name: str) -> QColor:
    """An instrument colour. Unknown names are loud rather than silently black."""
    if name not in EFIS:
        raise KeyError(f"no EFIS colour named {name!r}")
    return QColor(EFIS[name])


# Theme.radius* and Theme.fontSize*
RADIUS = {"sm": 4, "md": 12, "lg": 16, "xl": 20, "full": 9999}
FONT = {"xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20, "xxl": 24, "xxxl": 30}
SPACING = {4: 4, 8: 8, 12: 12, 16: 16, 24: 24, 32: 32}

# Theme.fontMedium / fontSemibold, in QFont weights.
WEIGHT_MEDIUM = QFont.Medium
WEIGHT_SEMIBOLD = QFont.DemiBold

# The palette every painter reads. Swapped by set_theme_mode.
_TOKENS = dict(DARK)
_THEME_MODE = "dark"


def set_theme_mode(mode: str) -> None:
    """Point the painters at the light or dark token set."""
    global _TOKENS, _THEME_MODE
    _THEME_MODE = "light" if mode == "light" else "dark"
    _TOKENS = dict(LIGHT if _THEME_MODE == "light" else DARK)


def theme_mode() -> str:
    return _THEME_MODE


def token(name: str) -> QColor:
    """A theme colour. Unknown names are loud rather than silently black."""
    if name not in _TOKENS:
        raise KeyError(f"no Shadcn theme token named {name!r}")
    return QColor(_TOKENS[name])


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _radius(value):
    """Clamp Theme.radiusFull to something drawRoundedRect can use.

    radiusFull is 9999 -- QML's way of saying "a pill". Passed straight to
    drawRoundedRect it produces nothing; half the shorter side is the same
    shape.
    """
    return value


def _pill(painter, rect, color, border=None, width=0):
    """A fully-rounded rect: Theme.radiusFull against a real geometry."""
    radius = min(rect.width(), rect.height()) / 2.0
    painter.setBrush(QBrush(color))
    painter.setPen(QPen(border, width) if border and width else Qt.NoPen)
    painter.drawRoundedRect(rect, radius, radius)


def _rounded(painter, rect, color, radius, border=None, width=0):
    painter.setBrush(QBrush(color) if color is not None else Qt.NoBrush)
    painter.setPen(QPen(border, width) if border is not None and width else Qt.NoPen)
    painter.drawRoundedRect(rect, radius, radius)


def _text(painter, rect, string, *, size, color, weight=QFont.Normal,
          flags=Qt.AlignLeft | Qt.AlignVCenter, elide=True):
    font = painter.font()
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    painter.setFont(font)
    painter.setPen(QPen(color))
    if elide:
        metrics = painter.fontMetrics()
        string = metrics.elidedText(str(string), Qt.ElideRight, int(rect.width()))
    painter.drawText(rect, flags, str(string))


def _state_color(state):
    """ShBadge/ShStatDot map the four machine states onto theme colours."""
    return token({"ok": "success", "warn": "warning",
                  "fault": "destructive"}.get(state, "mutedForeground"))


def _prop(props, key, default=None):
    value = props.get(key, default)
    return default if value in (None, "") else value


def _number(props, key, default=0.0):
    try:
        return float(_prop(props, key, default))
    except (TypeError, ValueError):
        return float(default)


def shade(colour, pct):
    """Theme.shade / draw_util.h hmi_shade: lighter by pct % (each channel
    moves pct % of the way to white) or darker by -pct %; alpha kept."""
    k = max(-1.0, min(1.0, pct / 100.0))
    c = QColor(colour)
    ch = [c.redF(), c.greenF(), c.blueF()]
    ch = [v + (1 - v) * k if k >= 0 else v * (1 + k) for v in ch]
    return QColor.fromRgbF(*ch, c.alphaF())


def _vertical_gradient(rect, top, bottom):
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, top)
    gradient.setColorAt(1.0, bottom)
    return QBrush(gradient)


# ShGlow.qml's fall-off (coverage 1..8 px outside the edge), shared with the
# panel's LVGL shadow.
GLOW_PROFILE = (0.55, 0.43, 0.32, 0.23, 0.15, 0.089, 0.042, 0.010)


def _glow(painter, rect, colour, radius):
    """A soft outer glow around ``rect``: rings whose coverage follows
    GLOW_PROFILE, outermost first."""
    painter.save()
    painter.setPen(Qt.NoPen)
    reach = len(GLOW_PROFILE)
    for d in range(reach, 0, -1):
        outer = GLOW_PROFILE[d] if d < reach else 0.0
        alpha = max(0.0, 1 - (1 - GLOW_PROFILE[d - 1]) / (1 - outer))
        c = QColor(colour)
        c.setAlphaF(c.alphaF() * alpha)
        painter.setBrush(QBrush(c))
        r = QRectF(rect).adjusted(-d, -d, d, d)
        painter.drawRoundedRect(r, radius + d if radius > 0 else 0, radius + d if radius > 0 else 0)
    painter.restore()


def _override_colour(props, key):
    """An optional colour property (accentColor, barColor): its QColor, or
    None when unset, invalid or fully transparent -- the theme's look."""
    colour = QColor(str(_prop(props, key, "") or "transparent"))
    return colour if colour.isValid() and colour.alpha() > 0 else None


# QML alignment tokens -> Qt flags. Shared by the painter and the Designer's
# alignment control, so the two cannot disagree about what a value means.
H_ALIGN = {
    "Text.AlignLeft": Qt.AlignLeft,
    "Text.AlignHCenter": Qt.AlignHCenter,
    "Text.AlignRight": Qt.AlignRight,
    "Text.AlignJustify": Qt.AlignJustify,
}
V_ALIGN = {
    "Text.AlignTop": Qt.AlignTop,
    "Text.AlignVCenter": Qt.AlignVCenter,
    "Text.AlignBottom": Qt.AlignBottom,
}


def text_alignment_flags(props):
    """The Qt flags for a Text widget's declared alignment."""
    horizontal = H_ALIGN.get(_prop(props, "horizontalAlignment", "Text.AlignLeft"),
                             Qt.AlignLeft)
    vertical = V_ALIGN.get(_prop(props, "verticalAlignment", "Text.AlignTop"),
                           Qt.AlignTop)
    return horizontal | vertical


# ---------------------------------------------------------------------------
# Painters -- one per registered widget type
# ---------------------------------------------------------------------------

def paint_text(painter, rect, props, ctx):
    """QML Text: glyphs only, no background, honouring both alignments."""
    color = QColor(_prop(props, "color", _TOKENS["foreground"]))
    font = painter.font()
    font.setPixelSize(max(1, int(_number(props, "fontSize", FONT["lg"]))))
    font.setBold(bool(props.get("bold")))
    painter.setFont(font)
    painter.setPen(QPen(color))
    flags = text_alignment_flags(props)
    if "Wrap" in str(_prop(props, "wrapMode", "Text.NoWrap")):
        flags |= Qt.TextWordWrap
    painter.drawText(rect, flags, str(_prop(props, "text", "")))


def paint_button(painter, rect, props, ctx):
    """ShButton: variant decides fill, border and label colour."""
    variant = _prop(props, "variant", "default")
    override = QColor(_prop(props, "backgroundColor", "") or "transparent")
    if override.isValid() and override.alpha() > 0:
        fill = override
    elif variant == "default":
        fill = token("primary")
    elif variant == "secondary":
        fill = token("secondary")
    elif variant == "destructive":
        fill = token("destructive")
    else:                                    # outline, ghost, link
        fill = QColor(Qt.transparent)

    border_override = QColor(_prop(props, "borderColor", "") or "transparent")
    if border_override.isValid() and border_override.alpha() > 0:
        border, width = border_override, max(1, int(_number(props, "borderWidth", 1)))
    elif variant == "outline":
        border, width = token("border"), 1
    else:
        border, width = None, 0

    radius = _number(props, "cornerRadius", RADIUS["md"])
    glow = _override_colour(props, "glowColor")
    if glow is not None:
        _glow(painter, rect, glow, radius)
    if bool(_prop(props, "gradient", False)) and fill.alpha() > 0:
        painter.setBrush(_vertical_gradient(QRectF(rect), shade(fill, 12), shade(fill, -12)))
        painter.setPen(QPen(border, width) if border is not None and width else Qt.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
    else:
        _rounded(painter, rect, fill, radius, border, width)

    text_override = QColor(_prop(props, "textColor", "") or "transparent")
    if text_override.isValid() and text_override.alpha() > 0:
        color = text_override
    elif variant == "default":
        color = token("primaryForeground")
    elif variant == "secondary":
        color = token("secondaryForeground")
    elif variant == "destructive":
        color = token("destructiveForeground")
    else:
        color = token("foreground")

    _text(painter, rect, _prop(props, "text", ""), size=FONT["sm"], color=color,
          weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_input(painter, rect, props, ctx):
    """ShInput: an outlined field showing its text, or its placeholder."""
    _rounded(painter, rect, QColor(Qt.transparent), RADIUS["md"], token("input"), 1)
    value = _prop(props, "text", "")
    inner = rect.adjusted(SPACING[12], 0, -SPACING[12], 0)
    _text(painter, inner, value or _prop(props, "placeholderText", ""),
          size=FONT["sm"],
          color=token("foreground") if value else token("mutedForeground"),
          flags=Qt.AlignLeft | Qt.AlignVCenter)


def paint_rectangle(painter, rect, props, ctx):
    """QML Rectangle: exactly its colour, border and radius."""
    width = int(_number(props, "borderWidth", 0))
    _rounded(painter, rect, QColor(_prop(props, "color", "#27272a")),
             _number(props, "radius", RADIUS["sm"]),
             QColor(_prop(props, "borderColor", "#52525b")) if width else None, width)


def paint_card(painter, rect, props, ctx):
    """ShCard: the surface other components are composed onto; optionally a
    title band (headerHeight, headerColor) and a gradient fill."""
    width = int(_number(props, "borderWidth", 1))
    fill = QColor(_prop(props, "color", _TOKENS["card"]))
    border = QColor(_prop(props, "borderColor", "#27272a"))
    radius = _number(props, "radius", RADIUS["xl"])
    header = int(_number(props, "headerHeight", 0))
    if not bool(_prop(props, "gradient", False)) and header <= width:
        _rounded(painter, rect, fill, radius, border if width else None, width)
        return
    r = QRectF(rect)
    brush = _vertical_gradient(r, shade(fill, 6), fill) if _prop(props, "gradient", False) else QBrush(fill)
    painter.setBrush(brush)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(r, radius, radius)
    if header > width:
        band = _override_colour(props, "headerColor") or shade(fill, 12)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(QRectF(r.left(), r.top(), r.width(), header - 1), band)
        painter.fillRect(QRectF(r.left(), r.top() + header - 1, r.width(), 1), border)
        painter.restore()
    if width:
        _rounded(painter, rect, None, radius, border, width)


def paint_value_tile(painter, rect, props, ctx):
    """ShValueTile: a card carrying a label, a state badge and a big reading."""
    _rounded(painter, rect, token("card"), RADIUS["xl"], token("secondary"), 1)
    inner = rect.adjusted(SPACING[16], SPACING[16], -SPACING[16], -SPACING[16])
    if inner.width() <= 0 or inner.height() <= 0:
        return

    state = str(_prop(props, "state", "idle"))
    badge_text = state.upper()
    font = painter.font()
    font.setPixelSize(FONT["xs"])
    font.setWeight(WEIGHT_SEMIBOLD)
    painter.setFont(font)
    badge_width = min(painter.fontMetrics().horizontalAdvance(badge_text) + 20,
                      inner.width())
    badge = QRectF(inner.right() - badge_width, inner.top(), badge_width, 20)
    _pill(painter, badge, _state_color(state))
    _text(painter, badge, badge_text, size=FONT["xs"],
          color=token("background") if state != "idle" else token("secondaryForeground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter, elide=False)

    label = QRectF(inner.left(), inner.top(),
                   max(0.0, inner.width() - badge_width - SPACING[8]), 20)
    _text(painter, label, _prop(props, "title", "Value"), size=FONT["sm"],
          color=token("mutedForeground"), weight=WEIGHT_MEDIUM,
          flags=Qt.AlignLeft | Qt.AlignVCenter)

    reading = QRectF(inner.left(), inner.top() + 20 + SPACING[8],
                     inner.width(), max(0.0, inner.height() - 20 - SPACING[8]))
    value = str(_prop(props, "value", "0.0"))
    unit = str(_prop(props, "unit", ""))
    font.setPixelSize(FONT["xxxl"])
    painter.setFont(font)
    value_width = painter.fontMetrics().horizontalAdvance(value)
    _text(painter, reading, value, size=FONT["xxxl"], color=token("foreground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignLeft | Qt.AlignTop, elide=False)
    if unit:
        unit_rect = QRectF(reading.left() + value_width + SPACING[4], reading.top(),
                           max(0.0, reading.width() - value_width - SPACING[4]),
                           FONT["xxxl"])
        _text(painter, unit_rect, unit, size=FONT["sm"],
              color=token("mutedForeground"), flags=Qt.AlignLeft | Qt.AlignBottom)


def paint_stat_dot(painter, rect, props, ctx):
    """ShStatDot: a filled circle carrying the state colour."""
    diameter = min(rect.width(), rect.height())
    dot = QRectF(0, 0, diameter, diameter)
    dot.moveCenter(rect.center())
    painter.setBrush(QBrush(_state_color(str(_prop(props, "state", "idle")))))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(dot)


def paint_progress(painter, rect, props, ctx):
    """ShProgress: a pill track with a primary indicator across it."""
    _pill(painter, rect, token("secondary"))
    if _prop(props, "indeterminate", False):
        fraction = 0.3
    else:
        fraction = max(0.0, min(1.0, _number(props, "value", 0.0)))
    if fraction <= 0:
        return
    indicator = QRectF(rect.left(), rect.top(), rect.width() * fraction, rect.height())
    # The indicator is clipped by the track, so it keeps the track's radius.
    painter.save()
    path = QPainterPath()
    radius = min(rect.width(), rect.height()) / 2.0
    path.addRoundedRect(rect, radius, radius)
    painter.setClipPath(path)
    _pill(painter, indicator, token("primary"))
    painter.restore()


def paint_alert(painter, rect, props, ctx):
    """ShAlert: an outlined panel, destructive variant colouring both texts."""
    destructive = _prop(props, "variant", "destructive") == "destructive"
    outline = token("destructive") if destructive else token("secondary")
    _rounded(painter, rect, QColor(Qt.transparent), RADIUS["lg"], outline, 1)
    inner = rect.adjusted(SPACING[16], SPACING[16], -SPACING[16], -SPACING[16])
    if inner.width() <= 0 or inner.height() <= 0:
        return
    title_color = token("destructive") if destructive else token("foreground")
    title = QRectF(inner.left(), inner.top(), inner.width(), FONT["sm"] + 6)
    _text(painter, title, _prop(props, "title", "Alarm"), size=FONT["sm"],
          color=title_color, weight=WEIGHT_MEDIUM, flags=Qt.AlignLeft | Qt.AlignTop)
    description = str(_prop(props, "description", ""))
    if description:
        body = QRectF(inner.left(), title.bottom() + SPACING[4], inner.width(),
                      max(0.0, inner.bottom() - title.bottom() - SPACING[4]))
        _text(painter, body, description, size=FONT["sm"],
              color=title_color if destructive else token("mutedForeground"),
              flags=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, elide=False)


def paint_gauge(painter, rect, props, ctx):
    """ShGauge: a 270-degree arc from 135, thresholds colouring the value."""
    dimension = min(rect.width(), rect.height())
    if dimension <= 0:
        return
    stroke = max(2.0, dimension * 0.1)
    square = QRectF(0, 0, dimension - stroke, dimension - stroke)
    square.moveCenter(rect.center())

    minimum = _number(props, "minimum", 0.0)
    maximum = _number(props, "maximum", 100.0)
    value = _number(props, "value", 0.0)
    span = maximum - minimum
    fraction = 0.0 if span <= 0 else max(0.0, min(1.0, (value - minimum) / span))

    if value >= _number(props, "thresholdFault", 90.0):
        color = token("destructive")
    elif value >= _number(props, "thresholdWarning", 70.0):
        color = token("warning")
    else:
        color = token("success")

    painter.setBrush(Qt.NoBrush)
    # Qt angles are 1/16th degree, counter-clockwise from 3 o'clock; QML's
    # startAngle 135 sweep 270 is clockwise from the top-left.
    painter.setPen(QPen(token("muted"), stroke, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(square, int(225 * 16), int(-270 * 16))
    if fraction > 0:
        painter.setPen(QPen(color, stroke, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(square, int(225 * 16), int(-270 * 16 * fraction))

    unit = str(_prop(props, "unit", ""))
    reading = f"{value:g}{unit}"
    centre = QRectF(square.left(), square.center().y() - dimension * 0.18,
                    square.width(), dimension * 0.26)
    _text(painter, centre, reading, size=max(10, int(dimension * 0.2)),
          color=token("foreground"), weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
    label = str(_prop(props, "label", ""))
    if label:
        below = QRectF(square.left(), centre.bottom(), square.width(), dimension * 0.18)
        _text(painter, below, label, size=max(9, int(dimension * 0.11)),
              color=token("mutedForeground"), flags=Qt.AlignCenter)


def paint_tabs(painter, rect, props, ctx):
    """ShTabs: the tab strip with the current tab lifted out of the track."""
    titles = [part.strip() for part in str(_prop(props, "tabs", "")).split(",")
              if part.strip()] or ["Tab"]
    strip_height = min(36.0, rect.height())
    strip = QRectF(rect.left(), rect.top(), rect.width(), strip_height)
    _rounded(painter, strip, token("muted"), RADIUS["lg"])

    inner = strip.adjusted(SPACING[4], SPACING[4], -SPACING[4], -SPACING[4])
    if inner.width() > 0 and inner.height() > 0:
        current = int(_number(props, "currentIndex", 0))
        each = inner.width() / len(titles)
        for index, title in enumerate(titles):
            cell = QRectF(inner.left() + index * each, inner.top(), each, inner.height())
            if index == current:
                _rounded(painter, cell, token("background"), RADIUS["md"])
            _text(painter, cell, title, size=FONT["sm"],
                  color=token("foreground") if index == current else token("mutedForeground"),
                  weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)

    body = QRectF(rect.left(), strip.bottom() + SPACING[8], rect.width(),
                  max(0.0, rect.bottom() - strip.bottom() - SPACING[8]))
    if body.height() > 0:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(token("secondary"), 1, Qt.DashLine))
        painter.drawRoundedRect(body, RADIUS["md"], RADIUS["md"])


def _paint_container(painter, rect, props, ctx, label):
    """Row, Column, Grid and Page: structure, not surface.

    These position their children and draw nothing themselves, so a filled box
    would misrepresent them. A dashed outline and a corner tag say "this is a
    frame" without competing with the widgets inside it.
    """
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(token("mutedForeground"), 1, Qt.DashLine))
    painter.drawRoundedRect(rect, RADIUS["sm"], RADIUS["sm"])
    tag = QRectF(rect.left() + 4, rect.top() + 2, max(0.0, rect.width() - 8), 14)
    if tag.width() > 0:
        _text(painter, tag, label, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignLeft | Qt.AlignVCenter)


# ---------------------------------------------------------------------------
# Avionics painters -- mirroring the Sh* instruments
# ---------------------------------------------------------------------------

def _severity_color(severity):
    """The three alert levels, in the colours a crew is trained to read."""
    return efis({"warning": "warning", "caution": "caution"}.get(severity, "text"))


def paint_data_field(painter, rect, props, ctx):
    """ShDataField: caption, reading, unit -- what an EFIS strip is made of."""
    label = str(_prop(props, "label", "LABEL"))
    value = str(_prop(props, "value", "---"))
    units = str(_prop(props, "units", ""))
    colour = _severity_color(_prop(props, "severity", "advisory"))

    if _prop(props, "stacked", True):
        caption = QRectF(rect.left(), rect.top(), rect.width(), FONT["xs"] + 4)
        _text(painter, caption, label, size=FONT["xs"],
              color=token("mutedForeground"), weight=WEIGHT_MEDIUM)
        reading = QRectF(rect.left(), caption.bottom() + 2, rect.width(),
                         max(0.0, rect.bottom() - caption.bottom() - 2))
    else:
        half = rect.width() * 0.45
        _text(painter, QRectF(rect.left(), rect.top(), half, rect.height()), label,
              size=FONT["xs"], color=token("mutedForeground"), weight=WEIGHT_MEDIUM)
        reading = QRectF(rect.left() + half + SPACING[8], rect.top(),
                         max(0.0, rect.width() - half - SPACING[8]), rect.height())

    size = FONT["xl"] if _prop(props, "stacked", True) else FONT["base"]
    font = painter.font()
    font.setPixelSize(size)
    font.setWeight(WEIGHT_SEMIBOLD)
    painter.setFont(font)
    value_width = painter.fontMetrics().horizontalAdvance(value)
    _text(painter, reading, value, size=size, color=colour, weight=WEIGHT_SEMIBOLD,
          flags=Qt.AlignLeft | Qt.AlignVCenter, elide=False)
    if units:
        unit_rect = QRectF(reading.left() + value_width + SPACING[4], reading.top(),
                           max(0.0, reading.width() - value_width - SPACING[4]),
                           reading.height())
        _text(painter, unit_rect, units, size=FONT["xs"],
              color=token("mutedForeground"), flags=Qt.AlignLeft | Qt.AlignVCenter)


def paint_attitude(painter, rect, props, ctx):
    """ShAttitude: sky over ground, rolled and pitched, aircraft symbol fixed."""
    pitch = _number(props, "pitch", 0.0)
    roll = _number(props, "roll", 0.0)
    per_degree = _number(props, "pixelsPerDegree", 4.0)

    painter.save()
    path = QPainterPath()
    path.addRect(rect)
    painter.setClipPath(path)
    painter.fillRect(rect, efis("panel"))

    centre = rect.center()
    painter.translate(centre)
    painter.rotate(-roll)
    painter.translate(0, pitch * per_degree)

    # Oversized so a rolled horizon still covers the corners.
    reach = max(rect.width(), rect.height()) * 1.6
    painter.fillRect(QRectF(-reach, -reach, reach * 2, reach), efis("sky"))
    painter.fillRect(QRectF(-reach, 0, reach * 2, reach), efis("ground"))
    painter.setPen(QPen(efis("line"), 2))
    painter.drawLine(QPointF(-reach, 0), QPointF(reach, 0))

    for degrees in (-20, -15, -10, -5, 5, 10, 15, 20):
        major = degrees % 10 == 0
        y = -degrees * per_degree
        half = 35 if major else 18
        painter.setPen(QPen(efis("line"), 2))
        painter.drawLine(QPointF(-half, y), QPointF(half, y))
        if major:
            _text(painter, QRectF(-half - 34, y - 8, 28, 16), abs(degrees),
                  size=FONT["xs"], color=efis("text"),
                  flags=Qt.AlignRight | Qt.AlignVCenter, elide=False)
    painter.restore()

    # Case-fixed marks: bank scale and the aircraft symbol.
    painter.save()
    painter.setClipPath(path)
    radius = min(rect.width(), rect.height()) * 0.44
    painter.setPen(QPen(efis("line"), 2))
    for mark in (-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60):
        angle = math.radians(mark - 90)
        inner = radius - (12 if mark % 30 == 0 else 7)
        painter.drawLine(
            QPointF(centre.x() + math.cos(angle) * radius,
                    centre.y() + math.sin(angle) * radius),
            QPointF(centre.x() + math.cos(angle) * inner,
                    centre.y() + math.sin(angle) * inner))
    wing = min(46.0, rect.width() * 0.22)
    painter.setPen(QPen(efis("aircraft"), 3))
    painter.drawLine(QPointF(centre.x() - wing, centre.y()),
                     QPointF(centre.x() - wing / 3, centre.y()))
    painter.drawLine(QPointF(centre.x() + wing / 3, centre.y()),
                     QPointF(centre.x() + wing, centre.y()))
    painter.setBrush(QBrush(efis("aircraft")))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(centre, 3.0, 3.0)
    painter.restore()


def paint_tape(painter, rect, props, ctx):
    """ShTape: a moving scale with the current value boxed at the centre."""
    minimum = _number(props, "minimumValue", 0.0)
    maximum = _number(props, "maximumValue", 200.0)
    value = max(minimum, min(maximum, _number(props, "value", 0.0)))
    step = max(1.0, _number(props, "step", 10.0))
    span = max(1.0, _number(props, "span", 60.0))
    left_side = _prop(props, "side", "left") == "left"

    caption = " ".join(part for part in (str(_prop(props, "label", "")),
                                         str(_prop(props, "units", ""))) if part)
    # The caption sits under the scale, not over it. Drawn on top of the ticks
    # it landed on whichever label happened to be lowest, which reads as a
    # corrupted number rather than as two overlapping strings.
    caption_band = 16.0 if caption else 0.0
    scale = QRectF(rect.left(), rect.top(), rect.width(),
                   max(1.0, rect.height() - caption_band))

    painter.save()
    path = QPainterPath()
    path.addRect(rect)
    painter.setClipPath(path)
    ground = efis("panel")
    ground.setAlphaF(0.85)
    painter.fillRect(rect, ground)

    per_unit = scale.height() / span
    first = (round(value / step) - int(span / step / 2) - 1) * step
    tick = first
    while tick <= first + span + step * 2:
        if minimum <= tick <= maximum:
            y = scale.center().y() - (tick - value) * per_unit
            if y < scale.top() or y > scale.bottom():
                tick += step
                continue
            painter.setPen(QPen(efis("line"), 2))
            if left_side:
                painter.drawLine(QPointF(rect.right() - 10, y), QPointF(rect.right(), y))
                label = QRectF(rect.left(), y - 8, rect.width() - 14, 16)
                flags = Qt.AlignRight | Qt.AlignVCenter
            else:
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.left() + 10, y))
                label = QRectF(rect.left() + 14, y - 8, rect.width() - 14, 16)
                flags = Qt.AlignLeft | Qt.AlignVCenter
            _text(painter, label, f"{tick:g}", size=FONT["xs"], color=efis("text"),
                  flags=flags, elide=False)
        tick += step

    box = QRectF(rect.left(), scale.center().y() - 13, rect.width(), 26)
    painter.setBrush(QBrush(efis("panel")))
    painter.setPen(QPen(efis("line"), 1))
    painter.drawRect(box)
    _text(painter, box, f"{value:.0f}", size=FONT["lg"], color=efis("text"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter, elide=False)

    if caption:
        _text(painter, QRectF(rect.left(), scale.bottom(), rect.width(), caption_band),
              caption, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignCenter)
    painter.restore()


def paint_compass(painter, rect, props, ctx):
    """ShCompass: a rotating card under a fixed lubber line."""
    heading = _number(props, "heading", 0.0)
    bug = _number(props, "headingBug", -1.0)
    course = _number(props, "course", -1.0)

    diameter = min(rect.width(), rect.height())
    face = QRectF(0, 0, diameter, diameter)
    face.moveCenter(rect.center())
    painter.setBrush(QBrush(efis("panel")))
    painter.setPen(QPen(token("secondary"), 1))
    painter.drawEllipse(face)

    centre = face.center()
    radius = diameter / 2 - 4

    painter.save()
    painter.translate(centre)
    painter.rotate(-heading)
    for degrees in range(0, 360, 5):
        major = degrees % 30 == 0
        angle = math.radians(degrees - 90)
        inner = radius - (14 if major else 7)
        painter.setPen(QPen(efis("line"), 2 if major else 1))
        painter.drawLine(
            QPointF(math.cos(angle) * radius, math.sin(angle) * radius),
            QPointF(math.cos(angle) * inner, math.sin(angle) * inner))
        if major and radius > 40:
            caption = {0: "N", 90: "E", 180: "S", 270: "W"}.get(degrees, degrees // 10)
            painter.save()
            painter.translate(math.cos(angle) * (radius - 26),
                              math.sin(angle) * (radius - 26))
            painter.rotate(degrees)
            _text(painter, QRectF(-14, -9, 28, 18), caption, size=FONT["xs"],
                  color=efis("text"), flags=Qt.AlignCenter, elide=False)
            painter.restore()
    if course >= 0:
        painter.save()
        painter.rotate(course)
        painter.setPen(QPen(efis("nav"), 3))
        painter.drawLine(QPointF(0, -radius * 0.72), QPointF(0, radius * 0.72))
        painter.restore()
    if bug >= 0:
        painter.save()
        painter.rotate(bug)
        painter.setBrush(QBrush(efis("bug")))
        painter.setPen(Qt.NoPen)
        painter.drawRect(QRectF(-7, -radius, 14, 10))
        painter.restore()
    painter.restore()

    painter.setPen(QPen(efis("aircraft"), 2))
    painter.drawLine(QPointF(centre.x(), face.top()),
                     QPointF(centre.x(), face.top() + 14))
    painter.drawLine(QPointF(centre.x() - 15, centre.y()),
                     QPointF(centre.x() + 15, centre.y()))


def paint_vsi(painter, rect, props, ctx):
    """ShVSI: a bar from the zero line out to the current rate."""
    full = max(1.0, _number(props, "range", 2000.0))
    value = max(-full, min(full, _number(props, "value", 0.0)))

    _rounded(painter, rect, efis("panel"), RADIUS["sm"], token("secondary"), 1)
    # Same reservation as ShTape: the units caption owns the bottom strip.
    scale = QRectF(rect.left(), rect.top(), rect.width(),
                   max(1.0, rect.height() - 16.0))
    reach = scale.height() / 2 - 12
    for index in range(5):
        tick = full - index * (full / 2)
        y = scale.center().y() - (tick / full) * reach
        painter.setPen(QPen(efis("line"), 2 if tick == 0 else 1))
        length = 14 if abs(tick) == full or tick == 0 else 8
        painter.drawLine(QPointF(rect.left() + 4, y),
                         QPointF(rect.left() + 4 + length, y))
        if abs(tick) >= 1000:
            _text(painter, QRectF(rect.left() + 20, y - 8, 24, 16),
                  f"{abs(tick) / 1000:.0f}", size=FONT["xs"], color=efis("text"),
                  flags=Qt.AlignLeft | Qt.AlignVCenter, elide=False)

    y = scale.center().y() - (value / full) * reach
    painter.setBrush(QBrush(efis("caution") if abs(value) >= full else efis("normal")))
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRectF(rect.left() + 22, y - 1.5,
                            max(0.0, rect.width() - 26), 3))
    _text(painter, QRectF(rect.left(), scale.bottom(), rect.width(), 16),
          str(_prop(props, "units", "FPM")), size=FONT["xs"],
          color=token("mutedForeground"), flags=Qt.AlignCenter)


def paint_engine_gauge(painter, rect, props, ctx):
    """ShEngineGauge: banded arc and a needle. The bands are always visible --
    where the limits are is information even when the needle is nowhere near."""
    minimum = _number(props, "minimumValue", 0.0)
    maximum = _number(props, "maximumValue", 100.0)
    span = max(0.0001, maximum - minimum)
    value = max(minimum, min(maximum, _number(props, "value", 0.0)))

    dimension = min(rect.width(), rect.height())
    stroke = max(4.0, dimension * 0.11)
    square = QRectF(0, 0, dimension - stroke * 2.2, dimension - stroke * 2.2)
    square.moveCenter(rect.center())

    # QML sweeps 240 degrees clockwise from 150; Qt measures counter-clockwise
    # from 3 o'clock in 1/16th degrees.
    start, sweep = 150.0, 240.0

    def band(low, high, colour):
        a0 = (max(minimum, low) - minimum) / span
        a1 = (min(maximum, high) - minimum) / span
        if a1 <= a0:
            return
        painter.setPen(QPen(colour, stroke, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(square, int(-(start + sweep * a0) * 16),
                        int(-(sweep * (a1 - a0)) * 16))

    painter.setBrush(Qt.NoBrush)
    green_low = _number(props, "greenLow", 20.0)
    green_high = _number(props, "greenHigh", 70.0)
    caution_high = _number(props, "cautionHigh", 85.0)
    band(minimum, green_low, efis("caution"))
    band(green_low, green_high, efis("normal"))
    band(green_high, caution_high, efis("caution"))
    band(caution_high, maximum, efis("warning"))

    angle = math.radians(start + sweep * ((value - minimum) / span))
    centre = square.center()
    tip = QPointF(centre.x() + math.cos(angle) * (square.width() / 2 - stroke * 0.3),
                  centre.y() + math.sin(angle) * (square.height() / 2 - stroke * 0.3))
    painter.setPen(QPen(efis("line"), max(2.0, dimension * 0.025)))
    painter.drawLine(centre, tip)
    painter.setBrush(QBrush(efis("line")))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(centre, max(2.0, dimension * 0.03), max(2.0, dimension * 0.03))

    units = str(_prop(props, "units", ""))
    reading = f"{value:.0f}{' ' + units if units else ''}"
    _text(painter, QRectF(rect.left(), rect.bottom() - 32, rect.width(), 16), reading,
          size=FONT["sm"], color=efis("text"), weight=WEIGHT_SEMIBOLD,
          flags=Qt.AlignCenter)
    label = str(_prop(props, "label", ""))
    if label:
        _text(painter, QRectF(rect.left(), rect.bottom() - 16, rect.width(), 14),
              label, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignCenter)


def paint_annunciator(painter, rect, props, ctx):
    """ShAnnunciator: a caption lamp, dimmed rather than blank when unlit."""
    colour = _severity_color(_prop(props, "severity", "caution"))
    if _prop(props, "severity", "caution") == "advisory":
        colour = efis("normal")
    colour = _override_colour(props, "litColor") or colour
    lit = bool(_prop(props, "lit", True))
    if lit and bool(_prop(props, "glow", False)):
        _glow(painter, rect, colour, RADIUS["sm"])

    painter.save()
    painter.setOpacity(1.0 if lit else 0.35)
    _rounded(painter, rect, colour if lit else efis("panel"), RADIUS["sm"], colour, 1)
    painter.restore()
    painter.save()
    painter.setOpacity(1.0 if lit else 0.75)
    _text(painter, rect, _prop(props, "text", "CAPTION"), size=FONT["sm"],
          color=efis("panel") if lit else colour, weight=WEIGHT_SEMIBOLD,
          flags=Qt.AlignCenter)
    painter.restore()


def paint_flight_director(painter, rect, props, ctx):
    painter.fillRect(rect, efis("panel"))
    active = bool(_prop(props, "active", True))
    _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 18),
          _prop(props, "mode", "FD") if active else "FD OFF", size=FONT["xs"],
          color=efis("normal") if active else token("mutedForeground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
    if not active:
        return
    pitch_limit = max(.001, abs(_number(props, "pitchLimit", 15)))
    roll_limit = max(.001, abs(_number(props, "rollLimit", 30)))
    pitch = max(-pitch_limit, min(pitch_limit, _number(props, "pitchCommand", 0)))
    roll = max(-roll_limit, min(roll_limit, _number(props, "rollCommand", 0)))
    cx = rect.center().x() + roll / roll_limit * rect.width() * .32
    cy = rect.center().y() + pitch / pitch_limit * rect.height() * .32
    painter.setPen(QPen(efis("nav"), max(3.0, rect.height() * .035)))
    painter.drawLine(QPointF(rect.center().x()-rect.width()*.24, cy),
                     QPointF(rect.center().x()+rect.width()*.24, cy))
    painter.drawLine(QPointF(cx, rect.center().y()-rect.height()*.29),
                     QPointF(cx, rect.center().y()+rect.height()*.29))


def paint_turn_coordinator(painter, rect, props, ctx):
    _rounded(painter, rect, efis("panel"), RADIUS["sm"])
    cx, cy = rect.center().x(), rect.top()+rect.height()*.43
    radius = min(rect.width()*.38, rect.height()*.38)
    painter.setPen(QPen(efis("line"), 2)); painter.setBrush(Qt.NoBrush)
    painter.drawArc(QRectF(cx-radius, cy-radius, radius*2, radius*2), 0, 180*16)
    rate = _number(props, "turnRate", 0); standard = max(.001, abs(_number(props, "standardRate", 3)))
    painter.save(); painter.translate(cx, cy); painter.rotate(max(-2,min(2,rate/standard))*20)
    painter.setPen(QPen(efis("aircraft"), 3)); painter.drawLine(QPointF(-rect.width()*.21,0), QPointF(rect.width()*.21,0)); painter.drawLine(QPointF(0,-8),QPointF(0,8)); painter.restore()
    tube = QRectF(rect.left()+rect.width()*.22, rect.bottom()-24, rect.width()*.56, 16)
    _rounded(painter, tube, None, 8, efis("line"), 1)
    limit=max(.001,abs(_number(props,"slipLimit",1))); slip=max(-1,min(1,_number(props,"slip",0)/limit))
    ball_x=tube.center().x()+slip*(tube.width()-12)*.42
    painter.setBrush(QBrush(efis("line"))); painter.setPen(Qt.NoPen); painter.drawEllipse(QPointF(ball_x,tube.center().y()),6,6)


def paint_engine_bar(painter, rect, props, ctx):
    minimum=_number(props,"minimumValue",0); maximum=_number(props,"maximumValue",100); span=max(.001,maximum-minimum)
    value=max(minimum,min(maximum,_number(props,"value",0))); caution=_number(props,"cautionValue",80); warning=_number(props,"warningValue",90)
    colour=_override_colour(props,"barColor") or efis("warning" if value>=warning else "caution" if value>=caution else "normal")
    if _prop(props, "orientation", "vertical") == "horizontal":
        # A vitals row: label | thin rounded bar | value (ShEngineBar.qml "hrow").
        size = max(7, min(FONT["sm"], round(rect.height() * 0.5)))
        bar_h = round(min(10, max(4, rect.height() * 0.22)))
        label = str(_prop(props, "label", ""))
        reading = f"{value:.0f}{_prop(props, 'units', '')}"
        font = painter.font()
        font.setPixelSize(size)
        font.setWeight(WEIGHT_SEMIBOLD)
        value_w = min(QFontMetricsF(font).horizontalAdvance(reading) + 1, rect.width() * 0.25)
        font.setWeight(WEIGHT_MEDIUM)
        label_w = min(QFontMetricsF(font).horizontalAdvance(label) + 1, rect.width() * 0.3) if label else 0
        if label:
            _text(painter, QRectF(rect.left(), rect.top(), label_w, rect.height()), label, size=size,
                  color=efis("text"), weight=WEIGHT_MEDIUM)
        _text(painter, QRectF(rect.right() - value_w, rect.top(), value_w, rect.height()), reading, size=size,
              color=efis("text"), weight=WEIGHT_SEMIBOLD, flags=Qt.AlignRight | Qt.AlignVCenter)
        x0 = rect.left() + (label_w + 8 if label else 0)
        track = QRectF(x0, rect.center().y() - bar_h / 2, max(1.0, rect.right() - value_w - 8 - x0), bar_h)
        line = QColor(efis("line"))
        line.setAlphaF(0.18)
        _rounded(painter, track, line, bar_h / 2)
        fill = QRectF(track.left(), track.top(), round(track.width() * (value - minimum) / span), bar_h)
        if fill.width() > 0:
            if _prop(props, "glow", False) in (True, "true", "True", 1, "1"):
                _glow(painter, fill, colour, bar_h / 2)
            _rounded(painter, fill, colour, bar_h / 2)
        return
    _rounded(painter, rect, efis("panel"), RADIUS["sm"])
    _text(painter,QRectF(rect.left(),rect.top(),rect.width(),22),_prop(props,"label","N1"),size=FONT["sm"],color=efis("text"),weight=WEIGHT_SEMIBOLD,flags=Qt.AlignCenter)
    well=QRectF(rect.center().x()-9,rect.top()+25,18,max(10,rect.height()-50))
    painter.setPen(QPen(efis("line"),1)); painter.setBrush(Qt.NoBrush); painter.drawRect(well)
    fraction=(value-minimum)/span
    if _prop(props, "glow", False) in (True, "true", "True", 1, "1") and fraction > 0:
        _glow(painter, QRectF(well.left()+2,well.bottom()-2-(well.height()-4)*fraction,well.width()-4,(well.height()-4)*fraction), colour, 0)
    painter.fillRect(QRectF(well.left()+2,well.bottom()-2-(well.height()-4)*fraction,well.width()-4,(well.height()-4)*fraction),colour)
    reading=f"{value:.0f}{_prop(props,'units','')}"; _text(painter,QRectF(rect.left(),rect.bottom()-22,rect.width(),20),reading,size=FONT["xs"],color=colour,weight=WEIGHT_SEMIBOLD,flags=Qt.AlignCenter)


def paint_fuel_quantity(painter, rect, props, ctx):
    _rounded(painter, rect, efis("panel"), RADIUS["sm"])
    capacity=max(.001,_number(props,"capacity",100)); low=_number(props,"lowLevel",15)
    _text(painter,QRectF(rect.left(),rect.top(),rect.width(),20),"FUEL QTY",size=FONT["sm"],color=efis("text"),weight=WEIGHT_SEMIBOLD,flags=Qt.AlignCenter)
    for x,name,key in ((rect.center().x()-34,"L","leftValue"),(rect.center().x()+34,"R","rightValue")):
        value=max(0,min(capacity,_number(props,key,0))); colour=efis("caution") if value<=low else efis("normal")
        _text(painter,QRectF(x-22,rect.top()+20,44,14),name,size=FONT["xs"],color=token("mutedForeground"),flags=Qt.AlignCenter)
        well=QRectF(x-22,rect.top()+35,44,max(20,rect.height()-60)); painter.setPen(QPen(efis("line"),1)); painter.setBrush(Qt.NoBrush); painter.drawRect(well)
        painter.fillRect(QRectF(well.left()+2,well.bottom()-2-(well.height()-4)*value/capacity,well.width()-4,(well.height()-4)*value/capacity),colour)
        _text(painter,QRectF(x-30,rect.bottom()-22,60,18),f"{value:.0f} {_prop(props,'units','KG')}",size=FONT["xs"],color=colour,flags=Qt.AlignCenter)


def paint_slider(painter, rect, props, ctx):
    """ShSlider: a horizontal track with a filled portion, handle, and value text."""
    value = _number(props, "value", 50.0)
    min_val = _number(props, "minValue", 0.0)
    max_val = _number(props, "maxValue", 100.0)
    span = max(0.0001, max_val - min_val)
    fraction = max(0.0, min(1.0, (value - min_val) / span))
    label = str(_prop(props, "label", ""))
    unit = str(_prop(props, "unit", ""))

    # Track
    track = QRectF(rect.left(), rect.top() + rect.height() * 0.35,
                   rect.width(), rect.height() * 0.2)
    _pill(painter, track, token("secondary"))

    # Fill
    fill = QRectF(track.left(), track.top(), track.width() * fraction, track.height())
    _pill(painter, fill, token("primary"))

    # Handle
    handle_r = max(2, track.height() * 0.35)
    handle_x = track.left() + (track.width() - handle_r * 2) * fraction
    handle_y = track.top() + track.height() / 2 - handle_r
    handle = QRectF(handle_x, handle_y, handle_r * 2, handle_r * 2)
    painter.setBrush(QBrush(token("background")))
    painter.setPen(QPen(token("primary"), 2))
    painter.drawEllipse(handle)

    # Value text
    value_text = f"{value:g}{' ' + unit if unit else ''}"
    _text(painter, QRectF(rect.left(), rect.top(), rect.width(),
                          rect.height() * 0.35), value_text,
          size=FONT["base"], color=token("foreground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)

    if label:
        _text(painter, QRectF(rect.left(), rect.bottom() - rect.height() * 0.35,
                              rect.width(), rect.height() * 0.35),
              label, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignCenter)


def paint_toggle(painter, rect, props, ctx):
    """ShToggle: a switch with on/off label text."""
    checked = bool(_prop(props, "checked", False))
    label = str(_prop(props, "label", ""))

    # Switch pill
    sw_w, sw_h = 40.0, 22.0
    sw_x = rect.left() + (rect.width() - sw_w) / 2
    sw_y = rect.top() + (rect.height() - sw_h) / 2
    sw_rect = QRectF(sw_x, sw_y, sw_w, sw_h)
    _pill(painter, sw_rect, token("primary") if checked else token("secondary"))

    # Thumb
    thumb_r = sw_h / 2 - 2
    thumb_x = sw_x + (not checked) * 2 + (sw_w - thumb_r * 2) * (1 if checked else 0)
    thumb = QRectF(sw_x + 2 + thumb_r, sw_y + 2 + thumb_r, thumb_r * 2, thumb_r * 2)
    if checked:
        thumb = QRectF(sw_x + sw_w - thumb_r * 2 - 2, sw_y + 2, thumb_r * 2, thumb_r * 2)
    painter.setBrush(QBrush(token("background")))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(thumb)

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(),
                              rect.height() * 0.5), label,
              size=FONT["sm"], color=token("foreground"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_checkbox(painter, rect, props, ctx):
    """ShCheckbox: a checkmark box with label."""
    checked = bool(_prop(props, "checked", False))
    label = str(_prop(props, "label", ""))

    box_w, box_h = 20.0, 20.0
    box_x = rect.left() + (rect.width() - box_w - SPACING[8]) / 2
    box_y = rect.top() + (rect.height() - box_h) / 2

    _rounded(painter, QRectF(box_x, box_y, box_w, box_h),
             token("primary") if checked else token("background"),
             RADIUS["sm"],
             token("primary") if checked else token("input"), 1)

    if checked:
        font = painter.font()
        font.setPixelSize(14)
        font.setWeight(Font.Bold)
        painter.setFont(font)
        painter.setPen(QPen(token("primaryForeground")))
        painter.drawText(QRectF(box_x, box_y, box_w, box_h), Qt.AlignCenter, "\u2713")

    if label:
        label_rect = QRectF(box_x + box_w + SPACING[8], rect.top(),
                            rect.width() - box_w - SPACING[8], rect.height())
        _text(painter, label_rect, label, size=FONT["sm"],
              color=token("foreground"), weight=WEIGHT_MEDIUM)


def paint_select(painter, rect, props, ctx):
    """ShSelect: a dropdown button with current selection and chevron."""
    placeholder = str(_prop(props, "placeholder", "Select..."))
    current_idx = int(_number(props, "currentIndex", 0))
    label = str(_prop(props, "label", ""))

    _rounded(painter, rect, QColor(Qt.transparent), RADIUS["md"],
             token("input"), 1)

    inner = rect.adjusted(SPACING[12], 0, -30, 0)
    if current_idx > 0:
        _text(painter, inner, placeholder, size=FONT["sm"],
              color=token("foreground"), flags=Qt.AlignLeft | Qt.AlignVCenter)
    else:
        _text(painter, inner, placeholder, size=FONT["sm"],
              color=token("mutedForeground"), flags=Qt.AlignLeft | Qt.AlignVCenter)

    _text(painter, QRectF(inner.right(), rect.top(), 20, rect.height()),
          "\u25BC", size=10, color=token("mutedForeground"), flags=Qt.AlignCenter)

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 14),
              label, size=FONT["xs"], color=token("foreground"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_num_input(painter, rect, props, ctx):
    """ShNumInput: +/- buttons flanking a numeric value display."""
    value = _number(props, "value", 0.0)
    unit = str(_prop(props, "unit", ""))
    label = str(_prop(props, "label", ""))

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 14),
              label, size=FONT["xs"], color=token("foreground"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)

    y_start = rect.top() + 2 if label else rect.top()
    y_end = rect.bottom()
    row_h = y_end - y_start
    btn_w = row_h * 0.9

    # Decrement button
    dec_rect = QRectF(rect.left() + 4, y_start + 1, btn_w, row_h - 2)
    _rounded(painter, dec_rect, QColor(Qt.transparent), RADIUS["md"],
             token("input"), 1)
    _text(painter, dec_rect, "\u2212", size=FONT["base"],
          color=token("foreground"), flags=Qt.AlignCenter)

    # Value box
    val_rect = QRectF(dec_rect.right() + 2, y_start + 1,
                      (row_h * 2.5), row_h - 2)
    _rounded(painter, val_rect, token("background"), RADIUS["md"],
             token("input"), 1)
    display_text = f"{value:g}" if unit == "" else f"{value:g} {unit}"
    _text(painter, val_rect.adjusted(4, 0, -4, 0), display_text,
          size=FONT["sm"], color=token("foreground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)

    # Increment button
    inc_rect = QRectF(val_rect.right() + 2, y_start + 1, btn_w, row_h - 2)
    _rounded(painter, inc_rect, QColor(Qt.transparent), RADIUS["md"],
             token("input"), 1)
    _text(painter, inc_rect, "+", size=FONT["base"],
          color=token("foreground"), flags=Qt.AlignCenter)


def paint_num_display(painter, rect, props, ctx):
    """ShNumDisplay: large numeric readout with unit and status bar."""
    value = _number(props, "value", 0.0)
    unit = str(_prop(props, "unit", ""))
    label = str(_prop(props, "label", ""))
    unit_text = f"{value:g}{' ' + unit if unit else ''}"

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 12),
              label, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignCenter)

    _text(painter, QRectF(rect.left(), rect.top() + (12 if label else 0),
                          rect.width(), rect.height() * 0.5),
          unit_text, size=FONT["xxxl"], color=token("success"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)

    bar = QRectF(rect.left() + rect.width() * 0.3, rect.bottom() - 8,
                 rect.width() * 0.4, 3)
    _rounded(painter, bar, token("success"), 2)


def paint_analog_display(painter, rect, props, ctx):
    """ShAnalogDisplay: horizontal bar with value indicator and zone markers."""
    value = _number(props, "value", 50.0)
    min_val = _number(props, "minValue", 0.0)
    max_val = _number(props, "maxValue", 100.0)
    span = max(0.0001, max_val - min_val)
    fraction = max(0.0, min(1.0, (value - min_val) / span))
    norm_low = _number(props, "normLow", 20.0)
    norm_high = _number(props, "normHigh", 80.0)
    label = str(_prop(props, "label", ""))

    # Track
    track = QRectF(rect.left(), rect.top() + rect.height() * 0.25,
                   rect.width(), rect.height() * 0.35)
    _rounded(painter, track, token("secondary"), RADIUS["sm"])

    # Fill
    fill = QRectF(track.left(), track.top(),
                  track.width() * fraction, track.height())
    _rounded(painter, fill, token("success"), RADIUS["sm"])

    # Value marker
    marker_x = track.left() + track.width() * fraction - 1
    marker = QRectF(marker_x, track.top() - 2, 2, track.height() + 4)
    painter.setBrush(QBrush(token("foreground")))
    painter.setPen(Qt.NoPen)
    painter.drawRect(marker)

    # Value text
    _text(painter, QRectF(rect.left(), rect.bottom() - rect.height() * 0.2,
                          rect.width(), rect.height() * 0.2),
          f"{value:g}", size=FONT["sm"], color=token("foreground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 12),
              label, size=FONT["xs"], color=token("success"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_trend_chart(painter, rect, props, ctx):
    """ShTrendChart: a small line chart with area fill and grid lines."""
    if str(props.get("series") or "").strip():
        # The multi-series dashboard view (dashboard_previews.py).
        from designer.canvas.dashboard_previews import paint_trend_series
        return paint_trend_series(painter, rect, props, ctx)
    min_val = _number(props, "minValue", 0.0)
    max_val = _number(props, "maxValue", 100.0)
    warn_low = _number(props, "warningLow", 20.0)
    warn_high = _number(props, "warningHigh", 80.0)
    label = str(_prop(props, "label", ""))

    chart_top = rect.top() + (12 if label else 0)
    chart = QRectF(rect.left(), chart_top, rect.width(), rect.height() - (12 if label else 0))

    # Background
    _rounded(painter, chart, token("background"), RADIUS["sm"],
             token("border"), 1)

    # Warning zone
    warn_y = chart.bottom() - (chart.height() * (1 - (warn_high - warn_low) / max(0.001, max_val - min_val)))
    warn_h = chart.height() * (warn_high - warn_low) / max(0.001, max_val - min_val)
    warn_zone = QRectF(chart.left(), chart.top() + chart.height() - warn_h - (chart.height() * (max_val - warn_high) / max(0.001, max_val - min_val)),
                       chart.width(), warn_h)
    warn_color = QColor(token("warning"))
    warn_color.setAlphaF(0.08)
    _rounded(painter, warn_zone, warn_color, 2)

    # Grid lines
    painter.setPen(QPen(token("border"), 1))
    for i in range(1, 4):
        gy = chart.top() + (chart.height() * i / 4)
        painter.drawLine(chart.left(), gy, chart.right(), gy)

    values = list(_prop(props, "data", []) or [])
    if len(values) < 2:
        _text(painter, chart, "No trend data", size=FONT["sm"],
              color=token("mutedForeground"), flags=Qt.AlignCenter)
        return
    pts = []
    for i, y_val in enumerate(values):
        x = chart.left() + (chart.width() * i / max(1, len(values) - 1))
        y = chart.bottom() - (chart.height() * (y_val - min_val) / max(0.001, max_val - min_val))
        pts.append(QPointF(x, y))

    # Fill area
    painter.save()
    path = QPainterPath()
    path.moveTo(pts[0].x(), chart.bottom())
    for pt in pts:
        path.lineTo(pt.x(), pt.y())
    path.lineTo(pts[-1].x(), chart.bottom())
    path.closeSubpath()
    grad = painter.background()
    grad = QBrush(QColor(token("primary").name()) if isinstance(token("primary"), QColor) else QColor("#006fee"))
    grad.setColor(QColor(grad.color().red(), grad.color().green(), grad.color().blue(), 40))
    painter.fillPath(path, grad)
    painter.restore()

    # Line
    painter.setPen(QPen(token("primary"), 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawPolyline(QPolygonF(pts))

    # Last point dot
    if pts:
        last = pts[-1]
        painter.setBrush(QBrush(token("primary")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(last.x() - 3, last.y() - 3, 6, 6)

    if label:
        _text(painter, QRectF(rect.left(), rect.top(), rect.width(), 12),
              label, size=FONT["xs"], color=token("mutedForeground"),
              flags=Qt.AlignLeft | Qt.AlignVCenter)


def paint_alarm_table(painter, rect, props, ctx):
    """ShAlarmTable: an alarm list with header and sample rows."""
    if str(props.get("columns") or "").strip() or str(props.get("sampleRows") or "").strip():
        # The table view (dashboard_previews.py).
        from designer.canvas.dashboard_previews import paint_alarm_table_view
        return paint_alarm_table_view(painter, rect, props, ctx)
    title = str(_prop(props, "title", "Active Alarms"))
    max_visible = int(_number(props, "maxVisible", 6))
    row_h = max(16, min(30, (rect.height() - 36) / max(1, max_visible)))

    # Header
    header_h = min(26, rect.height() * 0.15)
    header = QRectF(rect.left(), rect.top(), rect.width(), header_h)
    _rounded(painter, header, token("secondary"), RADIUS["sm"])
    _text(painter, header.adjusted(8, 0, -50, 0), title, size=FONT["sm"],
          color=token("foreground"), weight=WEIGHT_SEMIBOLD,
          flags=Qt.AlignLeft | Qt.AlignVCenter)

    alarms = list(_prop(props, "alarms", []) or [])
    # Badge with count
    painter.setBrush(QBrush(token("secondary")))
    painter.setPen(Qt.NoPen)
    badge_rect = QRectF(header.right() - 42, header.top() + 4, 30, header_h - 8)
    painter.drawRoundedRect(badge_rect, RADIUS["sm"], RADIUS["sm"])
    _text(painter, badge_rect, str(len(alarms)), size=FONT["xs"], color=token("foreground"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)

    # Alarm rows
    row_start = header.bottom()
    if not alarms:
        _text(painter, QRectF(rect.left(), row_start, rect.width(), rect.bottom() - row_start),
              "No active alarms", size=FONT["sm"], color=token("mutedForeground"),
              flags=Qt.AlignCenter)
        return

    for i, alarm in enumerate(alarms[:max_visible]):
        severity = alarm.get("severity", "ok")
        color = (token("destructive") if severity == "fault" else
                 token("warning") if severity in ("warning", "caution") else
                 token("mutedForeground"))
        msg = alarm.get("message", "Alarm")
        y = row_start + i * row_h
        row = QRectF(rect.left(), y, rect.width(), row_h)
        painter.setPen(QPen(token("border"), 1, Qt.DashLine))
        painter.drawLine(rect.left(), y, rect.right(), y)
        _rounded(painter, row, QColor(Qt.transparent), 0)

        # Severity dot
        dot = QRectF(rect.left() + 8, y + row_h * 0.3, 6, row_h * 0.4)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(dot)

        # Message
        _text(painter, QRectF(rect.left() + 20, y, rect.width() - 20, row_h),
              msg, size=FONT["xs"], color=token("foreground"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignLeft | Qt.AlignVCenter)


def animated_placeholder_geometry(width, height):
    """ShAnimatedImage.qml's placeholder layout (w_shanimatedimage.c's ph_geom):
    (glyph height, glyph width, text px, gap, top), all in whole pixels."""
    def px(value):                         # Math.round / lround, not banker's
        return int(math.floor(value + 0.5))
    s = max(1.0, min(width, height))
    glyph = max(12, min(64, px(s * 0.30)))
    glyph_w = px(glyph * 1.35)
    text_px = max(10, min(18, px(s * 0.11)))
    gap = px(glyph * 0.18)
    top = px((height - (glyph + gap + text_px)) / 2)
    return glyph, glyph_w, text_px, gap, top


def paint_animated_image(painter, rect, props, ctx):
    """ShAnimatedImage with nothing to play: the muted card, a framed play
    glyph and "GIF" -- what the QML and the panel draw for an empty or
    unreadable source. The canvas item plays the real GIF over this when the
    file is at hand (designer_view.DesignerItem._paint_movie)."""
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    _rounded(painter, QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), token("muted"), 6,
             token("border"), 1)
    glyph, glyph_w, text_px, gap, top = animated_placeholder_geometry(rect.width(), rect.height())
    ink = token("mutedForeground")
    frame = QRectF(rect.left() + round((rect.width() - glyph_w) / 2), rect.top() + top, glyph_w, glyph)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(ink, 2))
    painter.drawRoundedRect(frame.adjusted(1, 1, -1, -1), 3, 3)
    th = glyph * 0.45
    tw = th * 0.85
    cx, cy = frame.center().x(), frame.center().y()
    painter.setBrush(QBrush(ink))
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(QPolygonF([QPointF(cx - tw / 3, cy - th / 2), QPointF(cx - tw / 3, cy + th / 2),
                                   QPointF(cx + 2 * tw / 3, cy)]))
    _text(painter, QRectF(rect.left(), rect.top() + top + glyph + gap, rect.width(), text_px),
          "GIF", size=text_px, color=ink, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter, elide=False)


def process_value_text(props):
    """ShProcessValue's box text: toFixed(decimals) for a number (or a
    numeric string) when decimals >= 0, else the value as given."""
    value = props.get("value", 0)
    if value is None:
        return "--"
    try:
        decimals = int(props.get("decimals", -1))
    except (TypeError, ValueError):
        decimals = -1
    number = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            number = None
    if number is not None and not math.isfinite(number):
        number = None
    if decimals >= 0 and number is not None:
        return f"{number:.{decimals}f}"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def paint_process_value(painter, rect, props, ctx):
    """ShProcessValue: a SCADA reading row -- label, optional sparkline box,
    dark inset value box with right-aligned digits, unit column. The column
    shares are ShProcessValue.qml's / w_shprocessvalue.c's."""
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    px = lambda v: int(math.floor(v + 0.5))           # Math.round
    value_px = max(9, min(18, px(h * 0.56)))
    label_px = max(8, min(15, px(h * 0.46)))
    unit_px = max(8, min(14, px(h * 0.42)))
    inset = max(1, px(h * 0.08))
    box_h = max(6, px(h) - 2 * inset)
    unit = str(props.get("unit") or "")
    trend = bool(props.get("trend", False))
    unit_w = px(w * 0.22) if unit else 0
    unit_gap = 6 if unit else 0
    text = process_value_text(props)
    font = QFont(painter.font())
    font.setPixelSize(value_px)
    font.setWeight(WEIGHT_SEMIBOLD)
    digits_w = math.ceil(QFontMetricsF(font).horizontalAdvance(text))
    box_w = min(max(digits_w + 16, px(w * 0.26)), max(16, px(w) - unit_w - unit_gap))
    box_x = px(w) - unit_w - unit_gap - box_w
    spark_w = px(w * 0.18) if trend else 0
    spark_x = box_x - 6 - spark_w
    label_w = max(0, (spark_x if trend else box_x) - 6)
    box_colour = _override_colour(props, "boxColor") or QColor("#0a0d0b")
    border = QColor("#3a3f45")
    left, top = rect.left(), rect.top()
    bevel = bool(props.get("bevel", False))

    def bevel_lines(x, bw):
        # The bevel: a darker line along the top, a lighter one along the
        # bottom, inside the border (ShProcessValue.qml).
        if bevel and bw >= 6 and box_h >= 4:
            painter.fillRect(QRectF(left + x + 2, top + inset + 1, bw - 4, 1), shade(box_colour, -70))
            painter.fillRect(QRectF(left + x + 2, top + inset + box_h - 2, bw - 4, 1), shade(box_colour, 20))

    if label_w > 0:
        _text(painter, QRectF(left, top, label_w, h), props.get("label", "Value"), size=label_px,
              color=token("foreground"))
    if trend:
        spark = QRectF(left + spark_x + 0.5, top + inset + 0.5, spark_w - 1, box_h - 1)
        _rounded(painter, spark, box_colour, 3, border, 1)
        bevel_lines(spark_x, spark_w)
        ys = (0.30, 0.52, 0.40, 0.62, 0.48, 0.70, 0.58, 0.80)
        pad_x, pad_y = 4, max(3, px(box_h * 0.16))
        pw, ph = spark_w - 2 * pad_x, box_h - 2 * pad_y
        if pw > 0 and ph > 0:
            points = [QPointF(left + spark_x + pad_x + pw * i / (len(ys) - 1),
                              top + inset + pad_y + ph * (1 - y)) for i, y in enumerate(ys)]
            pen = QPen(_override_colour(props, "trendColor") or QColor("#f5a524"), 2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPolyline(QPolygonF(points))
    _rounded(painter, QRectF(left + box_x + 0.5, top + inset + 0.5, box_w - 1, box_h - 1),
             box_colour, 3, border, 1)
    bevel_lines(box_x, box_w)
    try:
        number = float(text) if text != "--" else None
    except ValueError:
        number = None
    above, below = _number(props, "warnAbove", 0.0), _number(props, "warnBelow", 0.0)
    warns = number is not None and ((above != 0 and number > above) or (below != 0 and number < below))
    colour = token("warning") if warns else (_override_colour(props, "valueColor") or QColor("#3ee05a"))
    _text(painter, QRectF(left + box_x + 4, top, max(1, box_w - 12), h), text, size=value_px,
          color=colour, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignRight | Qt.AlignVCenter)
    if unit:
        _text(painter, QRectF(left + box_x + box_w + unit_gap, top, unit_w, h), unit, size=unit_px,
              color=token("mutedForeground"))


_PAINTERS = {
    "Text": paint_text,
    "ShButton": paint_button,
    "ShInput": paint_input,
    "Rectangle": paint_rectangle,
    "ShCard": paint_card,
    "ShValueTile": paint_value_tile,
    "ShStatDot": paint_stat_dot,
    "ShProgress": paint_progress,
    "ShAlert": paint_alert,
    "ShGauge": paint_gauge,
    "ShTabs": paint_tabs,
    "Row": lambda p, r, props, c: _paint_container(p, r, props, c, "Row"),
    "Column": lambda p, r, props, c: _paint_container(p, r, props, c, "Column"),
    "Grid": lambda p, r, props, c: _paint_container(p, r, props, c, "Grid"),
    "Item": lambda p, r, props, c: _paint_container(p, r, props, c, "Page"),
    "ShDataField": paint_data_field,
    "ShAttitude": paint_attitude,
    "ShTape": paint_tape,
    "ShCompass": paint_compass,
    "ShVSI": paint_vsi,
    "ShEngineGauge": paint_engine_gauge,
    "ShAnnunciator": paint_annunciator,
    "ShFlightDirector": paint_flight_director,
    "ShTurnCoordinator": paint_turn_coordinator,
    "ShEngineBar": paint_engine_bar,
    "ShFuelQuantity": paint_fuel_quantity,
    # Industrial widgets
    "ShSlider": paint_slider,
    "ShToggle": paint_toggle,
    "ShCheckbox": paint_checkbox,
    "ShSelect": paint_select,
    "ShNumInput": paint_num_input,
    "ShNumDisplay": paint_num_display,
    "ShAnalogDisplay": paint_analog_display,
    "ShTrendChart": paint_trend_chart,
    "ShAlarmTable": paint_alarm_table,
    "ShProcessValue": paint_process_value,
    # The placeholder only; the canvas item plays the GIF itself.
    "ShAnimatedImage": paint_animated_image,
}
# Automotive painters live in their own module; see automotive_previews.py.
from designer.canvas import automotive_previews  # noqa: E402
_PAINTERS.update(automotive_previews.PAINTERS)
# Rail painters: designer/canvas/rail_previews.py, one module per type.
from designer.canvas import rail_previews  # noqa: E402
_PAINTERS.update(rail_previews.PAINTERS)
# Industrial dashboard painters (KPI tile, status row): dashboard_previews.py.
from designer.canvas import dashboard_previews  # noqa: E402
_PAINTERS.update(dashboard_previews.PAINTERS)


def painter_for(widget_type):
    """The preview painter for a type, or None when there is no preview.

    Image is deliberately absent: it needs the project directory to resolve a
    relative source, which only the canvas item holds, so it stays there.
    """
    return _PAINTERS.get(widget_type)


def has_preview(widget_type) -> bool:
    return widget_type in _PAINTERS
