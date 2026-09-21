// faces/attitudeface.h -- native twin of ui/qml/Shadcn/faces/canvas/AttitudeFace.qml.
//
// Paints: fixed bank scale and aircraft symbol.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment. Owner: W3 (swarm/briefs/faces/W3-*.md).
#pragma once

#include "faceitem.h"

namespace hmi {

class AttitudeFace : public FaceItem
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
