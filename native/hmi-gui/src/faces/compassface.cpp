// faces/compassface.cpp -- native twin of ui/qml/Shadcn/faces/canvas/CompassFace.qml.
#include "compassface.h"

#include <QFont>
#include <QFontMetricsF>
#include <QPainter>
#include <QtMath>

namespace hmi {

void CompassFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    // if (s.line === undefined) return;
    if (!spec.contains(QStringLiteral("line")))
        return;

    const qreal w = width(), h = height();
    const qreal cx = w / 2, cy = h / 2;
    const qreal r = std::min(w, h) / 2 - 4;

    const QColor line = color(QStringLiteral("line"));
    const QColor text = color(QStringLiteral("text"));

    // Font set once before the loop (Canvas literal)
    QFont font(QStringLiteral("sans-serif"));
    font.setPixelSize(13);
    QFontMetricsF fm(font);

    for (int deg = 0; deg < 360; deg += 5) {
        qreal a = (deg - 90) * M_PI / 180;
        bool major = deg % 30 == 0;
        qreal inner = r - (major ? 14 : 7);

        // Tick mark
        painter->setBrush(Qt::NoBrush);
        painter->setPen(pen(line, major ? 2 : 1));
        painter->drawLine(QPointF(cx + std::cos(a) * r, cy + std::sin(a) * r),
                         QPointF(cx + std::cos(a) * inner, cy + std::sin(a) * inner));

        if (major) {
            QString t;
            if (deg == 0) t = "N";
            else if (deg == 90) t = "E";
            else if (deg == 180) t = "S";
            else if (deg == 270) t = "W";
            else t = QString::number(deg / 10);

            painter->save();
            painter->translate(cx + std::cos(a) * (r - 28), cy + std::sin(a) * (r - 28));
            painter->rotate(deg);
            painter->setFont(font);
            painter->setPen(text);
            painter->drawText(QPointF(-fm.horizontalAdvance(t) / 2.0, 5), t);
            painter->restore();
        }
    }
}

} // namespace hmi