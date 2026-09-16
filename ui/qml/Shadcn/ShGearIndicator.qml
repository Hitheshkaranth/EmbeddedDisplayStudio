/**
 * ShGearIndicator.qml
 * Gear Indicator -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property string gears: "P,R,N,D"
    property string gear: "D"
    property int modeNumber: 4
    property bool showAll: true

    implicitWidth: 120
    implicitHeight: 70

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Gear Indicator"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
