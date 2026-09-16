/**
 * ShAutoReadout.qml
 * Readout -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 90.0
    property string unit: "°C"
    property string icon: "temperature"
    property string iconSide: "right"
    property int decimals: 0
    property string label: ""
    property real warnBelow: 0.0
    property real warnAbove: 0.0

    implicitWidth: 150
    implicitHeight: 56

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Readout"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
