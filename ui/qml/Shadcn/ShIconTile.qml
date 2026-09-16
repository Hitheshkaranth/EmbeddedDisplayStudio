/**
 * ShIconTile.qml
 * Icon Tile -- Automotive cluster widget. A rounded tile with a line icon
 * and a caption under it, as an infotainment menu shows BT / USB / SET.
 * ``active`` gives it the accent border and glow; a press lightens the face
 * and a release inside fires ``clicked()``.
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

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    readonly property real _tileHeight: Math.round(root._h * 0.72)
    readonly property real _radius: Math.round(root._w * 0.18)

    opacity: root.enabled ? 1.0 : 0.5

    Rectangle {
        id: glow
        anchors.fill: tile
        anchors.margins: -4
        radius: root._radius + 4
        color: Qt.alpha(Theme.autoAccent, 0.20)
        visible: root.active
    }

    Rectangle {
        id: tile
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: root._tileHeight
        radius: root._radius
        color: tap.pressed ? Qt.lighter(Theme.autoTileBg, 1.4) : Theme.autoTileBg
        border.color: root.active ? Theme.autoAccent : Theme.autoTileBorder
        border.width: root.active ? 2 : 1

        ShIcon {
            anchors.centerIn: parent
            name: root.icon
            size: Math.round(root._w * 0.42)
            color: Theme.autoText
        }

        MouseArea {
            id: tap
            anchors.fill: parent
            enabled: root.enabled
            // MouseArea.clicked already means "released inside".
            onClicked: root.clicked()
        }
    }

    Text {
        anchors.top: tile.bottom
        anchors.topMargin: Math.round(root._h * 0.04)
        anchors.left: parent.left
        anchors.right: parent.right
        text: root.label
        color: Theme.autoText
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(8, Math.round(root._h * 0.14))
        font.weight: Theme.fontMedium
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        visible: root.label !== ""
    }
}
