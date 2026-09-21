// faces/nativefaces.cpp -- see nativefaces.h.
#include "nativefaces.h"

#include <QQmlEngine>

#include "clustergaugeface.h"
#include "enginegaugeface.h"
#include "autolevelface.h"
#include "vehiclestatusface.h"
#include "compassface.h"
#include "turncoordinatorface.h"
#include "attitudeface.h"
#include "trendchartface.h"

namespace hmi {

static const char kUri[] = "Shadcn.Native";

void registerNativeFaces()
{
    static bool done = false;
    if (done)
        return;
    done = true;
    qmlRegisterType<NativeProbe>(kUri, 1, 0, "NativeProbe");
    qmlRegisterType<ClusterGaugeFace>(kUri, 1, 0, "ClusterGaugeFace");
    qmlRegisterType<EngineGaugeFace>(kUri, 1, 0, "EngineGaugeFace");
    qmlRegisterType<AutoLevelFace>(kUri, 1, 0, "AutoLevelFace");
    qmlRegisterType<VehicleStatusFace>(kUri, 1, 0, "VehicleStatusFace");
    qmlRegisterType<CompassFace>(kUri, 1, 0, "CompassFace");
    qmlRegisterType<TurnCoordinatorFace>(kUri, 1, 0, "TurnCoordinatorFace");
    qmlRegisterType<AttitudeFace>(kUri, 1, 0, "AttitudeFace");
    qmlRegisterType<TrendChartFace>(kUri, 1, 0, "TrendChartFace");
}

QStringList nativeFaceNames()
{
    return {"ClusterGauge", "EngineGauge", "AutoLevel", "VehicleStatus", "Compass", "TurnCoordinator", "Attitude", "TrendChart"};
}

} // namespace hmi
