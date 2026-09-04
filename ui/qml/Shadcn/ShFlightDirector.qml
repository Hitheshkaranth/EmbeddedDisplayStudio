import QtQuick 2.15

Item {
    id: root
    property real pitchCommand: 0
    property real rollCommand: 0
    property real pitchLimit: 15
    property real rollLimit: 30
    property bool active: true
    property string mode: "FD"
    implicitWidth: 180
    implicitHeight: 120
    clip: true

    readonly property real _pitch: Math.max(-pitchLimit, Math.min(pitchLimit, pitchCommand))
    readonly property real _roll: Math.max(-rollLimit, Math.min(rollLimit, rollCommand))

    Rectangle { anchors.fill: parent; color: Theme.efisPanel }
    Rectangle {
        visible: root.active
        width: parent.width * 0.48; height: Math.max(3, parent.height * 0.035)
        color: Theme.efisNav
        anchors.centerIn: parent
        y: parent.height / 2 - height / 2 + root._pitch / root.pitchLimit * parent.height * 0.32
    }
    Rectangle {
        visible: root.active
        width: Math.max(3, parent.width * 0.022); height: parent.height * 0.58
        color: Theme.efisNav
        anchors.centerIn: parent
        x: parent.width / 2 - width / 2 + root._roll / root.rollLimit * parent.width * 0.32
    }
    Text {
        anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter
        text: root.active ? root.mode : "FD OFF"
        color: root.active ? Theme.efisNormal : Theme.mutedForeground
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs
        font.weight: Theme.fontSemibold
    }
}
