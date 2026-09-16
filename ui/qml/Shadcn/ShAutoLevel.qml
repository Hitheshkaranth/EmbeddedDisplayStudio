/**
 * ShAutoLevel.qml
 * Level Bar -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 55.0
    property real minimumValue: 0.0
    property real maximumValue: 100.0
    property string topLabel: "F"
    property string midLabel: "1/2"
    property string bottomLabel: "E"
    property string redZone: "low"
    property real redZoneSpan: 12.0
    property string icon: "gas-station"
    property bool curved: true
    property bool showTicks: true

    implicitWidth: 90
    implicitHeight: 220

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Level Bar"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
