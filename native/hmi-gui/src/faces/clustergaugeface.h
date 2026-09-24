// faces/clustergaugeface.h -- native twin of ui/qml/Shadcn/faces/canvas/ClusterGaugeFace.qml.
//
// Paints: track, redline band, gradient value arc with glow, ticks, inner dial.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment.
#pragma once

#include "faceitem.h"

namespace hmi {

class ClusterGaugeFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
