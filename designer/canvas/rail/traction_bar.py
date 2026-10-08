"""Canvas painter for ShTractionBar -- mirrors ui/qml/Shadcn/ShTractionBar.qml at rest.

The metro cab's T/B indicator: title, an upper track filled from its bottom in
green while value > 0 (traction %), the signed percent and mode word between the
tracks, a lower track filled from its top in amber while value < 0 (braking %,
a faint amber hint while idle), and the side labels written bottom-to-top.
Geometry and colours are the QML's (and native/hmi-ui w_shtractionbar.c's).
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainterPath, QPen

from designer.canvas.widget_previews import _number, _prop

GREEN = "#4ade80"
AMBER = "#f59e0b"
LIGHT = "#d4d4d8"
GREY = "#a1a1aa"


def _font(painter, px, weight, spacing=0.0):
    font = QFont(painter.font())
    font.setPixelSize(max(1, int(px)))
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


def _centred_text(painter, cx, cy, text, font, color, rotate=False):
    painter.save()
    painter.setFont(font)
    painter.setPen(QPen(QColor(color)))
    metrics = painter.fontMetrics()
    tw, th = metrics.horizontalAdvance(text) + 4, metrics.height()
    painter.translate(cx, cy)
    if rotate:
        painter.rotate(-90)
    painter.drawText(QRectF(-tw / 2, -th / 2, tw, th), Qt.AlignCenter, text)
    painter.restore()


def _track(painter, rect, radius, fill, border):
    painter.setBrush(QBrush(QColor(fill)))
    painter.setPen(QPen(QColor(border), 1))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def _gradient_fill(painter, x, y, w, h, radius, top_color, bottom_color, clip):
    """A rounded rect with a vertical gradient, clipped to the rows in `clip`."""
    if w <= 0 or h <= 0 or clip[1] <= clip[0]:
        return
    painter.save()
    painter.setClipRect(QRectF(x, clip[0], w, clip[1] - clip[0]))
    gradient = QLinearGradient(0, y, 0, y + h)
    gradient.setColorAt(0.0, top_color)
    gradient.setColorAt(1.0, bottom_color)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    painter.fillPath(path, QBrush(gradient))
    painter.restore()


def paint(painter, rect, props, ctx):
    value = _number(props, "value", 30.0)
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    left, top = rect.left(), rect.top()
    tx, tw, th = left + w * 0.38, w * 0.50, h * 0.36
    up_top, low_top = top + h * 0.075, top + h * 0.565
    up_bottom, low_bottom = up_top + th, low_top + th
    radius = min(tw * 0.16, 12)
    ir = max(0.0, radius - 1)
    ix, iw = tx + 1, tw - 2
    power = max(0.0, min(100.0, value)) / 100
    brake = max(0.0, min(100.0, -value)) / 100

    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)

    # upper track: traction, filled from the bottom
    _track(painter, QRectF(tx, up_top, tw, th), radius, "#0f1a12", "#1f3a26")
    if power > 0:
        fill_top = up_bottom - 1 - (th - 2) * power
        gy = max(up_top + 1, fill_top - ir)
        _gradient_fill(painter, ix, gy, iw, up_bottom - 1 - gy, ir,
                       QColor("#166534"), QColor(GREEN), (fill_top, up_bottom - 1))
        ly = fill_top - 1.5
        if ly >= up_top + ir and ly + 3 <= up_bottom - ir:
            painter.fillRect(QRectF(ix, ly, iw, 3), QColor("#bef264"))

    # lower track: braking, filled from the top; a faint hint while idle
    _track(painter, QRectF(tx, low_top, tw, th), radius, "#1a140a", "#3a2a10")
    if brake > 0:
        fill_bottom = low_top + 1 + (th - 2) * brake
        gb = min(low_bottom - 1, fill_bottom + ir)
        _gradient_fill(painter, ix, low_top + 1, iw, gb - low_top - 1, ir,
                       QColor(AMBER), QColor("#92400e"), (low_top + 1, fill_bottom))
        ly = fill_bottom - 1.5
        if ly >= low_top + ir and ly + 3 <= low_bottom - ir:
            painter.fillRect(QRectF(ix, ly, iw, 3), QColor("#fcd34d"))
    else:
        hint_top, hint_bottom = QColor(AMBER), QColor("#92400e")
        hint_top.setAlphaF(0.16)
        hint_bottom.setAlphaF(0.03)
        _gradient_fill(painter, ix, low_top + 1, iw, th - 2, ir, hint_top, hint_bottom,
                       (low_top + 1, low_bottom - 1))

    # labels
    pct = round(min(100.0, abs(value)))
    if pct > 0 and value > 0:
        text, color, word = f"+{pct}%", GREEN, str(_prop(props, "propulsionText", "Propulsion"))
    elif pct > 0:
        text, color, word = f"-{pct}%", AMBER, str(_prop(props, "brakingText", "Braking"))
    else:
        text, color, word = "0%", GREY, "Coast"
    gap = low_top - up_bottom
    _centred_text(painter, tx + tw / 2, up_top - (h * 0.075) / 2, str(props.get("title", "T/B") or ""),
                  _font(painter, max(8, round(min(w * 0.21, h * 0.047))), QFont.DemiBold), LIGHT)
    _centred_text(painter, left + w / 2, up_bottom + gap * 0.36, text,
                  _font(painter, max(10, round(min(w * 0.26, h * 0.056))), QFont.Bold), color)
    _centred_text(painter, left + w / 2, up_bottom + gap * 0.76, word,
                  _font(painter, max(7, round(min(w * 0.13, h * 0.028))), QFont.Medium), LIGHT)
    side = _font(painter, max(7, round(min(w * 0.115, h * 0.025))), QFont.DemiBold, 1.0)
    side_x = left + (tx - left) * 0.55
    _centred_text(painter, side_x, up_top + th / 2, str(props.get("powerLabel", "POWER") or ""),
                  side, GREEN, rotate=True)
    _centred_text(painter, side_x, low_top + th / 2, str(props.get("brakeLabel", "BRAKING") or ""),
                  side, AMBER, rotate=True)
    painter.restore()
