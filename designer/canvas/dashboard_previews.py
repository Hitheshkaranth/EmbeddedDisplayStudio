"""Canvas painters for the industrial dashboard pieces: ShKpiTile, ShStatusRow,
ShTrendChart's series view and ShAlarmTable's table view.

Approximations of ui/qml/Shadcn/ShKpiTile.qml, ShStatusRow.qml,
ShTrendChart.qml and ShAlarmTable.qml (and their twins in
native/hmi-ui/src/widgets): the same shares of the size, the same colours,
Qt's text instead of the panel's metrics. The Designer canvas uses hmi-ui
renders when the binary is at hand; these are the fallback.
"""
import math
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF

from designer.canvas.widget_previews import (FONT, RADIUS, WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, _number,
                                             _override_colour, _prop, _rounded, _text, shade, token)

_ICONS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ui", "qml", "Shadcn", "icons"))
_ICON_CACHE = {}


def _px(v):
    return int(math.floor(v + 0.5))


def _clamp(v, lo, hi):
    return max(lo, min(hi, _px(v)))


def _font(size, weight=QFont.Normal):
    f = QFont()
    f.setPixelSize(max(1, int(size)))
    f.setWeight(weight)
    return f


def _width(text, size, weight=QFont.Normal):
    return QFontMetricsF(_font(size, weight)).horizontalAdvance(str(text))


