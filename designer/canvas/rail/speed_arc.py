"""Canvas painter for ShSpeedArc -- mirrors ui/qml/Shadcn/ShSpeedArc.qml at rest.

The same geometry as the QML Canvas and native/hmi-ui/src/widgets/w_shspeedarc.c:
everything relative to d = min(width, height), angles clockwise from 3 o'clock,
both arcs 240 degrees from 90 (6 o'clock) over the top to 330. QPainter angles
run the other way, hence the negations.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from designer.canvas.widget_previews import _number, _prop, _rounded

START, SWEEP = 90.0, 240.0


def _colour(value, default, alpha=1.0):
    colour = QColor(str(value or default))
    if not colour.isValid():
        colour = QColor(default)
    colour.setAlphaF(alpha)
    return colour


def _font(painter, px, weight):
    font = QFont(painter.font())
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    return font


def _given(props, key, default):
    """Text props: an empty string is a value ("no label"), as hmi-ui reads it."""
    value = props.get(key)
    return default if value is None else str(value)


def paint(painter, rect, props, ctx):
    value = _number(props, "value", 55.0)
    maximum = _number(props, "maximumValue", 100.0)
    target = _number(props, "target", 60.0)
    show_target = _prop(props, "showTarget", True) in (True, "true", "True", 1, "1")
    unit = _given(props, "unit", "KM/H")
    target_label = _given(props, "targetLabel", "TARGET")
    dp = max(0, min(6, int(_number(props, "decimals", 0))))
    outer_hex = _prop(props, "outerColor", "#22d3ee")
    inner_hex = _prop(props, "innerColor", "#a855f7")

    span = max(0.0001, maximum)

    def clamp(v):
        return max(0.0, min(maximum, v))

    def angle(v):
        return START + SWEEP * clamp(v) / span

    W, H = rect.width(), rect.height()
    d = max(1.0, min(W, H))
    cx, cy = rect.x() + W / 2, rect.y() + H / 2
    outer_r, outer_w = 0.40 * d, 0.034 * d
    inner_r, inner_w = 0.335 * d, 0.024 * d
    a0, a1, av = START, START + SWEEP, angle(value)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    def box(r):
        return QRectF(cx - r, cy - r, 2 * r, 2 * r)

    def wedge(r, start, end, alpha):
        if end <= start:
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(_colour(outer_hex, "#22d3ee", alpha))
        painter.drawPie(box(r), int(-start * 16), int(-(end - start) * 16))

    def arc(r, w, start, end, colour, alpha):
        if end <= start:
            return
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_colour(colour, "#22d3ee", alpha), w, Qt.SolidLine, Qt.RoundCap))
        painter.drawArc(box(r), int(-start * 16), int(-(end - start) * 16))

    def neon(r, w, start, end, colour):
        arc(r, w * 3.0, start, end, colour, 0.10)
        arc(r, w * 1.9, start, end, colour, 0.18)
        arc(r, w, start, end, colour, 1.0)

    def line(r0, r1, a, w, colour, alpha):
        rad = math.radians(a)
        painter.setPen(QPen(_colour(colour, "#ffffff", alpha), max(1, round(w)), Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(cx + r0 * math.cos(rad), cy + r0 * math.sin(rad)),
                         QPointF(cx + r1 * math.cos(rad), cy + r1 * math.sin(rad)))

    # 1. wedge behind the needle
    wedge_r = inner_r - inner_w / 2
    wedge(wedge_r, a0, av, 0.06)
    wedge(wedge_r, max(a0, av - 40), av, 0.07)
    wedge(wedge_r, max(a0, av - 14), av, 0.08)
    # 2. inner arc (the track)
    neon(inner_r, inner_w, a0, a1, inner_hex)
    # 3. outer arc: faint track, then the value
    arc(outer_r, outer_w, a0, a1, outer_hex, 0.14)
    if av > a0:
        neon(outer_r, outer_w, a0, av, outer_hex)
    # 4. needle
    r1 = outer_r + outer_w / 2 + 0.01 * d
    line(0.20 * d, r1, av, 0.026 * d, outer_hex, 0.25)
    line(0.20 * d, r1, av, 0.011 * d, outer_hex, 1.0)
    # 5. target tick
    if show_target:
        line(outer_r - outer_w / 2 - 0.022 * d, outer_r + outer_w / 2 + 0.022 * d,
             angle(target), 0.010 * d, "#ffffff", 1.0)

    # 6. readout + unit
    readout = f"{clamp(value):.{dp}f}"
    fs = max(8, round(min(0.226 * d, 0.58 * d / (max(1, len(readout)) * 0.62))))
    rfont = _font(painter, fs, QFont.Bold)
    rfm = QFontMetrics(rfont)
    rw, rh = rfm.horizontalAdvance(readout), rfm.height()
    ry = cy - round(0.045 * d) - rh / 2
    painter.setFont(rfont)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRectF(cx - rw / 2 - 4, ry, rw + 8, rh), Qt.AlignCenter, readout)
    if unit:
        ufont = _font(painter, max(7, round(0.071 * d)), QFont.Medium)
        ufm = QFontMetrics(ufont)
        uw = ufm.horizontalAdvance(unit)
        painter.setFont(ufont)
        painter.setPen(_colour(outer_hex, "#22d3ee"))
        painter.drawText(QRectF(cx - uw / 2 - 4, ry + rh - round(0.03 * d), uw + 8, ufm.height()),
                         Qt.AlignCenter, unit)

    # 7. target callout
    if show_target:
        lower = unit.lower()
        text = (f"{target_label}: " if target_label else "") + f"{clamp(target):.{dp}f}" + \
            (f" {lower}" if lower else "")
        cfont = _font(painter, max(7, round(0.048 * d)), QFont.Medium)
        cfm = QFontMetrics(cfont)
        pad_h, pad_v = round(0.026 * d), round(0.012 * d)
        bw = cfm.horizontalAdvance(text) + 2 * pad_h + 2
        bh = cfm.height() + 2 * pad_v + 2
        at = math.radians(angle(target))
        tr = outer_r + outer_w / 2 + 0.022 * d
        gap = 0.014 * d
        if math.sin(at) < -0.35:
            bx = cx + outer_r * math.cos(at) - bw / 2
            by = cy + tr * math.sin(at) - gap - bh
        else:
            bx = cx + tr * math.cos(at) + math.cos(at) * (bw / 2 + gap) - bw / 2
            by = cy + tr * math.sin(at) + math.sin(at) * (bh / 2 + gap) - bh / 2
        left, top = rect.x(), rect.y()
        bx = max(left, min(left + max(0, W - bw), bx))
        by = max(top, min(top + max(0, H - bh), by))
        half = rw / 2 + gap
        zone_top, zone_bottom = cy - 0.15 * d, cy + 0.15 * d
        if bx < cx + half and bx + bw > cx - half and by < zone_bottom and by + bh > zone_top:
            up, down = zone_top - bh, zone_bottom
            by = up if abs(by - up) <= abs(by - down) else down
            by = max(top, min(top + max(0, H - bh), by))
        callout = QRectF(round(bx) + 0.5, round(by) + 0.5, bw - 1, bh - 1)
        _rounded(painter, callout, QColor("#1c1c22"), round(0.018 * d), QColor("#3a3a44"), 1)
        painter.setFont(cfont)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(callout, Qt.AlignCenter, text)

    painter.restore()
