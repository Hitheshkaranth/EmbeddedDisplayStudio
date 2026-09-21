// faces/vehiclestatusface.h -- native twin of ui/qml/Shadcn/faces/canvas/VehicleStatusFace.qml.
//
// Paints: four wheels, rounded car body, two window lines.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment. Owner: W2 (swarm/briefs/faces/W2-*.md).
#pragma once

#include "faceitem.h"

namespace hmi {

class VehicleStatusFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

    // TODO(W2): delete this override once paintFace() is complete.
    bool implemented() const override { return false; }

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
