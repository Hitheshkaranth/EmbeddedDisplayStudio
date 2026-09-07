import QtQuick 2.15

Item {
    id: root
    property bool checked: false
    property string label: ""
    implicitWidth: 160
    implicitHeight: 32
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.5
    function toggle() { if (enabled) checked = !checked }
    Keys.onSpacePressed: { toggle(); event.accepted = true }
    Keys.onReturnPressed: { toggle(); event.accepted = true }
    Row {
        anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Theme.spacing4; anchors.rightMargin: Theme.spacing4; spacing: Theme.spacing8
        Rectangle {
            id: box
            width: 20; height: 20; radius: Theme.radiusSm
            color: root.checked ? Theme.brand : Theme.card
            border.color: root.checked ? Theme.brand : Theme.input; border.width: 1
            Text { anchors.centerIn: parent; visible: root.checked; text: "\u2713"; color: Theme.brandForeground; font.pixelSize: 14; font.bold: true }
        }
        Text { width: parent.width - box.width - parent.spacing; text: root.label; elide: Text.ElideRight; color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm; anchors.verticalCenter: parent.verticalCenter }
    }
    Rectangle { anchors.fill: parent; color: "transparent"; radius: Theme.radiusSm; border.width: root.activeFocus ? 2 : 0; border.color: Theme.ring }
    MouseArea { anchors.fill: parent; enabled: root.enabled; onClicked: { root.forceActiveFocus(); root.toggle() } }
}