def _icon(painter, name, rect, colour):
    """A kit icon (ui/qml/Shadcn/icons/<name>.png) recoloured, or nothing."""
    key = (name, int(rect.width()), QColor(colour).rgba())
    img = _ICON_CACHE.get(key)
    if img is None:
        path = os.path.join(_ICONS, f"{name}.png")
        if not os.path.exists(path):
            return
        src = QImage(path).scaled(int(rect.width()), int(rect.height()), Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        p = QPainter(src)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(src.rect(), QColor(colour))
        p.end()
        _ICON_CACHE[key] = img = src
    painter.drawImage(QPointF(rect.left(), rect.top()), img)


def _value_text(props):
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
    if decimals >= 0 and number is not None and math.isfinite(number):
        return f"{number:.{decimals}f}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def paint_kpi_tile(painter, rect, props, ctx):
    """ShKpiTile: icon, title, value + unit, subtitle, progress bar."""
    painter.setRenderHint(QPainter.Antialiasing, True)
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    left, top0 = rect.left(), rect.top()
    tile = _override_colour(props, "tileColor") or token("card")
    _rounded(painter, QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), tile, RADIUS["sm"], token("border"), 1)
    pad_x, pad_y = _clamp(w * 0.05, 6, 14), _clamp(h * 0.10, 4, 12)
    progress = _number(props, "progress", -1.0)
    bar = progress >= 0
    bar_h = _clamp(h * 0.06, 3, 8)
    bar_y = _px(h) - pad_y - bar_h
    top = pad_y
    bottom = bar_y - _clamp(h * 0.04, 2, 6) if bar else _px(h) - pad_y
    content_h = max(1, bottom - top)
    icon = str(props.get("icon") or "")
    icon_sz = _clamp(min(content_h * 0.62, w * 0.20), 12, 56) if icon else 0
    if icon:
        _icon(painter, icon, QRectF(left + pad_x, top0 + top + (content_h - icon_sz) // 2, icon_sz, icon_sz),
              token("mutedForeground"))
    text_x = pad_x + icon_sz + max(8, _px(w * 0.06)) if icon else pad_x
    text_w = max(1, _px(w) - pad_x - text_x)
    title, sub = str(props.get("title") or ""), str(props.get("subtitle") or "")
    tp, vp, sp = _clamp(h * 0.145, 8, 18), _clamp(h * 0.27, 10, 40), _clamp(h * 0.125, 8, 15)
    lh = lambda px: math.floor(px * 2478 / 2048)
    for g in range(40):
        stack = (lh(tp) if title else 0) + lh(vp) + (lh(sp) if sub else 0)
        if stack <= content_h or (tp <= 8 and vp <= 10 and sp <= 8):
            break
        if vp > 10:
            vp -= 1
        if g % 2 == 0 and tp > 8:
            tp -= 1
        if g % 2 == 0 and sp > 8:
            sp -= 1
    up = max(8, _px(vp * 0.72))
    stack = (lh(tp) if title else 0) + lh(vp) + (lh(sp) if sub else 0)
    gap = max(0.0, (content_h - stack) / (2 + (1 if title else 0) + (1 if sub else 0)))
    y = top + gap
    if title:
        _text(painter, QRectF(left + text_x, top0 + y, text_w, lh(tp)), title, size=tp,
              color=token("foreground"), weight=WEIGHT_MEDIUM)
        y += lh(tp) + gap
    ink = _override_colour(props, "valueColor") or token("foreground")
    value = _value_text(props)
    unit = str(props.get("unit") or "")
    vw = min(_width(value, vp, QFont.Bold), text_w)
    _text(painter, QRectF(left + text_x, top0 + y, text_w, lh(vp)), value, size=vp, color=ink, weight=QFont.Bold)
    if unit:
        _text(painter, QRectF(left + text_x + vw + max(3, _px(vp * 0.22)), top0 + y, text_w, lh(vp)), unit,
              size=up, color=ink, flags=Qt.AlignLeft | Qt.AlignBottom)
    y += lh(vp) + gap
    sub_top = y if sub else bottom - lh(sp)
    if sub:
        _text(painter, QRectF(left + text_x, top0 + sub_top, text_w, lh(sp)), sub, size=sp,
              color=token("mutedForeground"))
    ptext = str(props.get("progressText") or "")
    if ptext:
        _text(painter, QRectF(left + pad_x, top0 + sub_top, w - 2 * pad_x, lh(sp)), ptext, size=sp,
              color=token("foreground"), weight=WEIGHT_MEDIUM, flags=Qt.AlignRight | Qt.AlignVCenter)
    if bar:
        track = QRectF(left + pad_x, top0 + bar_y, max(1, w - 2 * pad_x), bar_h)
        _rounded(painter, track, token("muted"), bar_h / 2)
        fill_w = track.width() * min(100.0, progress) / 100.0
        if fill_w > 0:
            _rounded(painter, QRectF(track.left(), track.top(), fill_w, bar_h),
                     _override_colour(props, "barColor") or token("success"), bar_h / 2)


def status_colours(state):
    """(badge fill, lamp, badge ink) for a ShStatusRow state."""
    if state == "ok":
        return token("success"), token("success"), QColor("#07130b")
    if state == "warn":
        return token("warning"), token("warning"), QColor("#1a1203")
    if state == "fault":
        return token("destructive"), token("destructive"), QColor("#ffffff")
    return token("muted"), token("mutedForeground"), token("mutedForeground")


def paint_status_row(painter, rect, props, ctx):
    """ShStatusRow: lamp, label, status badge coloured by state."""
    painter.setRenderHint(QPainter.Antialiasing, True)
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    left, top = rect.left(), rect.top()
    fill, lamp, ink = status_colours(str(props.get("state") or "idle"))
    d = _clamp(h * 0.55, 6, 18)
    dx = _px(h * 0.15)
    lamp_rect = QRectF(left + dx, top + (_px(h) - d) // 2, d, d)
    painter.setBrush(QBrush(lamp))
    painter.setPen(QPen(shade(lamp, -35), 1) if d >= 10 else Qt.NoPen)
    painter.drawEllipse(lamp_rect.adjusted(0.5, 0.5, -0.5, -0.5))
    s = max(2, _px(d * 0.36))
    hl = QColor(shade(lamp, 55))
    hl.setAlphaF(200 / 255)
    painter.setBrush(QBrush(hl))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(lamp_rect.left() + _px(d * 0.22), lamp_rect.top() + _px(d * 0.18), s, s))
    status = str(props.get("status") or "")
    bh = _clamp(h * 0.72, 10, 28)
    bpx = _clamp(bh * 0.6, 7, 16)
    bw = 0 if not status else min(max(math.ceil(_width(status, bpx, WEIGHT_SEMIBOLD)) + bh, _px(w * 0.29)),
                                  _px(w) // 2)
    bx = _px(w) - bw
    if bw:
        badge = QRectF(left + bx, top + (_px(h) - bh) // 2, bw, bh)
        _rounded(painter, badge, fill, 2)
        _text(painter, badge, status, size=bpx, color=ink, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
    lpx = _clamp(h * 0.5, 8, 18)
    lx = dx + d + max(6, _px(h * 0.6))
    lw = (bx - 6 if bw else _px(w)) - lx
    if lw > 0:
        _text(painter, QRectF(left + lx, top, lw, h), str(props.get("label") or ""), size=lpx,
              color=token("foreground"))


# -- ShTrendChart series view -----------------------------------------------------

SERIES_PALETTE = ("#ff3b3b", "#ff9f1c", "#ffd23f", "#3ee05a", "#22b8ff", "#a78bfa", "#f472b6", "#94a3b8")


def parse_series(spec):
    """"Label|#color|level;..." -> [(label, QColor, level or None)] (at most 8)."""
    out = []
    for item in str(spec or "").split(";"):
        item = item.strip()
        if not item or len(out) >= 8:
            continue
        fields = [f.strip() for f in item.split("|")]
        colour = fields[1] if len(fields) > 1 and fields[1].startswith("#") else SERIES_PALETTE[len(out) % 8]
        try:
            level = float(fields[2]) if len(fields) > 2 else None
        except ValueError:
            level = None
        out.append((fields[0], QColor(colour), level))
    return out


def trend_noise(s, i, n):
    """w_shtrendchart.c's trend_noise / ShTrendChart.qml's _noise: -1..1."""
    h = (i * 374761393 + (s + 1) * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    r = h / 4294967295.0 * 2 - 1
    t = i / (n - 1) if n > 1 else 0
    return 0.62 * r + 0.38 * math.sin(2 * math.pi * (1.3 + 0.37 * s) * t + 1.7 * s)


def nice_step(span, max_ticks):
    if span <= 0 or max_ticks < 1:
        return 1.0
    raw = span / max_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for k in (1, 2, 2.5, 5, 10):
        if k * mag >= raw - 1e-9 * mag:
            return k * mag
    return 10 * mag


def tick_text(v, step):
    if abs(v) < step * 1e-6:
        v = 0.0
    dec = 0 if step >= 1 else min(4, math.ceil(-math.log10(step) - 1e-9))
    return f"{v:,.{dec}f}"


def paint_trend_series(painter, rect, props, ctx):
    """ShTrendChart with ``series`` set: framed plot, ticks, x labels, legend."""
    painter.setRenderHint(QPainter.Antialiasing, True)
    series = parse_series(props.get("series"))
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    left, top0 = rect.left(), rect.top()
    tick_px = max(8, min(12, _px(h * 0.055)))
    legend_px = max(8, min(13, _px(h * 0.065)))
    tick_lh = math.floor(tick_px * 2478 / 2048)
    muted, grid = token("mutedForeground"), token("border")
    top = 0
    label, unit = str(props.get("label") or ""), str(props.get("unit") or "")
    if label:
        _text(painter, QRectF(left, top0, w, 16), label, size=FONT["xs"], color=muted, weight=WEIGHT_MEDIUM)
        top += 18
    if unit:
        _text(painter, QRectF(left, top0 + top, w / 3, tick_lh), unit, size=tick_px, color=muted)
        top += tick_lh + 2
    top += tick_lh // 2
    xlabels = [x.strip() for x in str(props.get("xLabels") or "").split(",")] if props.get("xLabels") else []
    bottom = int(h) - (tick_lh + 4 if xlabels else tick_lh // 2) - 1
    swatch = max(8, _px(legend_px * 1.25))
    legend_w = max((_width(s[0], legend_px) for s in series), default=0) + swatch + 18
    if legend_w > w * 0.45:
        legend_w = 0
    lo = _number(props, "minValue", 0.0)
    hi = _number(props, "maxValue", 100.0)
    hi = hi if hi > lo else lo + 1
    step = nice_step(hi - lo, int(max(2, min(10, (bottom - top) / (tick_lh * 1.6)))))
    ticks = []
    v = math.ceil(lo / step - 1e-9) * step
    while v <= hi + step * 1e-6:
        ticks.append(v)
        v += step
    y_lw = max((_width(tick_text(t, step), tick_px) for t in ticks), default=0)
    x0, x1 = y_lw + 6, int(w) - legend_w - 6
    if x1 - x0 < 10 or bottom - top < 10:
        return
    pw, ph = x1 - x0, bottom - top
    painter.fillRect(QRectF(left + x0, top0 + top, pw, ph), token("background"))
    for t in ticks:
        y = round(bottom - (t - lo) / (hi - lo) * ph)
        if top < y < bottom:
            c = QColor(grid)
            c.setAlphaF(150 / 255)
            painter.fillRect(QRectF(left + x0, top0 + y, pw, 1), c)
        _text(painter, QRectF(left, top0 + y - tick_lh / 2, y_lw, tick_lh), tick_text(t, step), size=tick_px,
              color=muted, flags=Qt.AlignRight | Qt.AlignVCenter)
    for i, xl in enumerate(xlabels):
        x = x0 + pw * i / (len(xlabels) - 1) if len(xlabels) > 1 else x0
        tw = _width(xl, tick_px)
        tx = max(0, min(w - tw, x - tw / 2))
        _text(painter, QRectF(left + tx, top0 + bottom + 4, tw + 2, tick_lh), xl, size=tick_px, color=muted,
              elide=False)
    axis = shade(grid, 45)
    painter.fillRect(QRectF(left + x0, top0 + top, 1, ph + 1), axis)
    painter.fillRect(QRectF(left + x0, top0 + bottom, pw, 1), axis)
    n = max(8, min(160, _px(pw / 5)))
    lw = _number(props, "lineWidth", 2.0) or 2.0
    for s, (_name, colour, level) in enumerate(series):
        level = (lo + hi) / 2 if level is None else level
        pts = []
        for i in range(n):
            val = level + (hi - lo) * 0.016 * trend_noise(s, i, n)
            y = max(top, min(bottom, bottom - (val - lo) / (hi - lo) * ph))
            pts.append(QPointF(left + x0 + pw * i / (n - 1), top0 + y))
        painter.setPen(QPen(colour, lw))
        painter.setBrush(Qt.NoBrush)
        painter.drawPolyline(QPolygonF(pts))
    if legend_w:
        lh = math.floor(legend_px * 2478 / 2048)
        row_h = int(min(_px(lh * 2.1), ph / max(1, len(series))))
        for s, (name, colour, _level) in enumerate(series):
            cy = top + row_h * s + row_h // 2
            painter.fillRect(QRectF(left + x1 + 10, top0 + cy - 2, swatch, 4), colour)
            _text(painter, QRectF(left + x1 + 10 + swatch + 8, top0 + cy - lh / 2, legend_w - swatch - 8, lh),
                  name, size=legend_px, color=token("foreground"))


# -- ShAlarmTable table view ------------------------------------------------------

def _pill(text):
    t = str(text).upper()
    return {"HIGH": "high", "CRITICAL": "high", "MEDIUM": "medium", "LOW": "low", "ACTIVE": "active",
            "ACKED": "acked"}.get(t, "")


def paint_alarm_table_view(painter, rect, props, ctx):
    """ShAlarmTable with ``columns``/``sampleRows``: title bar, column header
    row, the sample rows with pills."""
    painter.setRenderHint(QPainter.Antialiasing, True)
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    left, top = rect.left(), rect.top()
    cols = [c.strip() for c in str(props.get("columns") or "").split(",")][:8] if props.get("columns") else []
    rows = [[c.strip() for c in r.split("|")][:8] for r in str(props.get("sampleRows") or "").split(";")
            if r.strip()][:16]
    head_h = max(22, min(36, _px(h * 0.17)))
    col_h = max(16, min(24, _px(h * 0.13))) if cols else 0
    head_colour = _override_colour(props, "headerColor")
    fill = head_colour or token("secondary")
    ink = token("foreground")
    if head_colour is not None:
        lum = 0.2126 * fill.redF() + 0.7152 * fill.greenF() + 0.0722 * fill.blueF()
        ink = QColor("#0b0f14") if lum > 0.55 else QColor("#ffffff")
    _rounded(painter, QRectF(left, top, w, head_h), fill, RADIUS["sm"])
    show_count = bool(props.get("showCount", True))
    _text(painter, QRectF(left + 8, top, w - (56 if show_count else 16), head_h),
          str(_prop(props, "title", "Active Alarms")), size=FONT["sm"], color=ink, weight=WEIGHT_SEMIBOLD)
    if show_count:
        badge = QRectF(left + w - 8 - 28, top + (head_h - min(20, head_h - 6)) / 2, 28, min(20, head_h - 6))
        _rounded(painter, badge, token("secondary"), badge.height() / 2)
        _text(painter, badge, str(len(rows)), size=FONT["xs"], color=token("secondaryForeground"),
              weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
    body = QRectF(left, top + head_h, w, h - head_h)
    _rounded(painter, body.adjusted(0.5, 0.5, -0.5, -0.5), token("background"), 0, token("border"), 1)
    rh = int(_number(props, "rowHeight", 30.0)) or 30
    if rows:
        rh = min(rh, max(14, int((h - head_h - col_h) // len(rows))))
    px = max(9, min(13, _px(rh * 0.6)))
    hpx, ppx = max(9, px - 1), max(8, px - 1)
    pill_h = max(12, min(22, _px(rh * 0.64)))
    ncols = max(1, len(cols) if cols else max((len(r) for r in rows), default=0))
    nat = []
    for c in range(ncols):
        m = _width(cols[c], hpx, WEIGHT_MEDIUM) if cols else 0
        for r in rows:
            s = r[c] if c < len(r) else ""
            m = max(m, _width(s, ppx, WEIGHT_SEMIBOLD) + 16 if _pill(s) else _width(s, px))
        nat.append(m + 16)
    total = sum(nat) or 1
    xs, x = [], 0.0
    for c in range(ncols):
        xs.append(round(x))
        x += nat[c] * w / total
    xs.append(round(w))
    if cols:
        painter.fillRect(QRectF(left, body.top(), w, col_h), token("secondary"))
        for c, name in enumerate(cols):
            _text(painter, QRectF(left + xs[c] + 8, body.top(), xs[c + 1] - xs[c] - 16, col_h), name, size=hpx,
                  color=token("mutedForeground"), weight=WEIGHT_MEDIUM)
            if c:
                painter.fillRect(QRectF(left + xs[c], body.top(), 1, col_h), token("border"))
    if not rows:
        _text(painter, QRectF(left, body.top() + col_h, w, body.height() - col_h), "No active alarms",
              size=FONT["sm"], color=token("mutedForeground"), flags=Qt.AlignCenter)
        return
    for i, r in enumerate(rows):
        y = body.top() + col_h + i * rh
        if y >= rect.bottom():
            break
        active = any(_pill(c) == "active" for c in r)
        row_ink = token("destructive") if active else token("foreground")
        for c in range(ncols):
            s = r[c] if c < len(r) else ""
            cx, cw = xs[c], xs[c + 1] - xs[c]
            kind = _pill(s)
            if not kind:
                _text(painter, QRectF(left + cx + 8, y, cw - 16, rh), s, size=px, color=row_ink)
            else:
                pw = min(cw - 12, max(_width(s, ppx, WEIGHT_SEMIBOLD) + 16, round(cw * 0.62)))
                pr = QRectF(left + cx + 6, y + (rh - pill_h) // 2, pw, pill_h)
                colours = {"high": (token("destructive"), QColor("#ffffff"), None),
                           "medium": (token("warning"), QColor("#1a1203"), None),
                           "low": (token("info"), QColor("#ffffff"), None)}
                if kind in colours:
                    bg, fg, edge = colours[kind]
                elif kind == "active":
                    bg = QColor(token("destructive"))
                    bg.setAlphaF(56 / 255)
                    fg = edge = token("destructive")
                else:
                    bg, fg, edge = None, token("mutedForeground"), token("mutedForeground")
                _rounded(painter, pr, bg, 3, edge, 1 if edge is not None else 0)
                _text(painter, pr, s, size=ppx, color=fg, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
            if c:
                painter.fillRect(QRectF(left + cx, y, 1, rh), token("border"))
        painter.fillRect(QRectF(left, y + rh - 1, w, 1), token("border"))


PAINTERS = {
    "ShKpiTile": paint_kpi_tile,
    "ShStatusRow": paint_status_row,
}
