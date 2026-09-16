/**
 * ShClusterGauge.qml
 * Cluster Gauge -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 4.2
    property real minimumValue: 0.0
    property real maximumValue: 8.0
    property real majorStep: 1.0
    property real redlineFrom: 7.0
    property real sweep: 240.0
    property string readout: "137"
    property string readoutUnit: "km/h"
    property string caption: ""
    property string label: "x1000 RPM"
    property int decimals: 0
    property bool showInnerDial: true

    implicitWidth: 240
    implicitHeight: 240

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Cluster Gauge"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
