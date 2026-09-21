// faces/turncoordinatorface.h -- native twin of ui/qml/Shadcn/faces/canvas/TurnCoordinatorFace.qml.
//
// Paints: upper half-circle scale with five index marks. This is the worked
// example for the other faces: read the Canvas file side by side with the
// .cpp -- every ctx call has a one-line equivalent here.
#pragma once

#include "faceitem.h"

namespace hmi {

class TurnCoordinatorFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
