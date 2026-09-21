// faces/faceitem.cpp -- see faceitem.h.
#include "faceitem.h"

#include <QPainter>
#include <QtMath>

namespace hmi {

FaceItem::FaceItem(QQuickItem *parent)
    : QQuickPaintedItem(parent)
{
    // Same as the Canvas item: transparent background, antialiased.
    setAntialiasing(true);
}

void FaceItem::setSpec(const QVariantMap &spec)
{
    m_spec = spec;
    emit specChanged();
    update();
}

void FaceItem::paint(QPainter *painter)
{
    painter->setRenderHint(QPainter::Antialiasing, true);
    painter->setRenderHint(QPainter::TextAntialiasing, true);
    paintFace(painter, m_spec);
}

// -- spec accessors -----------------------------------------------------------

double FaceItem::num(const QString &key, double def) const
{
    const QVariant v = m_spec.value(key);
    if (!v.isValid() || v.isNull())
        return def;
    bool ok = false;
    const double d = v.toDouble(&ok);
    return ok ? d : def;
}

bool FaceItem::flag(const QString &key, bool def) const
{
    const QVariant v = m_spec.value(key);
    if (!v.isValid() || v.isNull())
        return def;
    return v.toBool();
}

QString FaceItem::str(const QString &key, const QString &def) const
{
    const QVariant v = m_spec.value(key);
    if (!v.isValid() || v.isNull())
        return def;
    return v.toString();
}

QColor FaceItem::color(const QString &key, const QColor &def) const
{
    const QVariant v = m_spec.value(key);
    if (!v.isValid() || v.isNull())
        return def;
    if (v.userType() == QMetaType::QColor)
        return v.value<QColor>();
    if (v.userType() == QMetaType::QString) {
        const QColor c(v.toString());
        return c.isValid() ? c : def;
    }
    if (v.canConvert<QColor>()) {
        const QColor c = v.value<QColor>();
        return c.isValid() ? c : def;
    }
    return def;
}

QVariantList FaceItem::list(const QString &key) const
{
    const QVariant v = m_spec.value(key);
    if (v.userType() == QMetaType::QVariantList)
        return v.toList();
    if (v.canConvert<QVariantList>())
        return v.value<QVariantList>();
    return {};
}

// -- Canvas-2D equivalents ------------------------------------------------------

QPen FaceItem::pen(const QBrush &brush, qreal width, Qt::PenJoinStyle join, Qt::PenCapStyle cap)
{
    QPen p(brush, width);
    p.setCapStyle(cap);
    p.setJoinStyle(join);
    return p;
}

void FaceItem::arc(QPainterPath &path, qreal cx, qreal cy, qreal r,
                   qreal startRad, qreal endRad, bool anticlockwise)
{
    // HTML: the arc is the whole circumference when the angular distance in
    // the requested direction is >= 2*pi; otherwise the modulo of it.
    const qreal twoPi = 2.0 * M_PI;
    qreal sweep;
    if (!anticlockwise) {
        sweep = endRad - startRad;
        if (sweep >= twoPi)
            sweep = twoPi;
        else {
            sweep = std::fmod(sweep, twoPi);
            if (sweep < 0)
                sweep += twoPi;
        }
    } else {
        sweep = startRad - endRad;
        if (sweep >= twoPi)
            sweep = twoPi;
        else {
            sweep = std::fmod(sweep, twoPi);
            if (sweep < 0)
                sweep += twoPi;
        }
        sweep = -sweep;
    }
    // Canvas angles grow clockwise on screen (y down); QPainterPath angles
    // grow counter-clockwise. Negate both.
    const QRectF rect(cx - r, cy - r, 2 * r, 2 * r);
    const qreal qtStart = -qRadiansToDegrees(startRad);
    const qreal qtSweep = -qRadiansToDegrees(sweep);
    if (path.elementCount() == 0)
        path.arcMoveTo(rect, qtStart);
    path.arcTo(rect, qtStart, qtSweep);
}

void FaceItem::arcTo(QPainterPath &path, qreal x1, qreal y1, qreal x2, qreal y2, qreal r)
{
    if (path.elementCount() == 0)
        path.moveTo(x1, y1);
    const QPointF p0 = path.currentPosition();
    const QPointF p1(x1, y1), p2(x2, y2);
    QPointF v0 = p0 - p1, v2 = p2 - p1;
    const qreal l0 = std::hypot(v0.x(), v0.y()), l2 = std::hypot(v2.x(), v2.y());
    if (l0 < 1e-9 || l2 < 1e-9 || r <= 0) {
        path.lineTo(p1);
        return;
    }
    v0 /= l0;
    v2 /= l2;
    const qreal cross = v0.x() * v2.y() - v0.y() * v2.x();
    const qreal dot = v0.x() * v2.x() + v0.y() * v2.y();
    if (std::fabs(cross) < 1e-9) {           // collinear: no corner to round
        path.lineTo(p1);
        return;
    }
    const qreal theta = std::acos(qBound<qreal>(-1.0, dot, 1.0));   // angle at p1
    const qreal d = r / std::tan(theta / 2);                          // p1 -> tangent points
    const QPointF t0 = p1 + v0 * d;
    const QPointF t2 = p1 + v2 * d;
    QPointF bis = v0 + v2;
    const qreal lb = std::hypot(bis.x(), bis.y());
    bis /= lb;
    const QPointF c = p1 + bis * (r / std::sin(theta / 2));
    path.lineTo(t0);
    const qreal a0 = std::atan2(t0.y() - c.y(), t0.x() - c.x());
    const qreal a1 = std::atan2(t2.y() - c.y(), t2.x() - c.x());
    arc(path, c.x(), c.y(), r, a0, a1, cross > 0);
}

void FaceItem::quadTo(QPainterPath &path, qreal cpx, qreal cpy, qreal x, qreal y)
{
    path.quadTo(QPointF(cpx, cpy), QPointF(x, y));
}

QColor FaceItem::withAlpha(const QColor &c, qreal alpha)
{
    QColor out = c;
    out.setAlphaF(alpha);
    return out;
}

} // namespace hmi
