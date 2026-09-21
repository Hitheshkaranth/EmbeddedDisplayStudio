// faces/autolevelface.cpp -- see autolevelface.h.
#include "autolevelface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

QPainterPath AutoLevelFace::outline(qreal x, qreal w, qreal top, qreal h, qreal bulge)
{
    QPainterPath p;
    const qreal r = w / 2;
    const qreal midY = top + h / 2;
    const qreal bottom = top + h;

    p.moveTo(x, top + r);
    arc(p, x + r, top + r, r, M_PI, 0);
    quadTo(p, x + w - bulge, midY, x + w, bottom - r);
    arc(p, x + r, bottom - r, r, 0, M_PI);
    quadTo(p, x - bulge, midY, x, top + r);
    p.closeSubpath();
    return p;
}

void AutoLevelFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    if (!spec.contains(QStringLiteral("fraction")))
        return;

    const qreal x = num("barX");
    const qreal w = num("barW");
    const qreal top = num("barTop");
    const qreal h = num("barH");
    const qreal bulge = num("bulge");
    const qreal bottom = top + h;

    const QColor track = color("track");
    const QColor zone = color("zone");
    const QColor redline = color("redline");
    const QColor accentDeep = color("accentDeep");
    const QColor accent = color("accent");
    const QColor glowClr = color("glow");
    const QColor line = color("line");

    const qreal fraction = num("fraction");
    const QString redZone = str("redZone");
    const qreal redZoneSpan = num("redZoneSpan");
    const bool showTicks = flag("showTicks");

    const qreal tickMajor = num("tickMajor");
    const qreal tickMinor = num("tickMinor");

    // Build clip outline
    QPainterPath out = outline(x, w, top, h, bulge);

    painter->save();
    painter->setClipPath(out);

    // Track
    painter->setBrush(track);
    painter->setPen(Qt::NoPen);
    painter->fillRect(QRectF(x - bulge - 1, top - 1, w + bulge + 2, h + 2), track);

    // Red zone
    const qreal zoneH = qMax<qreal>(0, qMin<qreal>(1, redZoneSpan / 100.0)) * h;
    qreal zoneTop = -1, zoneBottom = -1;
    if (redZone == "low") { zoneTop = bottom - zoneH; zoneBottom = bottom; }
    else if (redZone == "high") { zoneTop = top; zoneBottom = top + zoneH; }
    if (zoneTop >= 0) {
        painter->setBrush(zone);
        painter->fillRect(QRectF(x - bulge - 1, zoneTop, w + bulge + 2, zoneBottom - zoneTop), zone);
    }

    // Fill from the bottom to the value
    const qreal fillTop = bottom - h * fraction;
    if (fraction > 0) {
        QLinearGradient grad(QPointF(0, bottom), QPointF(0, fillTop));
        grad.setColorAt(0, accentDeep);
        grad.setColorAt(1, accent);
        painter->setBrush(QBrush(grad));
        painter->setPen(Qt::NoPen);
        painter->fillRect(QRectF(x - bulge - 1, fillTop, w + bulge + 2, bottom - fillTop), QBrush(grad));

        // Fill inside the red zone reads as red, not blue
        if (zoneTop >= 0) {
            const qreal rt = qMax(zoneTop, fillTop);
            const qreal rb = qMin(zoneBottom, bottom);
            if (rb > rt) {
                painter->setBrush(redline);
                painter->fillRect(QRectF(x - bulge - 1, rt, w + bulge + 2, rb - rt), redline);
            }
        }

        // Glow
        painter->setBrush(glowClr);
        painter->fillRect(QRectF(x - bulge - 1, fillTop, w + bulge + 2, 2), glowClr);
    }

    painter->restore();

    // Ticks (outside the clip)
    if (showTicks) {
        painter->setPen(pen(line, 1.5));
        for (int i = 0; i <= 10; ++i) {
            const qreal f = i / 10.0;
            const qreal y = bottom - h * f;
            const qreal t = 1 - qAbs(f - 0.5) * 2;
            const qreal edge = x - bulge * (1 - (1 - t) * (1 - t)) * 0.5;
            const qreal len = (i % 5 == 0) ? tickMajor : tickMinor;
            const qreal pw = (i % 5 == 0) ? 1.5 : 1.0;
            painter->setPen(pen(line, pw));
            painter->drawLine(QPointF(edge - 2, y), QPointF(edge - 2 - len, y));
        }
    }
}

} // namespace hmi