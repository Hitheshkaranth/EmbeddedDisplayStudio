/**
 * ShDriveMode.qml
 * Drive Mode -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property string label: "Drive mode"
    property string modes: "ECO,COMFORT,SPORT"
    property int currentIndex: 2
    // enabled: Item's own property; the registry exposes it, QML inherits it.

    signal activated(int index)

    implicitWidth: 180
    implicitHeight: 56

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Drive Mode"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
