// faces/enginegaugeface.cpp -- see enginegaugeface.h.
#include "enginegaugeface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

void EngineGaugeFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    if (!spec.contains(QStringLiteral("value")))
        return;

    const qreal w = width(), h = height();
    const qreal cx = w / 2, cy = h / 2;
    const qreal dim = std::min(w, h);
    const qreal r = dim / 2 - dim * 0.12;
    const qreal stroke = std::max(4.0, dim * 0.11);
    const qreal span = std::max(0.0001, num(QStringLiteral("maximumValue")) - num(QStringLiteral("minimumValue")));
    const qreal clamped = std::max(num(QStringLiteral("minimumValue")),
                                   std::min(num(QStringLiteral("maximumValue")), num(QStringLiteral("value"))));
    const qreal start = 150, sweep = 240;

    // Helper lambda to draw a single arc band.
    auto drawArc = [&](qreal fromValue, qreal toValue, const QColor &colour) {
        const qreal a0 = (fromValue - num(QStringLiteral("minimumValue"))) / span;
        const qreal a1 = (toValue - num(QStringLiteral("minimumValue"))) / span;
        QPainterPath p;
        FaceItem::arc(p, cx, cy, r,
                      qDegreesToRadians(start + sweep * a0),
                      qDegreesToRadians(start + sweep * a1));
        painter->setPen(pen(colour, stroke));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    };

    // Four coloured bands.
    drawArc(num(QStringLiteral("minimumValue")), num(QStringLiteral("greenLow")),
            color(QStringLiteral("caution")));
    drawArc(num(QStringLiteral("greenLow")), num(QStringLiteral("greenHigh")),
            color(QStringLiteral("normal")));
    drawArc(num(QStringLiteral("greenHigh")), num(QStringLiteral("cautionHigh")),
            color(QStringLiteral("caution")));
    drawArc(num(QStringLiteral("cautionHigh")), num(QStringLiteral("maximumValue")),
            color(QStringLiteral("warning")));

    // Needle line.
    const qreal f = (clamped - num(QStringLiteral("minimumValue"))) / span;
    const qreal a = qDegreesToRadians(start + sweep * f);
    const qreal needleLen = r - stroke * 0.6;
    painter->setPen(pen(color(QStringLiteral("line")), std::max(2.0, dim * 0.025)));
    painter->setBrush(Qt::NoBrush);
    painter->drawLine(QPointF(cx, cy),
                     QPointF(cx + std::cos(a) * needleLen,
                             cy + std::sin(a) * needleLen));

    // Hub (filled circle).
    QPainterPath hub;
    FaceItem::arc(hub, cx, cy, std::max(2.0, dim * 0.03), 0, 2 * M_PI);
    painter->setPen(Qt::NoPen);
    painter->setBrush(color(QStringLiteral("line")));
    painter->drawPath(hub);
}

} // namespace hmi