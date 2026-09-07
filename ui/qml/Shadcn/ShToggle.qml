import QtQuick 2.15

Item {
    id: root
    property bool checked: false
    property string label: ""
    property string onText: "ON"
    property string offText: "OFF"
    signal toggled()
    implicitWidth: 160
    implicitHeight: 40
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.5
    function toggle() { if (enabled) { checked = !checked; toggled() } }
    Keys.onSpacePressed: { toggle(); event.accepted = true }
    Keys.onReturnPressed: { toggle(); event.accepted = true }
    Row {
        anchors.left: parent.left; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: Theme.spacing8; anchors.rightMargin: Theme.spacing8; spacing: Theme.spacing8
        Rectangle {
            id: switchTrack
            width: 40; height: 24; radius: 12
            color: root.checked ? Theme.brand : Theme.secondary
            border.color: Theme.border; border.width: 1
            Rectangle {
                width: 20; height: 20; radius: 10; y: 2
                x: root.checked ? switchTrack.width - width - 2 : 2
                color: root.checked ? Theme.brandForeground : Theme.foreground
                Behavior on x { NumberAnimation { duration: Theme.colorTransition } }
            }
        }
        Column {
            width: parent.width - switchTrack.width - parent.spacing
            anchors.verticalCenter: parent.verticalCenter
            Text { width: parent.width; text: root.label; visible: text !== ""; elide: Text.ElideRight; color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm }
            Text { width: parent.width; text: root.checked ? root.onText : root.offText; elide: Text.ElideRight; color: root.checked ? Theme.success : Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs }
        }
    }
    Rectangle { anchors.fill: parent; color: "transparent"; radius: Theme.radiusSm; border.width: root.activeFocus ? 2 : 0; border.color: Theme.ring }
    MouseArea { anchors.fill: parent; enabled: root.enabled; onClicked: { root.forceActiveFocus(); root.toggle() } }
}
