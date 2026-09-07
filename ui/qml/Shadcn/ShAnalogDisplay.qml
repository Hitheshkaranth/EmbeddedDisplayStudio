import QtQuick 2.15

Item {
    id: root
    property real value: 0
    property real minValue: 0
    property real maxValue: 100
    property string label: ""
    property string unit: ""
    property real normLow: 20
    property real normHigh: 80
    property real warnLow: 10
    property real warnHigh: 90
    property color normalColor: Theme.success
    property color warnColor: Theme.warning
    property color faultColor: Theme.destructive
    property color trackColor: Theme.secondary
    property bool vertical: false
    implicitWidth: vertical ? 72 : 240
    implicitHeight: vertical ? 240 : 64
    readonly property real _clamped: Math.max(minValue, Math.min(maxValue, value))
    readonly property real _fraction: maxValue > minValue ? (_clamped - minValue) / (maxValue - minValue) : 0
    readonly property color _severity: _clamped < warnLow || _clamped > warnHigh ? faultColor
        : _clamped < normLow || _clamped > normHigh ? warnColor : normalColor
    readonly property string _displayValue: isNaN(value) ? "--" : Number(value).toFixed(1) + (unit ? " " + unit : "")

    Text {
        id: caption
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: root.label ? 16 : 0; visible: root.label !== ""
        text: root.label; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
        color: root._severity; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs
    }
    Rectangle {
        id: track
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: caption.bottom; anchors.bottom: readout.top
        anchors.margins: 4
        radius: Theme.radiusSm; color: root.trackColor; clip: true
        Rectangle {
            anchors.left: parent.left; anchors.bottom: parent.bottom
            width: root.vertical ? parent.width : parent.width * root._fraction
            height: root.vertical ? parent.height * root._fraction : parent.height
            color: root._severity; radius: Theme.radiusSm
            Behavior on width { NumberAnimation { duration: 80 } }
            Behavior on height { NumberAnimation { duration: 80 } }
        }
        Repeater {
            model: [root.warnLow, root.normLow, root.normHigh, root.warnHigh]
            Rectangle {
                readonly property real fraction: root.maxValue > root.minValue ? (modelData - root.minValue) / (root.maxValue - root.minValue) : 0
                visible: fraction >= 0 && fraction <= 1
                x: root.vertical ? 0 : track.width * fraction
                y: root.vertical ? track.height * (1 - fraction) : 0
                width: root.vertical ? track.width : 1
                height: root.vertical ? 1 : track.height
                color: Theme.foreground; opacity: 0.45
            }
        }
        Rectangle {
            x: root.vertical ? 0 : Math.max(0, Math.min(track.width - width, track.width * root._fraction - width / 2))
            y: root.vertical ? Math.max(0, Math.min(track.height - height, track.height * (1 - root._fraction) - height / 2)) : 0
            width: root.vertical ? track.width : 3
            height: root.vertical ? 3 : track.height
            color: Theme.foreground
        }
    }
    Text {
        id: readout
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 20; text: root._displayValue; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter
        color: root._severity; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold
    }
}
