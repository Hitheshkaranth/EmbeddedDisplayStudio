// faces/compassface.h -- native twin of ui/qml/Shadcn/faces/canvas/CompassFace.qml.
//
// Paints: 72 tick marks and the rotated N/E/S/W and tens labels of the heading card.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment. Owner: W3 (swarm/briefs/faces/W3-*.md).
#pragma once

#include "faceitem.h"

namespace hmi {

class CompassFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

    // TODO(W3): delete this override once paintFace() is complete.
    bool implemented() const override { return false; }

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
