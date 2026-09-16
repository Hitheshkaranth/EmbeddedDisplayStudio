"""Canvas previews for the Automotive widgets -- mirror ui/qml/Shadcn/Sh*.qml.

Same rules as widget_previews.py: each painter reproduces the QML component at
rest, reading the same properties and Theme.qml auto* colours (the AUTO table in
widget_previews). One painter per registered type; PAINTERS is merged into the
main table.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainterPath,
                           QPen, QPolygonF)

from designer.canvas.widget_previews import (
    FONT, WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, _number, _prop, _rounded, _text, auto, token,
)


def _stub(painter, rect, props, display_name):
    """Placeholder until the real painter lands: a panel with the type name."""
    _rounded(painter, rect, auto("panel"), 8, auto("tileBorder"), 1)
    _text(painter, rect, display_name, size=FONT["sm"], color=auto("muted"),
          flags=Qt.AlignCenter)


def paint_cluster_gauge(painter, rect, props, ctx):
    """ShClusterGauge: TODO -- see the brief."""
    _stub(painter, rect, props, "Cluster Gauge")


def paint_gear_indicator(painter, rect, props, ctx):
    """ShGearIndicator: TODO -- see the brief."""
    _stub(painter, rect, props, "Gear Indicator")


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
    """ShDriveMode: TODO -- see the brief."""
    _stub(painter, rect, props, "Drive Mode")


def paint_telltale(painter, rect, props, ctx):
    """ShTelltale: TODO -- see the brief."""
    _stub(painter, rect, props, "Telltale")


def paint_trip_info(painter, rect, props, ctx):
    """ShTripInfo: TODO -- see the brief."""
    _stub(painter, rect, props, "Trip Info")


def paint_segment_bar(painter, rect, props, ctx):
    """ShSegmentBar: TODO -- see the brief."""
    _stub(painter, rect, props, "Segment Bar")


def paint_icon_tile(painter, rect, props, ctx):
    """ShIconTile: TODO -- see the brief."""
    _stub(painter, rect, props, "Icon Tile")


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
