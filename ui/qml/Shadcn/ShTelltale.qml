/**
 * ShTelltale.qml
 * Telltale -- Automotive cluster widget. One indicator lamp: a line icon in
 * the lamp colour with a soft glow when lit, a dim ghost when not (an unlit
 * lamp on a real cluster is still visible), and a 1 Hz blink on request.
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
    readonly property real _d: Math.max(1, Math.min(width, height))
    readonly property bool _hasLabel: root.label !== ""
    readonly property real _iconSize: Math.round(root._d * (root._hasLabel ? 0.5 : 0.62))
    /** True while the blinking lamp is in its dark half-period. Starts dark
        so a lamp that begins blinking is visibly different at once. */
    property bool _dark: false
    readonly property bool blinking: blinkTimer.running

    Timer {
        id: blinkTimer
        interval: 500
        repeat: true
        triggeredOnStart: true
        running: root.lit && root.blink
        onTriggered: root._dark = !root._dark
        onRunningChanged: if (!running) root._dark = false
    }

    Rectangle {
        id: glow
        anchors.horizontalCenter: lamp.horizontalCenter
        anchors.verticalCenter: lamp.verticalCenter
        width: Math.round(root._d * (root._hasLabel ? 0.75 : 0.95))
        height: width
        radius: width / 2
        color: Qt.alpha(root._lampColor, 0.18)
        visible: root.lit
        opacity: lamp.opacity
    }

    ShIcon {
        id: lamp
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: root._hasLabel ? -Math.round(root._d * 0.12) : 0
        name: root.icon
        size: root._iconSize
        color: root.lit ? root._lampColor : Theme.autoMuted
        opacity: !root.lit ? 0.35 : (root._dark ? 0.15 : 1.0)
    }

    Text {
        anchors.top: lamp.bottom
        anchors.topMargin: 2
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._d * 0.18))
        font.weight: Theme.fontMedium
        visible: root._hasLabel
    }
}
