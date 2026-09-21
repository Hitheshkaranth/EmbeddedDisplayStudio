// faces/attitudeface.cpp -- native twin of ui/qml/Shadcn/faces/canvas/AttitudeFace.qml.
#include "attitudeface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

void AttitudeFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    // if (s.line === undefined) return;
    if (!spec.contains(QStringLiteral("line")))
        return;

    const qreal w = width(), h = height();
    const qreal cx = w / 2, cy = h / 2;
    const qreal r = std::min(w, h) * 0.44;

    // Bank marks: eleven lines with pen(line, 2)
    painter->setBrush(Qt::NoBrush);
    painter->setPen(pen(color(QStringLiteral("line")), 2));

    const int marks[] = {-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60};
    for (int i = 0; i < 11; i++) {
        qreal a = (marks[i] - 90) * M_PI / 180;
        qreal inner = (marks[i] % 30 == 0) ? r - 12 : r - 7;
        painter->drawLine(QPointF(cx + std::cos(a) * r, cy + std::sin(a) * r),
                         QPointF(cx + std::cos(a) * inner, cy + std::sin(a) * inner));
    }

    // Aircraft symbol: two wing bars, pen(aircraft, 3)
    painter->setPen(pen(color(QStringLiteral("aircraft")), 3));
    painter->drawLine(QPointF(cx - 46, cy), QPointF(cx - 16, cy));
    painter->drawLine(QPointF(cx + 16, cy), QPointF(cx + 46, cy));

    // Centre dot: full circle radius 3, Qt::NoPen, brush aircraft
    painter->setPen(Qt::NoPen);
    painter->setBrush(color(QStringLiteral("aircraft")));
    painter->drawEllipse(QPointF(cx, cy), 3, 3);
}

} // namespace hmi