/**
 * ShIconTile.qml
 * Icon Tile -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property string icon: "phone"
    property string label: "BT"
    // enabled: Item's own property; the registry exposes it, QML inherits it.
    property bool active: false

    signal clicked()

    implicitWidth: 100
    implicitHeight: 110

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Icon Tile"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
