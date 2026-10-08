"""Canvas previews for the Rail widgets (ShSpeedArc, ShTractionBar, ShStationLine,
ShTrainConsist, ShStatusCard) -- each mirrors its ui/qml/Shadcn/Sh*.qml at rest.
PAINTERS is merged into widget_previews._PAINTERS."""
from designer.canvas.rail import speed_arc, station_line, status_card, traction_bar, train_consist

PAINTERS = {
    "ShSpeedArc": speed_arc.paint,
    "ShTractionBar": traction_bar.paint,
    "ShStationLine": station_line.paint,
    "ShTrainConsist": train_consist.paint,
    "ShStatusCard": status_card.paint,
}
