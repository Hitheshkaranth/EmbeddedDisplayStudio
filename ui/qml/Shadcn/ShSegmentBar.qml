/**
 * ShSegmentBar.qml
 * Segment Bar -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 60.0
    property real minimumValue: 0.0
    property real maximumValue: 100.0
    property int segments: 12
    property string label: "SOC"
    property bool showPercent: true
    property real lowLevel: 20.0

    implicitWidth: 320
    implicitHeight: 36

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Segment Bar"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
