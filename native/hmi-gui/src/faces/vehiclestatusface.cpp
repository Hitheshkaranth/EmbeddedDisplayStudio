// faces/vehiclestatusface.cpp -- see vehiclestatusface.h.
#include "vehiclestatusface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

QPainterPath VehicleStatusFace::roundedRect(qreal rx, qreal ry, qreal rw, qreal rh, qreal rr)
{
    QPainterPath p;
    p.moveTo(rx + rr, ry);
    p.lineTo(rx + rw - rr, ry);
    arcTo(p, rx + rw, ry, rx + rw, ry + rr, rr);
    p.lineTo(rx + rw, ry + rh - rr);
    arcTo(p, rx + rw, ry + rh, rx + rw - rr, ry + rh, rr);
    p.lineTo(rx + rr, ry + rh);
    arcTo(p, rx, ry + rh, rx, ry + rh - rr, rr);
    p.lineTo(rx, ry + rr);
    arcTo(p, rx, ry, rx + rr, ry, rr);
    p.closeSubpath();
    return p;
}

void VehicleStatusFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    if (!spec.contains(QStringLiteral("bodyW")))
        return;

    const qreal bodyX = num("bodyX");
    const qreal bodyY = num("bodyY");
    const qreal bodyW = num("bodyW");
    const qreal bodyH = num("bodyH");
    const qreal bodyR = num("bodyRadius");
    const qreal wheelW = num("wheelW");
    const qreal wheelH = num("wheelH");
    const QColor wheelClr = color("wheel");
    const QColor wheelLowClr = color("wheelLow");
    const QColor bodyFill = color("bodyFill");
    const QColor bodyLine = color("bodyLine");
    const QColor glass = color("glass");

    const bool flLow = flag("frontLeftLow");
    const bool frLow = flag("frontRightLow");
    const bool rlLow = flag("rearLeftLow");
    const bool rrLow = flag("rearRightLow");

    // Wheels
    const struct { qreal x; qreal y; bool low; } wheels[4] = {
        { bodyX - wheelW * 0.6,      bodyY + bodyH * 0.12, flLow },
        { bodyX + bodyW - wheelW * 0.4, bodyY + bodyH * 0.12, frLow },
        { bodyX - wheelW * 0.6,      bodyY + bodyH * 0.88 - wheelH, rlLow },
        { bodyX + bodyW - wheelW * 0.4, bodyY + bodyH * 0.88 - wheelH, rrLow },
    };

    for (int i = 0; i < 4; ++i) {
        painter->setBrush(wheels[i].low ? wheelLowClr : wheelClr);
        painter->setPen(Qt::NoPen);
        painter->drawPath(roundedRect(wheels[i].x, wheels[i].y, wheelW, wheelH, wheelW * 0.3));
    }

    // Body
    painter->setPen(pen(bodyLine, 1.5));
    painter->setBrush(bodyFill);
    painter->drawPath(roundedRect(bodyX, bodyY, bodyW, bodyH, bodyR));

    // Windows
    painter->setPen(pen(glass, 1.2));
    painter->setBrush(Qt::NoBrush);
    const qreal inset = bodyW * 0.12;
    painter->drawLine(QPointF(bodyX + inset, bodyY + bodyH * 0.28),
                      QPointF(bodyX + bodyW - inset, bodyY + bodyH * 0.28));
    painter->drawLine(QPointF(bodyX + inset, bodyY + bodyH * 0.72),
                      QPointF(bodyX + bodyW - inset, bodyY + bodyH * 0.72));
}

} // namespace hmi