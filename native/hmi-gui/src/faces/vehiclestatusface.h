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

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;

private:
    static QPainterPath roundedRect(qreal rx, qreal ry, qreal rw, qreal rh, qreal rr);
};

} // namespace hmi