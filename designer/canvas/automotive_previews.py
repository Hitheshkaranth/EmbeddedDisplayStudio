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
