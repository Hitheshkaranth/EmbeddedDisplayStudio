// faces/turncoordinatorface.cpp -- see turncoordinatorface.h.
#include "turncoordinatorface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

void TurnCoordinatorFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    // if (s.line === undefined) return;
    if (!spec.contains(QStringLiteral("line")))
        return;
    const qreal w = width(), h = height();
    // var cx=width/2, cy=height*.43, r=Math.min(width*.38,height*.38);
    const qreal cx = w / 2, cy = h * 0.43, r = std::min(w * 0.38, h * 0.38);

    // c.strokeStyle=s.line; c.lineWidth=2;
    painter->setBrush(Qt::NoBrush);
    painter->setPen(pen(color(QStringLiteral("line")), 2));

    // c.beginPath(); c.arc(cx,cy,r,Math.PI,2*Math.PI); c.stroke();
    QPainterPath scale;
    arc(scale, cx, cy, r, M_PI, 2 * M_PI);
    painter->drawPath(scale);

    // for (var i=-2;i<=2;i++) { var x=cx+i*r/2; moveTo(x,cy-r); lineTo(x,cy-r+8); stroke(); }
    for (int i = -2; i <= 2; ++i) {
        const qreal x = cx + i * r / 2;
        painter->drawLine(QPointF(x, cy - r), QPointF(x, cy - r + 8));
    }
}

} // namespace hmi
