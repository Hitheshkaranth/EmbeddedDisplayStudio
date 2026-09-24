// faces/faceitem.h -- base class of the native widget face painters.
//
// Phase 2 of the native port: the Canvas painters of the Shadcn kit
// (ui/qml/Shadcn/faces/canvas/*Face.qml) get a C++ twin each, registered
// in the QML module Shadcn.Native. Theme.face(name) in the kit picks the
// native twin when the module is present, the Canvas one otherwise, so the
// Python loader and the Designer keep working unchanged.
//
// Contract:
//   * A face is a pure function of ONE property, `spec` (QVariantMap). The
//     wrapper widget builds it from its own properties and Theme colours;
//     the face never reads Theme, the environment or any literal colour.
//   * The face must paint the same pixels as its Canvas twin for the same
//     spec and size. tests/tst_faces.cpp renders both and compares them.
//   * Missing spec keys fall back to the accessor defaults; a face never
//     asserts or throws on a bad spec, it paints what it can.
#pragma once

#include <QColor>
#include <QPainterPath>
#include <QPen>
#include <QQuickPaintedItem>
#include <QVariantList>
#include <QVariantMap>

namespace hmi {

class FaceItem : public QQuickPaintedItem
{
    Q_OBJECT
    Q_PROPERTY(QVariantMap spec READ spec WRITE setSpec NOTIFY specChanged)

public:
    explicit FaceItem(QQuickItem *parent = nullptr);

    QVariantMap spec() const { return m_spec; }
    void setSpec(const QVariantMap &spec);

    // Final: sets the render hints the Canvas painter has (antialiasing) and
    // delegates to paintFace(). Do not override in subclasses.
    void paint(QPainter *painter) override;

    // Stubs return false and tst_faces skips them; a finished face returns
    // true (the base default). Delete the override when the port is done.
    virtual bool implemented() const { return true; }

signals:
    void specChanged();

protected:
    // Paint from `spec` into the item rectangle (0,0,width(),height()).
    virtual void paintFace(QPainter *painter, const QVariantMap &spec) = 0;

    // -- spec accessors: missing or wrongly typed keys yield `def` ----------
    double num(const QString &key, double def = 0.0) const;
    bool flag(const QString &key, bool def = false) const;
    QString str(const QString &key, const QString &def = QString()) const;
    QColor color(const QString &key, const QColor &def = QColor(Qt::transparent)) const;
    QVariantList list(const QString &key) const;

    // -- Canvas-2D equivalents ------------------------------------------------
    // A pen with the Canvas defaults: butt caps and miter joins. QPainter's
    // own default (square caps) makes every line ~lineWidth longer.
    static QPen pen(const QBrush &brush, qreal width,
                    Qt::PenJoinStyle join = Qt::MiterJoin,
                    Qt::PenCapStyle cap = Qt::FlatCap);

    // ctx.arc(cx, cy, r, startRad, endRad, anticlockwise): angles in radians,
    // clockwise positive in a y-down frame, exactly as the Canvas API. Like
    // the Canvas call it joins the current point to the arc start with a
    // straight line when the path already has one, and just moves there
    // when the path is empty.
    static void arc(QPainterPath &path, qreal cx, qreal cy, qreal r,
                    qreal startRad, qreal endRad, bool anticlockwise = false);

    // ctx.arcTo(x1, y1, x2, y2, r) -- the rounded-corner form.
    static void arcTo(QPainterPath &path, qreal x1, qreal y1, qreal x2, qreal y2, qreal r);

    // ctx.quadraticCurveTo(cpx, cpy, x, y)
    static void quadTo(QPainterPath &path, qreal cpx, qreal cpy, qreal x, qreal y);

    // A colour with its alpha replaced (Qt.rgba(c.r, c.g, c.b, a) in QML).
    static QColor withAlpha(const QColor &c, qreal alpha);

private:
    QVariantMap m_spec;
};

} // namespace hmi
