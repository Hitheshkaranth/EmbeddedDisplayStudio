"""Shared renderer for the physical FlyVi display bezel."""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPixmap


BEZEL_MARGIN_PCT = 0.095


def bezel_logo() -> QPixmap:
    return QPixmap(os.path.join(os.path.dirname(__file__), "resources", "flyvi_logo_full.png"))


def screen_bezel_geometry(width: float, height: float):
    """Return the outer bezel rectangle and margin around a pixel screen."""
    bezel_width = width / (1 - 2 * BEZEL_MARGIN_PCT)
    margin = bezel_width * BEZEL_MARGIN_PCT
    return QRectF(-margin, -margin, bezel_width, height + 2 * margin), margin


def paint_device_bezel(painter, bezel_rect: QRectF, margin: float,
                        logo: QPixmap, led_state: int = 0) -> None:
    """Paint the canonical shadow, enclosure, brand mark and status LED."""
    bx, by, bw, bh = (bezel_rect.x(), bezel_rect.y(),
                      bezel_rect.width(), bezel_rect.height())
    shadow_path = QPainterPath()
    shadow_path.addRoundedRect(QRectF(bx + 4, by + 4, bw, bh), 28, 28)
    painter.fillPath(shadow_path, QColor(0, 0, 0, 40))

    bezel_path = QPainterPath()
    bezel_path.addRoundedRect(bezel_rect, 28, 28)
    painter.fillPath(bezel_path, QColor("#050505"))

    if logo is not None and not logo.isNull():
        logo_height = int(max(14, min(46, margin * 0.52)))
        scaled = logo.scaledToHeight(logo_height, Qt.SmoothTransformation)
        logo_x = int(bx + bw - margin * 0.56 - scaled.width())
        screen_bottom = by + bh - margin
        logo_y = int(screen_bottom + (margin - scaled.height()) / 2)
        painter.drawPixmap(logo_x, logo_y, scaled)

    led_colors = (QColor("#1a3d7c"), QColor("#3b82f6"),
                  QColor("#f59e0b"), QColor("#ef4444"))
    painter.setBrush(led_colors[max(0, min(int(led_state), 3))])
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(bx + margin / 2, by + margin / 2), 5.0, 5.0)
