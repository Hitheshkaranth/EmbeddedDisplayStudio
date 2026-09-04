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
from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen

# ---------------------------------------------------------------------------
# Theme tokens -- ui/qml/Shadcn/Theme.qml
# ---------------------------------------------------------------------------

DARK = {
    "background": "#09090b", "foreground": "#ecedee",
    "card": "#18181b", "cardForeground": "#ecedee",
    "primary": "#006fee", "primaryForeground": "#ffffff",
    "secondary": "#27272a", "secondaryForeground": "#ecedee",
    "muted": "#27272a", "mutedForeground": "#a1a1aa",
    "accent": "#3f3f46", "accentForeground": "#ffffff",
    "destructive": "#f31260", "destructiveForeground": "#ffffff",
    "border": "#00000000", "input": "#27272a", "ring": "#006fee",
    "success": "#17c964", "successForeground": "#f8fafc",
    "warning": "#f5a524", "warningForeground": "#f8fafc",
}

LIGHT = {
    "background": "#ffffff", "foreground": "#020817",
    "card": "#ffffff", "cardForeground": "#020817",
    "primary": "#0f172a", "primaryForeground": "#f8fafc",
    "secondary": "#f1f5f9", "secondaryForeground": "#0f172a",
    "muted": "#f1f5f9", "mutedForeground": "#64748b",
    "accent": "#f1f5f9", "accentForeground": "#0f172a",
    "destructive": "#ef4444", "destructiveForeground": "#f8fafc",
    "border": "#e2e8f0", "input": "#e2e8f0", "ring": "#020817",
    "success": "#22c55e", "successForeground": "#f8fafc",
    "warning": "#f59e0b", "warningForeground": "#f8fafc",
}

# Theme.radius* and Theme.fontSize*
RADIUS = {"sm": 4, "md": 12, "lg": 16, "xl": 20, "full": 9999}
FONT = {"xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20, "xxl": 24, "xxxl": 30}
SPACING = {4: 4, 8: 8, 12: 12, 16: 16, 24: 24, 32: 32}

# Theme.fontMedium / fontSemibold, in QFont weights.
WEIGHT_MEDIUM = QFont.Medium
WEIGHT_SEMIBOLD = QFont.DemiBold

# The palette every painter reads. Swapped by set_theme_mode.
_TOKENS = dict(DARK)


def set_theme_mode(mode: str) -> None:
    """Point the painters at the light or dark token set."""
    global _TOKENS
    _TOKENS = dict(LIGHT if mode == "light" else DARK)


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
    """ShCard: the surface other components are composed onto."""
    width = int(_number(props, "borderWidth", 1))
    _rounded(painter, rect, QColor(_prop(props, "color", _TOKENS["card"])),
             _number(props, "radius", RADIUS["xl"]),
             QColor(_prop(props, "borderColor", "#27272a")) if width else None, width)


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
}


def painter_for(widget_type):
    """The preview painter for a type, or None when there is no preview.

    Image is deliberately absent: it needs the project directory to resolve a
    relative source, which only the canvas item holds, so it stays there.
    """
    return _PAINTERS.get(widget_type)


def has_preview(widget_type) -> bool:
    return widget_type in _PAINTERS
