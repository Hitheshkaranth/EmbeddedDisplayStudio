/**
 * ShTripInfo.qml
 * Trip Info -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property string title: "Distance"
    property string row1Label: "Day"
    property string row1Value: "352"
    property string row1Unit: "km"
    property string row2Label: "Total"
    property string row2Value: "110 593"
    property string row2Unit: "km"

    implicitWidth: 200
    implicitHeight: 110

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Trip Info"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
