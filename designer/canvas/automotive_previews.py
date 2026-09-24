"""Canvas previews for the Automotive widgets -- mirror ui/qml/Shadcn/Sh*.qml.

Same rules as widget_previews.py: each painter reproduces the QML component at
rest, reading the same properties and Theme.qml auto* colours (the AUTO table in
widget_previews). One painter per registered type; PAINTERS is merged into the
main table.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPolygonF, QRadialGradient)

from designer.canvas.widget_previews import (
    FONT, WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, _number, _prop, _rounded, _text, auto, token,
)


def _painter_font(painter, pixel_size, weight=QFont.Normal):
    font = QFont(painter.font())
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


def _stub(painter, rect, props, display_name):
    """The placeholder look, a panel with the type name. No type paints with it;
    tests/test_automotive_contract.py checks that no real painter matches it."""
    _rounded(painter, rect, auto("panel"), 8, auto("tileBorder"), 1)
    _text(painter, rect, display_name, size=FONT["sm"], color=auto("muted"),
          flags=Qt.AlignCenter)


def paint_cluster_gauge(painter, rect, props, ctx):
    """ShClusterGauge: arc-based automotive cluster instrument."""
    value = _number(props, "value", 4.2)
    minimum = _number(props, "minimumValue", 0.0)
    maximum = _number(props, "maximumValue", 8.0)
    major_step = _number(props, "majorStep", 1.0)
    redline_from = _number(props, "redlineFrom", 7.0)
    sweep = _number(props, "sweep", 240.0)
    readout = str(_prop(props, "readout", "137"))
    readout_unit = str(_prop(props, "readoutUnit", "km/h"))
    caption = str(_prop(props, "caption", ""))
    label = str(_prop(props, "label", "x1000 RPM"))
    decimals = int(_number(props, "decimals", 0))
    show_inner = bool(_prop(props, "showInnerDial", "true") in ("true", "True", True, 1, "1"))
    span = max(0.0001, maximum - minimum)
    clamped = max(minimum, min(maximum, value))

    d = min(rect.width(), rect.height())
    cx = rect.center().x()
    cy = rect.center().y()
    start_angle = 90 + (360 - sweep) / 2  # degrees, canvas coords (CW from 3 o'clock)
    arc_r = 0.38 * d
    stroke_w = 0.05 * d
    tick_len = 0.035 * d
    label_r = 0.47 * d

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(Qt.NoBrush)

    # 1. Scale track (unfilled arc)
    painter.setPen(QPen(auto("track"), stroke_w, Qt.SolidLine, Qt.FlatCap))
    painter.drawArc(
        QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2),
        int(-(start_angle) * 16),
        int(-sweep * 16))

    # 2. Redline band (always visible)
    if redline_from < maximum:
        red_f0 = (redline_from - minimum) / span
        painter.setPen(QPen(auto("redline"), stroke_w, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(
            QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2),
            int(-(start_angle + sweep * red_f0) * 16),
            int(-(sweep * (1.0 - red_f0)) * 16))

    # 3. Value arc with gradient
    frac = (clamped - minimum) / span
    value_angle = start_angle + sweep * frac  # degrees

    # Gradient for the value arc (horizontal mapping: left=deep, right=accent)
    grad = QLinearGradient(cx - arc_r, cy, cx + arc_r, cy)
    grad.setColorAt(0.0, auto("accentDeep"))
    grad.setColorAt(1.0, auto("accent"))
    painter.setPen(QPen(grad, stroke_w, Qt.SolidLine, Qt.FlatCap))
    painter.drawArc(
        QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2),
        int(-start_angle * 16),
        int(-(value_angle - start_angle) * 16))

    # 2 px glow line on outer edge of value arc
    glow_r = arc_r + stroke_w * 0.35
    painter.setPen(QPen(auto("glow"), 2, Qt.SolidLine, Qt.FlatCap))
    painter.drawArc(
        QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2),
        int(-start_angle * 16),
        int(-(value_angle - start_angle) * 16))

    # Redline portion of value arc (past redlineFrom)
    if clamped > redline_from and redline_from < maximum:
        red_f0_2 = (redline_from - minimum) / span
        red_start = start_angle + sweep * red_f0_2
        painter.setPen(QPen(auto("redline"), stroke_w, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(
            QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2),
            int(-red_start * 16),
            int(-(value_angle - red_start) * 16))

    # 4. Major ticks and labels
    steps = int(round(span / major_step))
    for i in range(steps + 1):
        mv = minimum + i * major_step
        if mv > maximum + 0.001:
            break
        mv_frac = (mv - minimum) / span
        angle_deg = start_angle + sweep * mv_frac
        angle_rad = math.radians(angle_deg)

        # Tick line
        tx1 = cx + (arc_r + tick_len) * math.cos(angle_rad)
        ty1 = cy + (arc_r + tick_len) * math.sin(angle_rad)
        tx2 = cx + arc_r * math.cos(angle_rad)
        ty2 = cy + arc_r * math.sin(angle_rad)

        is_redline = mv >= redline_from
        painter.setPen(QPen(
            auto("redline") if is_redline else auto("line"),
            2, Qt.SolidLine, Qt.FlatCap))
        painter.drawLine(QPointF(tx1, ty1), QPointF(tx2, ty2))

        # Label at 0.52d from centre, in a box the glyphs actually fit.
        lx = cx + label_r * math.cos(angle_rad)
        ly = cy + label_r * math.sin(angle_rad)
        label_size = max(7, int(0.068 * d))
        box_w, box_h = label_size * 2.4, label_size * 1.4
        _text(painter, QRectF(lx - box_w / 2, ly - box_h / 2, box_w, box_h),
              str(int(mv)), size=label_size,
              color=auto("redline") if is_redline else auto("line"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter, elide=False)

    # 5. Minor ticks (4 between each major step)
    for i in range(steps):
        base_val = minimum + i * major_step
        for m in range(1, 5):
            m_val = base_val + m * (major_step / 5)
            if m_val > maximum + 0.001:
                break
            m_frac = (m_val - minimum) / span
            m_angle_deg = start_angle + sweep * m_frac
            m_angle_rad = math.radians(m_angle_deg)
            minor_len = tick_len * 0.5
            mx1 = cx + (arc_r + minor_len) * math.cos(m_angle_rad)
            my1 = cy + (arc_r + minor_len) * math.sin(m_angle_rad)
            mx2 = cx + arc_r * math.cos(m_angle_rad)
            my2 = cy + arc_r * math.sin(m_angle_rad)
            painter.setPen(QPen(auto("muted"), 1.2, Qt.SolidLine, Qt.FlatCap))
            painter.drawLine(QPointF(mx1, my1), QPointF(mx2, my2))

    # 6. Inner dial
    if show_inner:
        inner_r = 0.28 * d
        # Fill circle
        painter.setBrush(QBrush(auto("panel")))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        # Radial gradient overlay (center: accentDeep 20% alpha, edge: transparent)
        rad_grad = QRadialGradient(QPointF(cx, cy), inner_r)
        rad_grad.setColorAt(0.0, QColor(auto("accentDeep").red(),
                                         auto("accentDeep").green(),
                                         auto("accentDeep").blue(), 51))
        rad_grad.setColorAt(1.0, QColor(auto("accentDeep").red(),
                                         auto("accentDeep").green(),
                                         auto("accentDeep").blue(), 0))
        painter.setBrush(QBrush(rad_grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        # Ring
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(auto("tileBorder"), 1.5, Qt.SolidLine, Qt.FlatCap))
        painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

    # 7 & 8. Readout + readoutUnit (Text elements for crispness)
    readout_text = readout if readout else f"{clamped:.{decimals}f}"
    readout_size = 0.28 * d
    readout_rect = QRectF(cx - d * 0.4, cy - readout_size * 0.5,
                          d * 0.8, readout_size)
    _text(painter, readout_rect, readout_text, size=readout_size,
          color=auto("text"), weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter, elide=False)

    if readout_unit:
        unit_rect = QRectF(cx - d * 0.3, readout_rect.bottom() + 2,
                           d * 0.6, 0.08 * d)
        _text(painter, unit_rect, readout_unit, size=0.08 * d,
              color=auto("muted"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter, elide=False)

    # Caption above readout
    if caption:
        cap_rect = QRectF(cx - d * 0.3,
                          readout_rect.top() - 0.07 * d - 6,
                          d * 0.6, 0.07 * d)
        _text(painter, cap_rect, caption, size=0.07 * d,
              color=auto("amber"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter, elide=False)

    # 9. Label at the foot of the arc's opening, as the QML places it.
    if label:
        label_size = max(7, int(0.045 * d))
        lbl_rect = QRectF(cx + 0.2 * d, cy + 0.33 * d - label_size * 0.7, 0.4 * d, label_size * 1.4)
        _text(painter, lbl_rect, label, size=label_size,
              color=auto("muted"), weight=WEIGHT_MEDIUM, flags=Qt.AlignLeft | Qt.AlignVCenter, elide=False)

    painter.restore()


def paint_gear_indicator(painter, rect, props, ctx):
    """ShGearIndicator: the gear row in list order, the engaged gear large
    and bright, a lighter mode digit after it. No panel -- the QML has none."""
    gear = str(_prop(props, "gear", "D"))
    mode_number = int(_number(props, "modeNumber", 4))
    show_all = _prop(props, "showAll", True) in (True, "true", "True", 1, "1")
    gears = [g.strip() for g in str(_prop(props, "gears", "P,R,N,D")).split(",") if g.strip()]
    if gear and gear not in gears:
        gears.append(gear)
    if not show_all:
        gears = [gear]

    h = rect.height()
    spacing = max(2, int(h * 0.12))
    baseline = rect.bottom() - h * 0.12

    def font_for(size, weight):
        font = QFont()
        font.setPixelSize(max(8, int(size)))
        font.setWeight(weight)
        return font

    big = font_for(h * 0.62, WEIGHT_SEMIBOLD)
    small = font_for(h * 0.4, WEIGHT_MEDIUM)
    digit = font_for(h * 0.45, QFont.Normal)
    runs = []
    for g in gears:
        current = g == gear
        runs.append((g, big if current else small, auto("text") if current else auto("muted"), 0))
        if current and mode_number > 0:
            runs.append((str(mode_number), digit, auto("line"), h * 0.02))
    total = sum(QFontMetrics(f).horizontalAdvance(t) for t, f, _, _ in runs) + spacing * (len(gears) - 1)
    x = rect.center().x() - total / 2
    for index, (text, font, colour, lift) in enumerate(runs):
        painter.setFont(font)
        painter.setPen(QPen(colour))
        width = QFontMetrics(font).horizontalAdvance(text)
        painter.drawText(QPointF(x, baseline - lift), text)
        x += width + (0 if text.isdigit() and index + 1 < len(runs) and False else 0)
        # a digit hugs its gear; the gap comes before the next gear
        if not (index + 1 < len(runs) and runs[index + 1][3] > 0):
            x += spacing
        else:
            x += 1


def paint_auto_level(painter, rect, props, ctx):
    """ShAutoLevel: the curved fuel / coolant bar -- track, always-visible
    red zone, accent gradient fill from the bottom, ticks, side labels and
    an icon placeholder under the bar."""
    minimum = _number(props, "minimumValue", 0.0)
    maximum = _number(props, "maximumValue", 100.0)
    span = max(0.0001, maximum - minimum)
    fraction = max(0.0, min(1.0, (_number(props, "value", 55.0) - minimum) / span))
    red_zone = str(_prop(props, "redZone", "low"))
    zone_span = max(0.0, min(1.0, _number(props, "redZoneSpan", 12.0) / 100.0))
    curved = _prop(props, "curved", True) in (True, "true", "True", 1, "1")
    show_ticks = _prop(props, "showTicks", True) in (True, "true", "True", 1, "1")

    w, h = rect.width(), rect.height()
    bar_w = w * 0.22
    x = rect.left() + w * 0.55 + (w * 0.45 - bar_w) / 2
    top, bar_h = rect.top() + h * 0.02, h * 0.78
    bottom, mid_y, r = top + bar_h, top + bar_h / 2, bar_w / 2
    bulge = w * 0.18 if curved else 0.0

    outline = QPainterPath()
    outline.moveTo(x, top + r)
    outline.arcTo(QRectF(x, top, bar_w, bar_w), 180, -180)
    outline.quadTo(QPointF(x + bar_w - bulge, mid_y), QPointF(x + bar_w, bottom - r))
    outline.arcTo(QRectF(x, bottom - bar_w, bar_w, bar_w), 0, -180)
    outline.quadTo(QPointF(x - bulge, mid_y), QPointF(x, top + r))
    outline.closeSubpath()

    painter.save()
    painter.setClipPath(outline)
    wide = QRectF(x - bulge - 1, top - 1, bar_w + bulge + 2, bar_h + 2)
    painter.fillRect(wide, auto("track"))
    zone = None
    if red_zone == "low":
        zone = (bottom - bar_h * zone_span, bottom)
    elif red_zone == "high":
        zone = (top, top + bar_h * zone_span)
    if zone:
        dim = QColor(auto("redline"))
        dim.setAlphaF(0.85)
        painter.fillRect(QRectF(wide.left(), zone[0], wide.width(), zone[1] - zone[0]), dim)
    fill_top = bottom - bar_h * fraction
    if fraction > 0:
        gradient = QLinearGradient(0, bottom, 0, fill_top)
        gradient.setColorAt(0.0, auto("accentDeep"))
        gradient.setColorAt(1.0, auto("accent"))
        painter.fillRect(QRectF(wide.left(), fill_top, wide.width(), bottom - fill_top), QBrush(gradient))
        if zone:
            red_top, red_bottom = max(zone[0], fill_top), min(zone[1], bottom)
            if red_bottom > red_top:
                painter.fillRect(QRectF(wide.left(), red_top, wide.width(), red_bottom - red_top),
                                 auto("redline"))
        painter.fillRect(QRectF(wide.left(), fill_top, wide.width(), 2), auto("glow"))
    painter.restore()

    if show_ticks:
        for i in range(11):
            f = i / 10
            y = bottom - bar_h * f
            t = 1 - abs(f - 0.5) * 2
            edge = x - bulge * (1 - (1 - t) ** 2) * 0.5
            length = w * 0.12 if i % 5 == 0 else w * 0.06
            painter.setPen(QPen(auto("line"), 1.5 if i % 5 == 0 else 1.0))
            painter.drawLine(QPointF(edge - 2, y), QPointF(edge - 2 - length, y))

    label_w = max(4.0, x - bulge - w * 0.16 - rect.left())
    for text, f in ((str(_prop(props, "topLabel", "F")), 1.0), (str(_prop(props, "midLabel", "1/2")), 0.5),
                    (str(_prop(props, "bottomLabel", "E")), 0.0)):
        if text:
            y = top + bar_h * (1 - f)
            _text(painter, QRectF(rect.left(), y - h * 0.05, label_w, h * 0.1), text,
                  size=max(7, int(w * 0.14)), color=auto("line"), weight=WEIGHT_SEMIBOLD,
                  flags=Qt.AlignRight | Qt.AlignVCenter, elide=False)

    if str(_prop(props, "icon", "")):
        size = w * 0.3
        cx = x + bar_w / 2
        cy = bottom + (rect.bottom() - bottom) / 2
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(auto("line"), max(1.5, size * 0.09)))
        painter.drawRoundedRect(QRectF(cx - size / 2 + 2, cy - size / 2 + 2, size - 4, size - 4),
                                size * 0.25, size * 0.25)


def paint_auto_readout(painter, rect, props, ctx):
    """ShAutoReadout: the big number, its unit on the baseline, an icon
    placeholder on the chosen side; red outside the warn limits."""
    value = _number(props, "value", 0.0)
    decimals = int(_number(props, "decimals", 0))
    unit = str(_prop(props, "unit", ""))
    icon = str(_prop(props, "icon", ""))
    label = str(_prop(props, "label", ""))
    icon_left = str(_prop(props, "iconSide", "right")) == "left"
    warn_below = _number(props, "warnBelow", 0.0)
    warn_above = _number(props, "warnAbove", 0.0)
    warns = (warn_below != 0 and value < warn_below) or (warn_above != 0 and value > warn_above)

    h = rect.height()
    icon_size = round(h * 0.6)
    slot = icon_size + round(h * 0.15) if icon else 0
    if icon:
        ix = rect.left() if icon_left else rect.right() - icon_size
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(auto("red") if warns else auto("line"), max(1.5, icon_size * 0.09)))
        painter.drawRoundedRect(QRectF(ix + 2, rect.center().y() - icon_size / 2 + 2,
                                       icon_size - 4, icon_size - 4), icon_size * 0.25, icon_size * 0.25)

    block = QRectF(rect.left() + (slot if icon_left else 0), rect.top(), max(1.0, rect.width() - slot), h)
    number_size = max(8, int(h * 0.5))
    unit_size = max(7, int(h * 0.28))
    label_size = max(7, int(h * 0.2))
    content_h = number_size + (label_size if label else 0)
    y = block.center().y() - content_h / 2
    if label:
        _text(painter, QRectF(block.left(), y, block.width(), label_size), label, size=label_size,
              color=auto("muted"), flags=Qt.AlignLeft | Qt.AlignVCenter)
        y += label_size
    number = f"{value:.{decimals}f}"
    font = QFont()
    font.setPixelSize(number_size)
    font.setWeight(WEIGHT_SEMIBOLD)
    unit_font = QFont()
    unit_font.setPixelSize(unit_size)
    unit_w = QFontMetrics(unit_font).horizontalAdvance(unit) + 3 if unit else 0
    number_w = min(QFontMetrics(font).horizontalAdvance(number), block.width() - unit_w)
    x = block.left() if icon_left else block.right() - unit_w - number_w
    painter.setFont(font)
    painter.setPen(QPen(auto("red") if warns else auto("text")))
    baseline = y + QFontMetrics(font).ascent()
    painter.drawText(QPointF(x, baseline), number)
    if unit:
        painter.setFont(unit_font)
        painter.setPen(QPen(auto("muted")))
        painter.drawText(QPointF(x + number_w + 3, baseline), unit)


def paint_drive_mode(painter, rect, props, ctx):
    """ShDriveMode: the caption over the current mode name between two
    chevrons. No panel behind it -- the QML draws none either."""
    modes = [m.strip() for m in str(_prop(props, "modes", "ECO,COMFORT,SPORT")).split(",")
             if m.strip()]
    current = int(_number(props, "currentIndex", 2))
    label = str(_prop(props, "label", "Drive mode"))
    mode_name = modes[current] if 0 <= current < len(modes) else ""

    h = rect.height()
    if label:
        _text(painter, QRectF(rect.left(), rect.top() + h * 0.04, rect.width(), h * 0.3),
              label, size=max(8, int(h * 0.24)), color=auto("muted"),
              weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)

    row = QRectF(rect.left(), rect.top() + h * 0.36, rect.width(), h * 0.62)
    _text(painter, row, mode_name, size=max(8, int(h * 0.34)), color=auto("amber"),
          weight=WEIGHT_SEMIBOLD, flags=Qt.AlignCenter)
    # Chevrons sit either side of the name, spaced as the QML Row spaces them.
    metrics = painter.fontMetrics()
    half = metrics.horizontalAdvance(mode_name) / 2 + h * 0.2 + h * 0.45
    chevron = max(8, int(h * 0.36))
    for glyph, cx in (("‹", row.center().x() - half), ("›", row.center().x() + half)):
        _text(painter, QRectF(cx - h * 0.45, row.top(), h * 0.9, row.height()), glyph,
              size=chevron, color=auto("line"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_telltale(painter, rect, props, ctx):
    """ShTelltale: icon lamp -- bright when lit, dim ghost when unlit, with glow."""
    lit = bool(_prop(props, "lit", True))
    blink = bool(_prop(props, "blink", False))
    color_name = str(_prop(props, "color", "amber"))
    label = str(_prop(props, "label", ""))

    # Map color name
    color_map = {"amber": auto("amber"), "green": auto("green"),
                 "red": auto("red"), "blue": auto("blue"),
                 "white": auto("text")}
    lamp_color = color_map.get(color_name, auto("amber"))

    dim_color = QColor(auto("muted"))
    if lit:
        icon_color = lamp_color
        opacity = 1.0
    else:
        icon_color = dim_color
        opacity = 0.35

    # Glow behind icon when lit
    if lit:
        glow_rect = QRectF(rect.left() + rect.width() * 0.05,
                           rect.top() + rect.height() * 0.05,
                           rect.width() * 0.9, rect.height() * 0.9)
        glow_col = QColor(lamp_color)
        glow_col.setAlphaF(0.18)
        painter.setBrush(QBrush(glow_col))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(glow_rect, rect.width() * 0.5, rect.height() * 0.5)

    # Icon placeholder: rounded square (like ShIcon would render)
    icon_size = int(min(rect.width(), rect.height()) * 0.62)
    if label:
        icon_size = int(rect.height() * 0.5)

    cx = rect.left() + rect.width() * 0.5
    cy = rect.top() + rect.height() * (0.38 if label else 0.5)
    icon_rect = QRectF(cx - icon_size / 2, cy - icon_size / 2, icon_size, icon_size)

    painter.save()
    painter.setOpacity(opacity)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(icon_color, max(1.5, icon_size * 0.09)))
    painter.drawRoundedRect(icon_rect.adjusted(2, 2, -2, -2), icon_size * 0.25, icon_size * 0.25)
    painter.restore()

    # Blink: hint at 0.6 alpha
    if blink and lit:
        painter.save()
        painter.setOpacity(0.6)
        painter.setBrush(QBrush(lamp_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(icon_rect, icon_size * 0.25, icon_size * 0.25)
        painter.restore()

    # Label
    if label:
        label_rect = QRectF(rect.left(), rect.top() + rect.height() * 0.65,
                            rect.width(), rect.height() * 0.3)
        _text(painter, label_rect, label, size=int(rect.height() * 0.18),
              color=auto("muted"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_trip_info(painter, rect, props, ctx):
    """ShTripInfo: card with title and two label/value/unit rows."""
    w = rect.width()
    h = rect.height()
    radius = int(h * 0.08)

    # Background card
    _rounded(painter, rect, auto("tileBg"), radius, auto("tileBorder"), 1)

    margin = int(h * 0.1)
    title_size = int(h * 0.15)
    label_size = int(h * 0.16)
    value_size = int(h * 0.2)
    unit_size = int(h * 0.14)
    row_height = int(h * 0.3)

    title = _prop(props, "title", "Distance")
    r1l = _prop(props, "row1Label", "Day")
    r1v = _prop(props, "row1Value", "352")
    r1u = _prop(props, "row1Unit", "km")
    r2l = _prop(props, "row2Label", "Total")
    r2v = _prop(props, "row2Value", "110 593")
    r2u = _prop(props, "row2Unit", "km")

    y = margin
    # Title
    if title:
        _text(painter, QRectF(margin, y, w - 2 * margin, title_size),
              title, size=title_size, color=auto("muted"),
              flags=Qt.AlignLeft | Qt.AlignTop)
        y += title_size

    # Row 1
    if r1l or r1v:
        row_y = y + 2
        _text(painter, QRectF(margin, row_y, w * 0.45, row_height),
              r1l, size=label_size, color=auto("line"),
              flags=Qt.AlignLeft | Qt.AlignVCenter)
        _text(painter, QRectF(w * 0.55, row_y, w * 0.35, row_height),
              r1v, size=value_size, color=auto("text"), weight=WEIGHT_SEMIBOLD,
              flags=Qt.AlignRight | Qt.AlignVCenter)
        if r1u:
            _text(painter, QRectF(w * 0.85, row_y, w * 0.15, row_height),
                  r1u, size=unit_size, color=auto("muted"),
                  flags=Qt.AlignRight | Qt.AlignVCenter)
        y += row_height
        # Divider
        painter.setPen(QPen(auto("tileBorder"), 1))
        painter.drawLine(QPointF(margin, y), QPointF(w - margin, y))
        y += 1

    # Row 2
    if r2l or r2v:
        row_y = y + 2
        _text(painter, QRectF(margin, row_y, w * 0.45, row_height),
              r2l, size=label_size, color=auto("line"),
              flags=Qt.AlignLeft | Qt.AlignVCenter)
        _text(painter, QRectF(w * 0.55, row_y, w * 0.35, row_height),
              r2v, size=value_size, color=auto("text"), weight=WEIGHT_SEMIBOLD,
              flags=Qt.AlignRight | Qt.AlignVCenter)
        if r2u:
            _text(painter, QRectF(w * 0.85, row_y, w * 0.15, row_height),
                  r2u, size=unit_size, color=auto("muted"),
                  flags=Qt.AlignRight | Qt.AlignVCenter)


def paint_segment_bar(painter, rect, props, ctx):
    """ShSegmentBar: segmented bar (SOC) with optional label and % text."""
    w = rect.width()
    h = rect.height()

    value = _number(props, "value", 60.0)
    min_val = _number(props, "minimumValue", 0.0)
    max_val = _number(props, "maximumValue", 100.0)
    seg_count = max(1, min(60, int(_number(props, "segments", 12))))
    label = _prop(props, "label", "SOC")
    show_pct = props.get("showPercent", True)
    low_level = _number(props, "lowLevel", 20.0)

    span = max(0.0001, max_val - min_val)
    frac = max(0.0, min(1.0, (value - min_val) / span))
    filled_count = frac * seg_count
    full_cells = int(filled_count)
    partial = filled_count - full_cells
    last_full = partial >= 0.5
    total_full = full_cells + 1 if last_full else full_cells

    low = value <= low_level and low_level > 0
    accent = auto("redline") if low else auto("accent")
    accent_deep = auto("redline") if low else auto("accentDeep")
    pct_color = auto("red") if low else auto("text")

    gap = int(h * 0.12)
    radius = int(h * 0.1)

    # Label on the left
    label_width = 0
    if label:
        _text(painter, QRectF(2, 0, h, h), label, size=int(h * 0.4),
              color=auto("muted"), flags=Qt.AlignLeft | Qt.AlignVCenter)
        fm = painter.fontMetrics()
        label_width = fm.horizontalAdvance(label) + 4

    # Percent text on the right
    pct_width = 0
    if show_pct:
        pct_text = str(round(frac * 100)) + "%"
        _text(painter, QRectF(w - h, 0, h, h), pct_text, size=int(h * 0.45),
              color=pct_color, weight=WEIGHT_SEMIBOLD, flags=Qt.AlignRight | Qt.AlignVCenter)
        fm = painter.fontMetrics()
        pct_width = fm.horizontalAdvance(pct_text) + 4

    # Segment cells
    avail = w - 4 - label_width - pct_width - 8
    if avail < 0:
        avail = 0
    cell_w = (avail - gap * (seg_count - 1)) / seg_count
    if cell_w < 0:
        cell_w = 0

    cell_y = (h - cell_w) / 2.0
    x = 4 + label_width

    for i in range(seg_count):
        if i < total_full:
            brush_color = accent_deep if i == 0 else accent
        else:
            brush_color = auto("track")
        painter.setBrush(QBrush(brush_color))
        painter.setPen(Qt.NoPen)
        if cell_w >= 2 * radius:
            painter.drawRoundedRect(x, cell_y, cell_w, cell_w, radius, radius)
        else:
            painter.drawRoundedRect(x, cell_y, cell_w, cell_w, int(cell_w / 2), int(cell_w / 2))
        x += cell_w + gap


def paint_icon_tile(painter, rect, props, ctx):
    """ShIconTile: rounded tile with icon and label below."""
    active = bool(_prop(props, "active", False))
    label = str(_prop(props, "label", "BT"))

    tile_h = int(rect.height() * 0.72)
    tile_w = rect.width()
    tile_rect = QRectF(rect.left(), rect.top(), tile_w, tile_h)
    radius = int(rect.width() * 0.18)

    # Glow behind tile when active
    if active:
        glow_rect = QRectF(tile_rect.left() - 4, tile_rect.top() - 4,
                           tile_rect.width() + 8, tile_rect.height() + 8)
        glow_col = QColor(auto("accent"))
        glow_col.setAlphaF(0.20)
        painter.setBrush(QBrush(glow_col))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(glow_rect, radius + 4, radius + 4)

    # Tile background
    painter.setBrush(QBrush(auto("tileBg")))
    border_col = QColor(auto("accent")) if active else QColor(auto("tileBorder"))
    painter.setPen(QPen(border_col, 2 if active else 1))
    painter.drawRoundedRect(tile_rect, radius, radius)

    # Icon placeholder centred in tile
    icon_size = int(tile_w * 0.42)
    cx = tile_rect.center().x()
    cy = tile_rect.center().y()
    icon_r = QRectF(cx - icon_size / 2, cy - icon_size / 2, icon_size, icon_size)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(auto("text"), max(1.5, icon_size * 0.08)))
    painter.drawRoundedRect(icon_r.adjusted(2, 2, -2, -2), icon_size * 0.3, icon_size * 0.3)

    # Label
    label_rect = QRectF(rect.left(), tile_rect.bottom() + 4,
                        rect.width(), rect.height() - tile_rect.height() - 4)
    _text(painter, label_rect, label, size=int(rect.height() * 0.14),
          color=auto("text"), weight=WEIGHT_MEDIUM, flags=Qt.AlignCenter)


def paint_vehicle_status(painter, rect, props, ctx):
    """ShVehicleStatus: top-view car outline, four wheels (amber when low),
    the pressures at the corners (red when low), unit under, label over."""
    warn_below = _number(props, "warnBelow", 1.8)
    decimals = int(_number(props, "decimals", 1))
    values = {name: _number(props, name, 0.0) for name in ("frontLeft", "frontRight", "rearLeft", "rearRight")}

    def low(v):
        return warn_below > 0 and v < warn_below

    w, h = rect.width(), rect.height()
    body_w, body_h = w * 0.42, h * 0.7
    x, y = rect.left() + (w - body_w) / 2, rect.top() + (h - body_h) / 2
    wheel_w, wheel_h = w * 0.09, h * 0.14
    radius = min(w * 0.16, body_w / 2, body_h / 2)

    wheels = [(x - wheel_w * 0.6, y + body_h * 0.12, values["frontLeft"]),
              (x + body_w - wheel_w * 0.4, y + body_h * 0.12, values["frontRight"]),
              (x - wheel_w * 0.6, y + body_h * 0.88 - wheel_h, values["rearLeft"]),
              (x + body_w - wheel_w * 0.4, y + body_h * 0.88 - wheel_h, values["rearRight"])]
    painter.setPen(Qt.NoPen)
    for wx, wy, v in wheels:
        colour = QColor(auto("amber")) if low(v) else QColor(auto("line"))
        if not low(v):
            colour.setAlphaF(0.7)
        painter.setBrush(QBrush(colour))
        painter.drawRoundedRect(QRectF(wx, wy, wheel_w, wheel_h), wheel_w * 0.3, wheel_w * 0.3)

    fill = QColor(auto("accentDeep"))
    fill.setAlphaF(0.25)
    painter.setBrush(QBrush(fill))
    painter.setPen(QPen(auto("accent"), 1.5))
    painter.drawRoundedRect(QRectF(x, y, body_w, body_h), radius, radius)
    glass = QColor(auto("accent"))
    glass.setAlphaF(0.6)
    painter.setPen(QPen(glass, 1.2))
    inset = body_w * 0.12
    for f in (0.28, 0.72):
        painter.drawLine(QPointF(x + inset, y + body_h * f), QPointF(x + body_w - inset, y + body_h * f))

    size = max(7, int(h * 0.12))
    for name, right, bottom in (("frontLeft", False, False), ("frontRight", True, False),
                                ("rearLeft", False, True), ("rearRight", True, True)):
        v = values[name]
        text_w = w * 0.3
        tx = x + body_w + wheel_w + 2 if right else x - wheel_w - 2 - text_w
        ty = y + body_h - h * 0.06 - size if bottom else y + h * 0.06
        _text(painter, QRectF(tx, ty, text_w, size * 1.2), f"{v:.{decimals}f}", size=size,
              color=auto("red") if low(v) else auto("text"), weight=WEIGHT_SEMIBOLD,
              flags=(Qt.AlignLeft if right else Qt.AlignRight) | Qt.AlignVCenter, elide=False)

    small = max(7, int(h * 0.08))
    unit = str(_prop(props, "unit", ""))
    if unit:
        _text(painter, QRectF(rect.left(), rect.bottom() - small * 1.3, w, small * 1.3), unit,
              size=small, color=auto("muted"), flags=Qt.AlignCenter)
    label = str(_prop(props, "label", ""))
    if label:
        _text(painter, QRectF(rect.left(), rect.top(), w, small * 1.3), label,
              size=small, color=auto("muted"), flags=Qt.AlignCenter)


PAINTERS = {
    "ShClusterGauge": paint_cluster_gauge,
    "ShGearIndicator": paint_gear_indicator,
    "ShAutoLevel": paint_auto_level,
    "ShAutoReadout": paint_auto_readout,
    "ShDriveMode": paint_drive_mode,
    "ShTelltale": paint_telltale,
    "ShTripInfo": paint_trip_info,
    "ShSegmentBar": paint_segment_bar,
    "ShIconTile": paint_icon_tile,
    "ShVehicleStatus": paint_vehicle_status,
}
