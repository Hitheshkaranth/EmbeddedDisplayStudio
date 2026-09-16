/**
 * ShTelltale.qml
 * Telltale -- Automotive cluster widget. An icon lamp that is bright when
 * lit, dimmed when unlit, and blinks when the blink property is true.
 */
import QtQuick 2.15

Item {
    id: root

    property string icon: "bulb"
    property string color: "amber"
    property bool lit: true
    property bool blink: false
    property string label: ""

    implicitWidth: 48
    implicitHeight: 48

    readonly property color _lampColor: {
        if (root.color === "amber") return Theme.autoAmber;
        if (root.color === "green") return Theme.autoGreen;
        if (root.color === "red")   return Theme.autoRed;
        if (root.color === "blue")  return Theme.autoBlue;
        return Theme.autoText;
    }

    readonly property bool _hasLabel: root.label !== ""
    readonly property real _iconSize: root._hasLabel
        ? Math.round(root.implicitHeight * 0.5)
        : Math.round(root.implicitHeight * 0.62)

    Timer {
        id: blinkTimer
        interval: 500
        repeat: true
        running: root.lit && root.blink
        onTriggered: iconItem.opacity = (iconItem.opacity >= 1.0) ? 0.15 : 1.0
    }

    function _resetBlinkOpacity() {
        iconItem.opacity = 1.0;
    }

    Component.onCompleted: {
        if (root.lit && root.blink)
            iconItem.opacity = 0.5;
    }

    Connections {
        target: root
        function onBlinkChanged() {
            if (root.blink && root.lit) {
                iconItem.opacity = 0.5;
                blinkTimer.start();
            } else {
                blinkTimer.stop();
                iconItem.opacity = 1.0;
            }
        }
        function onLitChanged() {
            if (!root.lit) {
                blinkTimer.stop();
                iconItem.opacity = 1.0;
            }
        }
    }

    Column {
        anchors.fill: parent
        spacing: 0

        Item {
            id: iconArea
            anchors.horizontalCenter: parent.horizontalCenter
            width: root._iconSize
            height: root._iconSize

            Rectangle {
                id: glowRect
                anchors.centerIn: parent
                width: Math.round(root.implicitHeight * 0.95)
                height: width
                radius: width / 2
                color: Qt.alpha(root._lampColor, 0.18)
                visible: root.lit
            }

            ShIcon {
                id: iconItem
                anchors.centerIn: parent
                name: root.icon
                size: root._iconSize
                color: root.lit ? root._lampColor : Theme.autoMuted
                opacity: root.blink ? (root.lit ? 0.5 : 0.35) : (root.lit ? 1.0 : 0.35)
            }
        }

        Text {
            text: root.label
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(root.implicitHeight * 0.18)
            font.weight: Theme.fontMedium
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: iconArea.bottom
            anchors.topMargin: 2
            visible: root._hasLabel
        }
    }
}