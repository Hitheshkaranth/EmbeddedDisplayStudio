// faces/attitudeface.h -- native twin of ui/qml/Shadcn/faces/canvas/AttitudeFace.qml.
//
// Paints: fixed bank scale and aircraft symbol.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment.
#pragma once

#include "faceitem.h"

namespace hmi {

class AttitudeFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
