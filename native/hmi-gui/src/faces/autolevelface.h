// faces/autolevelface.h -- native twin of ui/qml/Shadcn/faces/canvas/AutoLevelFace.qml.
//
// Paints: curved bar clipped to its outline: track, red zone, gradient fill, glow, ticks.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment. Owner: W2 (swarm/briefs/faces/W2-*.md).
#pragma once

#include "faceitem.h"

namespace hmi {

class AutoLevelFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;

private:
    static QPainterPath outline(qreal x, qreal w, qreal top, qreal h, qreal bulge);
};

} // namespace hmi