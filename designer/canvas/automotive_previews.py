"""Canvas previews for the Automotive widgets -- mirror ui/qml/Shadcn/Sh*.qml.

Same rules as widget_previews.py: each painter reproduces the QML component at
rest, reading the same properties and Theme.qml auto* colours (the AUTO table in
widget_previews). One painter per registered type; PAINTERS is merged into the
main table.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainterPath, QPen, QPolygonF

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
    """ShAutoLevel: TODO -- see the brief."""
    _stub(painter, rect, props, "Level Bar")


def paint_auto_readout(painter, rect, props, ctx):
    """ShAutoReadout: TODO -- see the brief."""
    _stub(painter, rect, props, "Readout")


def paint_drive_mode(painter, rect, props, ctx):
    """ShDriveMode: TODO -- see the brief."""
    _stub(painter, rect, props, "Drive Mode")


def paint_telltale(painter, rect, props, ctx):
    """ShTelltale: TODO -- see the brief."""
    _stub(painter, rect, props, "Telltale")


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
    """ShIconTile: TODO -- see the brief."""
    _stub(painter, rect, props, "Icon Tile")


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
