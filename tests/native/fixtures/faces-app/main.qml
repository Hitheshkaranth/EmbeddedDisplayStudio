import QtQuick 2.15
import Shadcn 1.0

Rectangle {
    id: root
    width: 640
    height: 480
    color: Theme.background

    ShClusterGauge {
        x: 10; y: 10; width: 150; height: 150
    }
    ShEngineGauge {
        x: 170; y: 10; width: 150; height: 150
    }
    ShAutoLevel {
        x: 330; y: 10; width: 80; height: 200
    }
    ShVehicleStatus {
        x: 420; y: 10; width: 210; height: 190
    }
    ShTrendChart {
        x: 10; y: 170; width: 300; height: 150
        data: [1, 2, 3]
    }
    ShCompass {
        x: 320; y: 170; width: 150; height: 150
    }
    ShTurnCoordinator {
        x: 480; y: 170; width: 150; height: 150
    }
    ShAttitude {
        x: 10; y: 330; width: 300; height: 140
    }

    Component.onCompleted: Hmi.log("PROBE faces native=" + Theme.nativeFaces)
}
