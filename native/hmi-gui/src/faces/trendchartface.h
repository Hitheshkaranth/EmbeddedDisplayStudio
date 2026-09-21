// faces/trendchartface.h -- native twin of ui/qml/Shadcn/faces/canvas/TrendChartFace.qml.
//
// Paints: gradient fill under the trace, the trace, the current-value dot.
// The Canvas file is the drawing specification; the spec keys are listed in
// its header comment. Owner: W4 (swarm/briefs/faces/W4-*.md).
#pragma once

#include "faceitem.h"

namespace hmi {

class TrendChartFace : public FaceItem
{
    Q_OBJECT

public:
    using FaceItem::FaceItem;

    // TODO(W4): delete this override once paintFace() is complete.
    bool implemented() const override { return false; }

protected:
    void paintFace(QPainter *painter, const QVariantMap &spec) override;
};

} // namespace hmi
