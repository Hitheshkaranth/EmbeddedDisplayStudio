"""Canvas previews for the kit's "neon" styles (approximate).

ShClusterGauge / ShSpeedArc style "neon" and the arc helpers behind them, the
QPainter counterpart of ui/qml/Shadcn/NeonPaint.js and draw_util.h's
hmi_draw_neon_arc / hmi_draw_neon_glow: a thick round-capped arc shaded along
the scale in short segments, over a few wider translucent copies for the
glow. The Designer canvas shows hmi-ui's own render when it has the binary;
these keep the fallback recognisable.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from designer.canvas.widget_previews import (
    WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, _number, _override_colour, _text, auto, shade,
)

GLOW_LAYERS = 8
GLOW_ALPHA = 30 / 255


def _mix(c0, c1, t):
    t = max(0.0, min(1.0, t))
    return QColor(round(c0.red() + (c1.red() - c0.red()) * t),
                  round(c0.green() + (c1.green() - c0.green()) * t),
                  round(c0.blue() + (c1.blue() - c0.blue()) * t))


def glow_reach(d):
    return max(4.0, min(16.0, 0.04 * d))


def arc(painter, cx, cy, r, w, a0, a1, c0, c1=None, g0=None, g1=None, alpha=1.0, caps=(True, True)):
    """A stroked arc from a0 to a1 degrees (clockwise from 3 o'clock), shaded
    from c0 at g0 to c1 at g1, with round caps where ``caps`` says."""
    if a1 <= a0 or w <= 0 or r <= 0:
        return
    c1 = c1 or c0
    g0 = a0 if g0 is None else g0
    g1 = a1 if g1 is None else g1
    box = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    n = max(1, min(48, int((a1 - a0) / 5)))
    step = (a1 - a0) / n
    painter.setBrush(Qt.NoBrush)
    for i in range(n):
        s = a0 + i * step
        mid = s + step / 2
        colour = _mix(c0, c1, (mid - g0) / (g1 - g0) if g1 > g0 else 0)
        colour.setAlphaF(alpha)
        painter.setPen(QPen(colour, w, Qt.SolidLine, Qt.FlatCap))
        extra = 0.6 if alpha >= 1 and i < n - 1 else 0
        painter.drawArc(box, int(-s * 16), int(-(step + extra) * 16))
    painter.setPen(Qt.NoPen)
    for at, wanted in ((a0, caps[0]), (a1, caps[1])):
        if not wanted:
            continue
        colour = _mix(c0, c1, (at - g0) / (g1 - g0) if g1 > g0 else 0)
        colour.setAlphaF(alpha)
        painter.setBrush(colour)
        rad = math.radians(at)
        painter.drawEllipse(QPointF(cx + r * math.cos(rad), cy + r * math.sin(rad)), w / 2, w / 2)


def glow(painter, cx, cy, r, w, a0, a1, c0, c1=None, g0=None, g1=None, reach=8.0, caps=(True, True)):
    for k in range(GLOW_LAYERS, 0, -1):
        arc(painter, cx, cy, r, w + 2 * reach * k / GLOW_LAYERS, a0, a1, c0, c1, g0, g1, GLOW_ALPHA, caps)


def paint_cluster_gauge(painter, rect, props, ctx):
    """ShClusterGauge style "neon"."""
    value = _number(props, "value", 4.2)
    minimum = _number(props, "minimumValue", 0.0)
    maximum = _number(props, "maximumValue", 8.0)
    redline_from = _number(props, "redlineFrom", 7.0)
    sweep = _number(props, "sweep", 240.0)
    decimals = int(_number(props, "decimals", 0))

    def given(key, default):
        v = props.get(key)
        return default if v is None else str(v)
    readout = given("readout", "137")
    unit = given("readoutUnit", "km/h")
    caption = given("caption", "")
    label = given("label", "x1000 RPM")
    c0 = _override_colour(props, "accentColor") or auto("accent")
    c1 = _override_colour(props, "accentColor2") or shade(c0, 35)
    red = auto("redline")
    span = max(0.0001, maximum - minimum)
    clamped = max(minimum, min(maximum, value))
    d = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    a0 = 90 + (360 - sweep) / 2
    a1 = a0 + sweep
    arc_r, stroke = 0.40 * d, 0.085 * d
    red_a = a0 + sweep * max(0.0, min(1.0, (redline_from - minimum) / span)) if redline_from < maximum else a1
    value_a = a0 + sweep * (clamped - minimum) / span

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    arc(painter, cx, cy, arc_r, stroke, a0, red_a, c0, c1, a0, a1, 0.12, (True, red_a >= a1))
    arc(painter, cx, cy, arc_r, stroke, red_a, a1, red, red, alpha=0.12, caps=(red_a <= a0, True))
    v_end = min(value_a, red_a)
    into_red = value_a > red_a
    glow(painter, cx, cy, arc_r, stroke, a0, v_end, c0, c1, a0, a1, glow_reach(d), (True, not into_red))
    if into_red:
        glow(painter, cx, cy, arc_r, stroke, red_a, value_a, red, red, reach=glow_reach(d),
             caps=(red_a <= a0, True))
    arc(painter, cx, cy, arc_r, stroke, a0, v_end, c0, c1, a0, a1, 1.0, (True, not into_red))
    if into_red:
        arc(painter, cx, cy, arc_r, stroke, red_a, value_a, red, red, caps=(red_a <= a0, True))

    text = readout if readout else f"{clamped:.{decimals}f}"
    fs = max(8, round(min(0.30 * d, 0.62 * d / (max(1, len(text)) * 0.6))))
    line_h = fs * 1.21
    top = cy - round(0.03 * d) - line_h / 2
    _text(painter, QRectF(rect.left(), top, rect.width(), line_h), text, size=fs,
          color=auto("text"), weight=QFont.Bold, flags=Qt.AlignCenter, elide=False)
    if caption:
        cap_fs = max(7, round(min(0.075 * d, 0.56 * d / max(1, len(caption) * 0.62))))
        _text(painter, QRectF(rect.left(), top + round(0.10 * fs) - cap_fs * 1.21, rect.width(), cap_fs * 1.21),
              caption, size=cap_fs, color=c0, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter, elide=False)
    y = top + line_h - round(0.12 * fs)
    if unit:
        ufs = max(7, round(0.075 * d))
        _text(painter, QRectF(rect.left(), y, rect.width(), ufs * 1.21), unit, size=ufs,
              color=auto("muted"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter, elide=False)
        y += ufs * 1.21
    if label:
        lfs = max(7, round(0.06 * d))
        _text(painter, QRectF(rect.left(), y, rect.width(), lfs * 1.21), label, size=lfs,
              color=auto("muted"), flags=Qt.AlignCenter, elide=False)
    painter.restore()


def paint_speed_arc(painter, rect, props, ctx):
    """ShSpeedArc style "neon"."""
    value = _number(props, "value", 55.0)
    maximum = max(0.0001, _number(props, "maximumValue", 100.0))
    target = _number(props, "target", 60.0)
    show_target = props.get("showTarget", True) in (True, "true", "True", 1, "1")
    unit = props.get("unit")
    unit = "KM/H" if unit is None else str(unit)
    dp = max(0, min(6, int(_number(props, "decimals", 0))))
    outer = _override_colour(props, "outerColor") or QColor("#22d3ee")
    inner = _override_colour(props, "innerColor") or QColor("#a855f7")
    mid = _mix(outer, inner, 128 / 255)

    def angle(v):
        return 90 + 240 * max(0.0, min(maximum, v)) / maximum

    d = max(1.0, min(rect.width(), rect.height()))
    cx, cy = rect.center().x(), rect.center().y()
    a0, a1, av = 90.0, 330.0, angle(value)
    r0, w0 = 0.40 * d, 0.055 * d
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    arc(painter, cx, cy, r0, w0, a0, a1, outer, alpha=0.14)
    glow(painter, cx, cy, r0, w0, a0, av, outer, reach=glow_reach(d))
    arc(painter, cx, cy, r0, w0, a0, av, shade(outer, -10), shade(outer, 40), a0, a1)
    arc(painter, cx, cy, 0.325 * d, 0.04 * d, a0, av, mid, alpha=0.85)
    arc(painter, cx, cy, 0.26 * d, 0.028 * d, a0, av, inner, alpha=0.60)
    if show_target:
        at = math.radians(angle(target))
        t0, t1 = r0 - w0 / 2 - 0.015 * d, r0 + w0 / 2 + 0.015 * d
        painter.setPen(QPen(QColor("#ffffff"), max(2, round(0.010 * d)), Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(cx + t0 * math.cos(at), cy + t0 * math.sin(at)),
                         QPointF(cx + t1 * math.cos(at), cy + t1 * math.sin(at)))
    text = f"{max(0.0, min(maximum, value)):.{dp}f}"
    fs = max(8, round(min(0.28 * d, 0.46 * d / (max(1, len(text)) * 0.6))))
    line_h = fs * 1.21
    top = cy - round(0.035 * d) - line_h / 2
    _text(painter, QRectF(rect.left(), top, rect.width(), line_h), text, size=fs,
          color=QColor("#ffffff"), weight=QFont.Bold, flags=Qt.AlignCenter, elide=False)
    if unit:
        ufs = max(7, round(0.08 * d))
        _text(painter, QRectF(rect.left(), top + line_h - round(0.12 * fs), rect.width(), ufs * 1.21), unit,
              size=ufs, color=QColor("#b4bfcc"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter, elide=False)
    painter.restore()
