/**
 * ShIconTile.qml
 * Icon Tile -- Automotive cluster widget. A rounded tile with an icon and
 * caption, glowing when active and highlighting on press.
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

    opacity: root.enabled ? 1.0 : 0.5

    Column {
        anchors.fill: parent
        spacing: 0

        Item {
            id: tileArea
            anchors.horizontalCenter: parent.horizontalCenter
            width: root.implicitWidth
            height: Math.round(root.implicitHeight * 0.72)

            Rectangle {
                id: glowRect
                anchors.centerIn: parent
                width: root.implicitWidth + 8
                height: Math.round(root.implicitHeight * 0.72) + 8
                radius: Math.round(root.implicitWidth * 0.18) + 4
                color: Qt.alpha(Theme.autoAccent, 0.20)
                visible: root.active
            }

            Rectangle {
                id: tileBg
                anchors.centerIn: parent
                width: root.implicitWidth
                height: Math.round(root.implicitHeight * 0.72)
                radius: Math.round(root.implicitWidth * 0.18)
                color: root.active ? Qt.lighter(Theme.autoTileBg, 1.4) : Theme.autoTileBg
                border.color: root.active ? Theme.autoAccent : Theme.autoTileBorder
                border.width: root.active ? 2 : 1

                ShIcon {
                    anchors.centerIn: parent
                    name: root.icon
                    size: Math.round(root.implicitWidth * 0.42)
                    color: Theme.autoText
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: root.enabled
                hoverEnabled: false
                onPressed: function() { tileBg.color = Qt.lighter(Theme.autoTileBg, 1.4) }
                onReleased: function(mouse) {
                    mouse.accepted = true;
                    tileBg.color = root.active ? Qt.lighter(Theme.autoTileBg, 1.4) : Theme.autoTileBg;
                    root.clicked();
                }
                onCanceled: function() {
                    tileBg.color = root.active ? Qt.lighter(Theme.autoTileBg, 1.4) : Theme.autoTileBg;
                }
            }
        }

        Text {
            text: root.label
            color: Theme.autoText
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(root.implicitHeight * 0.14)
            font.weight: Theme.fontMedium
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: tileArea.bottom
            anchors.topMargin: 4
            elide: Text.ElideRight
            width: parent.width
        }
    }
}