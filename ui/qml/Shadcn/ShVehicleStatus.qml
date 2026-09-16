/**
 * ShVehicleStatus.qml
 * Vehicle Status -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property real frontLeft: 2.6
    property real frontRight: 2.5
    property real rearLeft: 1.6
    property real rearRight: 2.2
    property string unit: "bar"
    property real warnBelow: 1.8
    property int decimals: 1
    property string label: "TPMS"

    implicitWidth: 150
    implicitHeight: 190

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Vehicle Status"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
