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
