// faces/trendchartface.cpp -- see trendchartface.h.
#include "trendchartface.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

void TrendChartFace::paintFace(QPainter *painter, const QVariantMap &spec)
{
    // if (s.data === undefined) return;
    if (!spec.contains(QStringLiteral("data")))
        return;

    const QVariantList data = list("data");
    if (data.isEmpty())
        return;

    const int maxPoints = static_cast<int>(num("maxPoints", 0));
    // pts = data.slice(-maxPoints); if maxPoints <= 0, slice(-0) returns whole array
    QVariantList pts;
    if (maxPoints <= 0) {
        pts = data;
    } else {
        const int from = qMax(0, static_cast<int>(data.size()) - maxPoints);
        for (int i = from; i < static_cast<int>(data.size()); ++i)
            pts << data[i];
    }
    if (pts.size() < 2)
        return;

    const qreal w = width(), h = height();
    const qreal minValue = num("minValue", 0);
    const qreal maxValue = num("maxValue", 0);
    const qreal stepX = w / (maxPoints - 1);
    const qreal yScale = 1.0 / (maxValue - minValue > 0 ? maxValue - minValue : 1);
    const QColor lineCol = color("lineColor", QColor(Qt::transparent));
    const QColor fillCol = color("fillColor", QColor(Qt::transparent));
    const QColor bgCol = color("background", QColor(Qt::transparent));
    const qreal lw = num("lineWidth", 1.0);

    // --- Fill area -----------------------------------------------------------
    // ctx.beginPath(); ctx.moveTo(0, h);
    // for each point: ctx.lineTo(x, y);
    // ctx.lineTo(lastX, h); ctx.closePath();
    QPainterPath fillPath;
    fillPath.moveTo(0, h);
    for (int i = 0; i < pts.size(); ++i) {
        const qreal v = pts[i].toDouble();
        const qreal px = i * stepX;
        const qreal py = h - (v - minValue) * yScale * h;
        fillPath.lineTo(px, py);
    }
    fillPath.lineTo((pts.size() - 1) * stepX, h);
    fillPath.closeSubpath();

    // grad = ctx.createLinearGradient(0, 0, 0, h)
    // grad.addColorStop(0, Qt.rgba(fillColor, 0.2))
    // grad.addColorStop(1, Qt.rgba(fillColor, 0.02))
    QLinearGradient fillGrad(0, 0, 0, h);
    fillGrad.setColorAt(0.0, withAlpha(fillCol, 0.2));
    fillGrad.setColorAt(1.0, withAlpha(fillCol, 0.02));

    painter->setRenderHint(QPainter::Antialiasing);
    painter->setPen(Qt::NoPen);
    painter->setBrush(fillGrad);
    painter->drawPath(fillPath);

    // --- Line ----------------------------------------------------------------
    // ctx.beginPath(); for each point: moveTo (first) / lineTo;
    // ctx.strokeStyle = lineColor; ctx.lineWidth = lineWidth;
    // ctx.lineJoin = "round"; ctx.stroke();
    QPainterPath linePath;
    for (int j = 0; j < pts.size(); ++j) {
        const qreal v = pts[j].toDouble();
        const qreal px = j * stepX;
        const qreal py = h - (v - minValue) * yScale * h;
        if (j == 0)
            linePath.moveTo(px, py);
        else
            linePath.lineTo(px, py);
    }
    painter->setBrush(Qt::NoBrush);
    painter->setPen(pen(QBrush(lineCol), lw, Qt::RoundJoin));
    painter->drawPath(linePath);

    // --- Current value dot ---------------------------------------------------
    // outer circle radius 4 filled with fillColor
    const qreal lastX = (pts.size() - 1) * stepX;
    const qreal lastY = h - (pts.back().toDouble() - minValue) * yScale * h;
    painter->setPen(Qt::NoPen);
    painter->setBrush(fillCol);
    painter->drawEllipse(QPointF(lastX, lastY), 4, 4);

    // inner circle radius 3 filled with background
    painter->setBrush(bgCol);
    painter->drawEllipse(QPointF(lastX, lastY), 3, 3);
}

} // namespace hmi
