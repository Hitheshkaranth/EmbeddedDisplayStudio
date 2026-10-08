"""Canvas painter for ShTrainConsist -- mirrors ui/qml/Shadcn/ShTrainConsist.qml at rest.

A top-down metro consist standing vertically: cars stacked with small gaps,
cab cars with a rounded accent-trimmed nose, windscreen band and lights,
two columns of seats per car, a lock on the car behind the leading cab, door
bars on both long sides coloured by doorsLeft / doorsRight, car names on the
right and the two door captions on the left, all reading bottom-to-top.
Geometry is the C face's (native/hmi-ui/src/widgets/w_shtrainconsist.c).
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen

from designer.canvas.widget_previews import WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, _prop

BODY = "#2a2a30"
LINE = "#3f3f46"
SEAT = "#3a3a42"
GLASS = "#0c0c10"
DOOR = {"closed": "#4ade80", "open": "#f59e0b", "disabled": "#3f3f46"}
CAPTION = {"closed": "#4ade80", "open": "#f59e0b", "disabled": "#71717a"}


def door_state(value):
    """'closed' / 'open' / 'disabled'; a bound bool or number: true/1 closed, false/0 open."""
    if isinstance(value, bool):
        return "closed" if value else "open"
    if isinstance(value, (int, float)):
        return "closed" if value else "open"
    s = str(value).strip().lower()
    if s in ("closed", "true", "1"):
        return "closed"
    if s in ("open", "false", "0"):
        return "open"
    return "disabled"


def car_list(value):
    return [c.strip() for c in str(value).split(",") if c.strip()][:16]


def split_caption(text):
    text = str(text)
    if ":" not in text:
        return text, ""
    i = text.index(":")
    return text[:i + 1], text[i + 1:].strip()


def _font(painter, size, weight):
    font = QFont(painter.font())
    font.setPixelSize(max(1, int(size)))
    font.setWeight(weight)
    return font


def _fill(painter, x, y, w, h, colour, radius=0.0):
    if w <= 0 or h <= 0:
        return
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(colour)))
    painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)


def _framed(painter, x, y, w, h, fill, border, width, radius):
    """A rectangle with its border inside the box, as QML/LVGL draw it."""
    _fill(painter, x, y, w, h, border, radius)
    _fill(painter, x + width, y + width, w - 2 * width, h - 2 * width, fill, max(0.0, radius - width))


def _rotated_text(painter, cx, cy, text, font, colour):
    """Text centred on (cx, cy), rotated -90 deg (reads bottom-to-top)."""
    if not text:
        return
    painter.save()
    painter.translate(cx, cy)
    painter.rotate(-90)
    painter.setFont(font)
    painter.setPen(QPen(QColor(colour)))
    m = QFontMetricsF(font)
    w = m.horizontalAdvance(text)
    painter.drawText(QRectF(-w / 2 - 2, -m.height() / 2, w + 4, m.height()), Qt.AlignCenter, text)
    painter.restore()


def _lock(painter, cx, cy, size, colour):
    s = size / 24.0
    pen = QPen(QColor(colour), max(1.0, 2 * s))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    x0, y0 = cx - size / 2, cy - size / 2
    painter.drawRoundedRect(QRectF(x0 + 5 * s, y0 + 11 * s, 14 * s, 10 * s), 2 * s, 2 * s)
    shackle = QPainterPath(QPointF(x0 + 8 * s, y0 + 11 * s))
    shackle.lineTo(x0 + 8 * s, y0 + 7 * s)
    shackle.arcTo(QRectF(x0 + 8 * s, y0 + 3 * s, 8 * s, 8 * s), 180, -180)
    shackle.lineTo(x0 + 16 * s, y0 + 11 * s)
    painter.drawPath(shackle)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(colour)))
    painter.drawEllipse(QPointF(cx, y0 + 16 * s), 1 * s, 1 * s)


def paint(painter, rect, props, ctx):
    cars = car_list(_prop(props, "cars", "MC1,M1,T1,T2,M2,MC2"))
    left = door_state(props.get("doorsLeft", "closed"))
    right = door_state(props.get("doorsRight", "disabled"))
    accent = QColor(str(_prop(props, "accent", "#a855f7")))
    if not accent.isValid():
        accent = QColor("#a855f7")
    n = len(cars)
    W, H = max(1.0, rect.width()), max(1.0, rect.height())
    ox, oy = rect.left(), rect.top()
    bw = W * 0.30
    bx = ox + (W - bw) / 2
    top = oy + H * 0.015
    gap = max(2.0, H * 0.007)
    car_h = (H * 0.97 - gap * (n - 1)) / n if n else H * 0.97
    r_n = min(bw * 0.42, car_h * 0.35)
    r_s = max(2.0, bw * 0.07)
    outline = max(1, round(W * 0.005))
    trim = max(2, round(W * 0.013))
    dw, dh = max(3.0, W * 0.027), car_h * 0.28

    def car_y(i):
        return top + i * (car_h + gap)

    def section(i):
        y, h = car_y(i), car_h
        if i == 0:
            y += r_n
            h -= r_n
        if i == n - 1:
            h -= r_n
        return y, h

    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)

    # Doors first (the bodies cover their inner halves).
    for i in range(n):
        sy, sh = section(i)
        gp = (sh - 2 * dh) / 3
        for k in range(2):
            dy = sy + gp + k * (dh + gp)
            for dx, state in ((bx - dw * 0.55, left), (bx + bw - dw * 0.45, right)):
                if state == "closed":
                    glow = QColor(DOOR["closed"])
                    glow.setAlphaF(0.22)
                    e = dw * 0.6
                    _fill(painter, dx - e, dy - e, dw + 2 * e, dh + 2 * e, glow, round(dw))
                _fill(painter, dx, dy, dw, dh, DOOR[state], round(max(1.0, dw * 0.3)))

    for i in range(n):
        y = car_y(i)
        lead, tail = i == 0, i == n - 1
        sy, sh = section(i)
        if lead or tail:
            # The nose frame stops short of the far end so its antialiased edge
            # never peeps out from under the passenger part.
            inset = 0 if (lead and tail) else 2
            _framed(painter, bx, y + (0 if lead else inset), bw, car_h - inset, BODY, accent, trim, round(r_n))
            py = y + (r_n if lead else 0)
            ph = car_h - (r_n if lead else 0) - (r_n if tail else 0)
            _framed(painter, bx, py, bw, ph, BODY, LINE, outline, 0 if (lead and tail) else round(r_s))
            if lead:
                _fill(painter, bx + outline, y + r_n, bw - 2 * outline, outline + 1, BODY)
            if tail:
                _fill(painter, bx + outline, y + car_h - r_n - outline - 1, bw - 2 * outline, outline + 1, BODY)
            band = max(3.0, r_n * 0.32)
            lr = max(1.5, bw * 0.035)
            painter.setPen(Qt.NoPen)
            if lead:
                _fill(painter, bx + bw * 0.16, y + r_n * 0.55, bw * 0.68, band, GLASS, round(band / 2))
                painter.setBrush(QBrush(QColor("#f4f4f5")))
                for f in (0.32, 0.68):
                    painter.drawEllipse(QPointF(bx + bw * f, y + r_n * 0.30), lr, lr)
            if tail:
                yb = y + car_h
                _fill(painter, bx + bw * 0.16, yb - r_n * 0.55 - band, bw * 0.68, band, GLASS, round(band / 2))
                painter.setBrush(QBrush(QColor("#ef4444")))
                for f in (0.32, 0.68):
                    painter.drawEllipse(QPointF(bx + bw * f, yb - r_n * 0.30), lr, lr)
        else:
            _framed(painter, bx, y, bw, car_h, BODY, LINE, outline, round(r_s))
        # Seats: two columns of three.
        pitch = sh * 0.76 / 3
        seat_h, seat_w = pitch * 0.62, bw * 0.24
        for r in range(3):
            yy = sy + sh * 0.12 + r * pitch + (pitch - seat_h) / 2
            for f in (0.14, 0.62):
                _fill(painter, bx + bw * f, yy, seat_w, seat_h, SEAT, round(max(1.0, seat_w * 0.18)))

    if n >= 3:
        sy, sh = section(1)
        _lock(painter, bx + bw / 2, sy + sh / 2, round(max(8.0, bw * 0.24)), "#d4d4d8")

    # Car names on the right.
    car_font = _font(painter, max(8, round(min(H * 0.025, W * 0.075))), WEIGHT_MEDIUM)
    for i, name in enumerate(cars):
        _rotated_text(painter, bx + bw + W * 0.12, car_y(i) + car_h / 2, name, car_font, "#a1a1aa")

    # Door captions on the left: prefix at the bottom (white), status above it.
    fs = max(8, round(min(H * 0.0227, W * 0.067)))
    cap_font = _font(painter, fs, WEIGHT_SEMIBOLD)
    m = QFontMetricsF(cap_font)
    cx = bx - W * 0.12
    for text, state, fy in ((_prop(props, "leftLabel", ""), left, 0.25),
                            (_prop(props, "rightLabel", ""), right, 0.75)):
        prefix, status = split_caption(text or "")
        pw = m.horizontalAdvance(prefix)
        sw = m.horizontalAdvance(status) if status else 0.0
        length = pw + (fs * 0.3 + sw if status else 0.0)
        cy = oy + H * fy
        _rotated_text(painter, cx, cy + length / 2 - pw / 2, prefix, cap_font, "#fafafa")
        _rotated_text(painter, cx, cy - length / 2 + sw / 2, status, cap_font, CAPTION[state])

    painter.restore()
