"""Canvas painter for ShStatusCard -- mirrors ui/qml/Shadcn/ShStatusCard.qml at rest
(and native/hmi-ui/src/widgets/w_shstatuscard.c).

A rounded dark card: the subsystem icon top-left in ``iconColor``, a glowing
state dot top-right, the title (up to two lines, the second smaller and muted)
over the status, bold and coloured by ``state``. Scales with
s = min(w/240, h/180); long text shrinks to 60 % and then elides.
"""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen

from designer.canvas.widget_previews import _prop

_ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                         "ui", "qml", "Shadcn", "icons"))
_ICON_CACHE = {}

CARD = "#26262c"
BORDER = "#3a3a44"
TITLE = "#fafafa"
MUTED = "#a1a1aa"
DOT = {"ok": "#4ade80", "warn": "#f59e0b", "fault": "#ef4444", "idle": "#52525b"}


def state_colours(state):
    """(dot colour, status text colour) for a state; unknown states read as ok."""
    dot = DOT.get(str(state), DOT["ok"])
    return dot, (MUTED if state == "idle" else dot)


def _icon_image(name):
    if name not in _ICON_CACHE:
        path = os.path.join(_ICON_DIR, f"{name}.png")
        image = QImage(path) if name and os.path.isfile(path) else QImage()
        _ICON_CACHE[name] = None if image.isNull() else image
    return _ICON_CACHE[name]


def _draw_icon(painter, rect, name, colour):
    image = _icon_image(name)
    if image is None:
        if name:   # ShIcon's unknown-name look: a red outline
            painter.setPen(QPen(QColor("#ef4444"), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)
        return
    tinted = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
    tinted.fill(Qt.transparent)
    p = QPainter(tinted)
    p.drawImage(0, 0, image)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(tinted.rect(), colour)
    p.end()
    painter.save()
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawImage(rect, tinted)
    painter.restore()


def _fit_font(painter, text, px, weight, width):
    font = QFont(painter.font())
    font.setKerning(False)   # the native face does not kern; nor does the QML
    floor_px = max(8, round(px * 0.6))
    p = px
    while True:
        font.setPixelSize(max(1, p))
        font.setWeight(weight)
        if p <= floor_px or QFontMetrics(font).horizontalAdvance(text) <= width:
            return font
        p -= 1


def _line_h(px):
    """Line height as the native face gets it (Inter hhea 1984/-494 of 2048,
    truncated like LVGL's tiny_ttf)."""
    return int(px * 2478 / 2048)


def _asc(px):
    return _line_h(px) - int(px * 494 / 2048)


def _line(painter, x, top, width, text, px, weight, colour):
    """One elided line in the slot starting at *top*, on its nominal baseline."""
    font = _fit_font(painter, text, px, weight, width)
    metrics = QFontMetrics(font)
    painter.setFont(font)
    painter.setPen(QPen(QColor(colour)))
    painter.drawText(QPointF(x, top + _asc(px)), metrics.elidedText(text, Qt.ElideRight, int(width)))


def paint(painter, rect, props, ctx):
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    s = min(w / 240.0, h / 180.0)
    pad = max(4, round(20 * s))
    x0, y0 = rect.left(), rect.top()
    state = str(_prop(props, "state", "ok"))
    dot, status_colour = state_colours(state)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)

    radius = round(16 * s)
    painter.setPen(QPen(QColor(BORDER), 1))
    painter.setBrush(QColor(CARD))
    painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

    icon_size = max(8, round(44 * s))
    colour = str(_prop(props, "iconColor", "#38bdf8"))
    icon_colour = QColor(colour if colour.startswith("#") else "#38bdf8")
    if not icon_colour.isValid():
        icon_colour = QColor("#38bdf8")
    _draw_icon(painter, QRectF(x0 + pad, y0 + round(18 * s), icon_size, icon_size),
               str(_prop(props, "icon", "snowflake")), icon_colour)

    r = max(2.0, 7 * s)
    halo = r * 1.9
    cx = w - pad - r
    cy = max(pad * 0.5 + halo, 18 * s + icon_size / 2 - 8 * s)
    painter.setPen(Qt.NoPen)
    glow = QColor(dot)
    glow.setAlphaF(0.22)
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(x0 + cx, y0 + cy), halo, halo)
    painter.setBrush(QColor(dot))
    painter.drawEllipse(QPointF(x0 + cx, y0 + cy), r, r)

    text_w = max(10, w - 2 * pad)
    title = str(_prop(props, "title", "HVAC:")).replace("\\n", "\n").split("\n")
    line1 = title[0]
    line2 = title[1] if len(title) > 1 else ""
    status_px, title_px, sub_px = max(8, round(28 * s)), max(8, round(24 * s)), max(7, round(16 * s))
    gap = round(2 * s)
    status_top = y0 + h - pad - _line_h(status_px) + gap
    _line(painter, x0 + pad, status_top, text_w, str(_prop(props, "status", "")),
          status_px, QFont.Bold, status_colour)
    above = status_top - gap
    if line2:
        above -= _line_h(sub_px)
        _line(painter, x0 + pad, above, text_w, line2, sub_px, QFont.Medium, MUTED)
    _line(painter, x0 + pad, above - _line_h(title_px), text_w, line1, title_px, QFont.Medium, TITLE)
    painter.restore()
