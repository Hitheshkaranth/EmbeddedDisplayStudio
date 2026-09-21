// faces/clustergaugeface.cpp -- see clustergaugeface.h.
#include "clustergaugeface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

void ClusterGaugeFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    if (!spec.contains(QStringLiteral("value")))
        return;

    const qreal w = width(), h = height();
    const qreal cx = w / 2, cy = h / 2;
    const qreal d = std::min(w, h);
    const qreal span = std::max(0.0001, num(QStringLiteral("maximumValue")) - num(QStringLiteral("minimumValue")));
    const qreal clamped = std::max(num(QStringLiteral("minimumValue")),
                                   std::min(num(QStringLiteral("maximumValue")), num(QStringLiteral("value"))));

    // Common setup
    const qreal startAngle = 90 + (360 - num(QStringLiteral("sweep"))) / 2;
    const qreal arcR = 0.38 * d;
    const qreal strokeW = 0.05 * d;
    const qreal redlineFrom = num(QStringLiteral("redlineFrom"));

    // -- 1. Scale track --------------------------------------------------------
    {
        QPainterPath p;
        arc(p, cx, cy, arcR,
            qDegreesToRadians(startAngle),
            qDegreesToRadians(startAngle + num(QStringLiteral("sweep"))));
        painter->setPen(pen(color(QStringLiteral("track")), strokeW));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    }

    // -- 2. Redline band (always visible when redlineFrom < maximumValue) -----
    if (redlineFrom < num(QStringLiteral("maximumValue"))) {
        const qreal redStartFrac = (redlineFrom - num(QStringLiteral("minimumValue"))) / span;
        const qreal redStartAngle = startAngle + num(QStringLiteral("sweep")) * redStartFrac;
        QPainterPath p;
        arc(p, cx, cy, arcR,
            qDegreesToRadians(redStartAngle),
            qDegreesToRadians(startAngle + num(QStringLiteral("sweep"))));
        painter->setPen(pen(color(QStringLiteral("redline")), strokeW));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    }

    // -- 3. Value arc ---------------------------------------------------------
    const qreal frac = (clamped - num(QStringLiteral("minimumValue"))) / span;
    const qreal valueAngle = startAngle + num(QStringLiteral("sweep")) * frac;

    // Gradient pen for the value arc.
    QLinearGradient grad(QPointF(cx - arcR, cy), QPointF(cx + arcR, cy));
    grad.setColorAt(0, color(QStringLiteral("accentDeep")));
    grad.setColorAt(1, color(QStringLiteral("accent")));
    {
        QPainterPath p;
        arc(p, cx, cy, arcR,
            qDegreesToRadians(startAngle),
            qDegreesToRadians(valueAngle));
        painter->setPen(pen(QBrush(grad), strokeW));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    }

    // 2 px glow line on the outer edge.
    {
        QPainterPath p;
        arc(p, cx, cy, arcR + strokeW * 0.35,
            qDegreesToRadians(startAngle),
            qDegreesToRadians(valueAngle));
        painter->setPen(pen(color(QStringLiteral("glow")), 2));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    }

    // Redline portion of value arc (past redlineFrom).
    if (clamped > redlineFrom && redlineFrom < num(QStringLiteral("maximumValue"))) {
        const qreal redStartFrac2 = (redlineFrom - num(QStringLiteral("minimumValue"))) / span;
        const qreal redStartAngle2 = startAngle + num(QStringLiteral("sweep")) * redStartFrac2;
        QPainterPath p;
        arc(p, cx, cy, arcR,
            qDegreesToRadians(redStartAngle2),
            qDegreesToRadians(valueAngle));
        painter->setPen(pen(color(QStringLiteral("redline")), strokeW));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(p);
    }

    // -- 4. Major ticks -------------------------------------------------------
    const qreal tickLen = 0.035 * d;
    const qreal majorStep = num(QStringLiteral("majorStep"));
    {
        for (qreal mv = num(QStringLiteral("minimumValue"));
             mv <= num(QStringLiteral("maximumValue")) + 0.0001;
             mv += majorStep) {
            const qreal mvFrac = (mv - num(QStringLiteral("minimumValue"))) / span;
            const qreal a = qDegreesToRadians(startAngle + num(QStringLiteral("sweep")) * mvFrac);
            const qreal tx1 = cx + (arcR + tickLen) * std::cos(a);
            const qreal ty1 = cy + (arcR + tickLen) * std::sin(a);
            const qreal tx2 = cx + arcR * std::cos(a);
            const qreal ty2 = cy + arcR * std::sin(a);
            const QColor tickCol = mv >= redlineFrom ? color(QStringLiteral("redline"))
                                                      : color(QStringLiteral("line"));
            painter->setPen(pen(tickCol, 2));
            painter->setBrush(Qt::NoBrush);
            painter->drawLine(QPointF(tx1, ty1), QPointF(tx2, ty2));
        }
    }

    // -- 5. Minor ticks -------------------------------------------------------
    const qreal minorLen = tickLen * 0.5;
    const int steps = qRound(span / majorStep);
    {
        for (int st = 0; st < steps; st++) {
            const qreal baseVal = num(QStringLiteral("minimumValue")) + st * majorStep;
            for (int m = 1; m < 5; m++) {
                const qreal mVal = baseVal + m * (majorStep / 5);
                if (mVal > num(QStringLiteral("maximumValue")) + 0.0001)
                    break;
                const qreal mFrac = (mVal - num(QStringLiteral("minimumValue"))) / span;
                const qreal ma = qDegreesToRadians(startAngle + num(QStringLiteral("sweep")) * mFrac);
                const qreal mx1 = cx + (arcR + minorLen) * std::cos(ma);
                const qreal my1 = cy + (arcR + minorLen) * std::sin(ma);
                const qreal mx2 = cx + arcR * std::cos(ma);
                const qreal my2 = cy + arcR * std::sin(ma);
                painter->setPen(pen(color(QStringLiteral("muted")), 1.2));
                painter->setBrush(Qt::NoBrush);
                painter->drawLine(QPointF(mx1, my1), QPointF(mx2, my2));
            }
        }
    }

    // -- 6. Inner dial --------------------------------------------------------
    if (flag(QStringLiteral("showInnerDial"))) {
        const qreal innerR = 0.28 * d;
        QPainterPath circle;
        arc(circle, cx, cy, innerR, 0, 2 * M_PI);

        // Fill with panel colour.
        painter->setPen(Qt::NoPen);
        painter->setBrush(color(QStringLiteral("panel")));
        painter->drawPath(circle);

        // Radial tint gradient.
        QColor dialTint = color(QStringLiteral("dialTint"));
        QRadialGradient radGrad(QPointF(cx, cy), innerR);
        radGrad.setColorAt(0, dialTint);
        radGrad.setColorAt(1, withAlpha(dialTint, 0));
        painter->setPen(Qt::NoPen);
        painter->setBrush(QBrush(radGrad));
        painter->drawPath(circle);

        // Ring stroke.
        painter->setPen(pen(color(QStringLiteral("tileBorder")), 1.5));
        painter->setBrush(Qt::NoBrush);
        painter->drawPath(circle);
    }
}

} // namespace hmi