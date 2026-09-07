import QtQuick 2.15

Item {
    id: root
    property var alarms: []
    property int maxVisible: 6
    property string title: "Active Alarms"
    property bool showTimestamp: true
    property real rowHeight: 30
    signal alarmActivated(var alarm)
    implicitWidth: 350
    implicitHeight: rowHeight * maxVisible + 36

    Rectangle {
        id: header
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 36; color: Theme.secondary; radius: Theme.radiusSm
        Text { anchors.left: parent.left; anchors.leftMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 56; text: root.title; elide: Text.ElideRight; color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
        ShBadge { anchors.right: parent.right; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; text: root.alarms.length.toString(); variant: "secondary" }
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: header.bottom; anchors.bottom: parent.bottom
        color: Theme.background; border.color: Theme.border; border.width: 1
        Text {
            anchors.centerIn: parent; visible: root.alarms.length === 0
            text: "No active alarms"; color: Theme.mutedForeground
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm
        }
        ListView {
            anchors.fill: parent; clip: true; visible: root.alarms.length > 0
            model: root.alarms; boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width; height: root.rowHeight
                color: modelData.acknowledged ? "transparent" : Theme.accent
                Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 1; color: Theme.border }
                ShStatDot { id: dot; anchors.left: parent.left; anchors.leftMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; size: 8; state: modelData.severity === "fault" ? "fault" : modelData.severity === "warning" || modelData.severity === "caution" ? "warn" : "ok" }
                Text { anchors.left: dot.right; anchors.leftMargin: Theme.spacing8; anchors.right: stateText.left; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; text: modelData.message || "Alarm"; elide: Text.ElideRight; color: modelData.acknowledged ? Theme.mutedForeground : Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm }
                Text { id: stateText; anchors.right: timestamp.left; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: 28; text: modelData.acknowledged ? "ACK" : "NEW"; color: modelData.acknowledged ? Theme.mutedForeground : Theme.brand; font.family: Theme.fontFamily; font.pixelSize: 10 }
                Text { id: timestamp; anchors.right: parent.right; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; width: root.showTimestamp ? 64 : 0; visible: root.showTimestamp; text: modelData.timestamp || ""; horizontalAlignment: Text.AlignRight; elide: Text.ElideRight; color: Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: 10 }
                MouseArea { anchors.fill: parent; onClicked: root.alarmActivated(modelData) }
            }
        }
    }
}
