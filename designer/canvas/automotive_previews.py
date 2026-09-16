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
    """Placeholder until the real painter lands: a panel with the type name."""
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
    arc_r = 0.42 * d
    stroke_w = 0.05 * d
    tick_len = 0.035 * d
    label_r = 0.52 * d

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

        # Label at 0.52d from center
        lx = cx + label_r * math.cos(angle_rad)
        ly = cy + label_r * math.sin(angle_rad)
        _text(painter, QRectF(lx - 12, ly - 6, 24, 12),
              str(int(mv)), size=0.075 * d,
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
        inner_r = 0.3 * d
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

    # 9. Label (bottom-right)
    if label:
        lbl_rect = QRectF(rect.right() - 0.5 * d, rect.bottom() - 0.06 * d,
                          0.5 * d, 0.06 * d)
        _text(painter, lbl_rect, label, size=0.06 * d,
              color=auto("muted"), weight=WEIGHT_MEDIUM, flags=Qt.AlignRight | Qt.AlignBottom, elide=False)

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
    """ShTripInfo: TODO -- see the brief."""
    _stub(painter, rect, props, "Trip Info")


def paint_segment_bar(painter, rect, props, ctx):
    """ShSegmentBar: TODO -- see the brief."""
    _stub(painter, rect, props, "Segment Bar")


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
    """ShVehicleStatus: TODO -- see the brief."""
    _stub(painter, rect, props, "Vehicle Status")


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
