import QtQuick 2.15

Item {
    id: root
    property real value: 0
    property real minValue: 0
    property real maxValue: 100
    property real step: 1
    property string label: ""
    property string unit: ""
    property real valueWarning: 0
    property real valueFault: 0
    property bool showTicks: true
    property int tickCount: 5
    property bool showValue: true
    property real handleRadius: 12
    implicitWidth: 250
    implicitHeight: 64
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.5

    readonly property real _clamped: Math.max(minValue, Math.min(maxValue, value))
    readonly property real _fraction: maxValue > minValue ? (_clamped - minValue) / (maxValue - minValue) : 0
    readonly property color _valueColor: valueFault > 0 && _clamped >= valueFault ? Theme.destructive
        : valueWarning > 0 && _clamped >= valueWarning ? Theme.warning : Theme.brand

    function changeValue(delta) {
        var amount = step > 0 ? step : 1
        value = Math.max(minValue, Math.min(maxValue, _clamped + delta * amount))
    }
    function valueAt(mouseX) {
        var local = track.mapFromItem(mouseArea, mouseX, 0).x
        var raw = minValue + Math.max(0, Math.min(1, local / track.width)) * (maxValue - minValue)
        value = step > 0 ? Math.max(minValue, Math.min(maxValue,
            minValue + Math.round((raw - minValue) / step) * step)) : raw
    }

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Left || event.key === Qt.Key_Down) changeValue(-1)
        else if (event.key === Qt.Key_Right || event.key === Qt.Key_Up) changeValue(1)
        else if (event.key === Qt.Key_Home) value = minValue
        else if (event.key === Qt.Key_End) value = maxValue
        else return
        event.accepted = true
    }

    Column {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 5
        Row {
            width: parent.width
            height: 20
            Text {
                width: parent.width / 2
                text: root.label
                visible: text !== ""
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeXs
                color: Theme.mutedForeground
            }
            Text {
                width: parent.width / 2
                horizontalAlignment: Text.AlignRight
                visible: root.showValue
                text: Number(root._clamped).toFixed(root.step > 0 && root.step < 1 ? 2 : 0)
                    + (root.unit ? " " + root.unit : "")
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                font.weight: Theme.fontSemibold
                color: root._valueColor
            }
        }
        Item {
            width: parent.width
            height: 28
            Rectangle {
                id: track
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: root.handleRadius
                anchors.rightMargin: root.handleRadius
                height: 8
                radius: 4
                color: Theme.secondary
                Rectangle { width: parent.width * root._fraction; height: parent.height; radius: 4; color: root._valueColor }
                Repeater {
                    model: root.showTicks && root.tickCount > 1 ? root.tickCount : 0
                    Rectangle {
                        x: index * (track.width - 1) / Math.max(1, root.tickCount - 1)
                        width: 1; height: track.height; color: Theme.mutedForeground; opacity: 0.45
                    }
                }
                Rectangle {
                    width: root.handleRadius * 2; height: width; radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    x: parent.width * root._fraction - width / 2
                    color: Theme.card; border.color: root._valueColor; border.width: 3
                }
            }
        }
    }
    Rectangle { anchors.fill: parent; color: "transparent"; radius: Theme.radiusSm; border.width: root.activeFocus ? 2 : 0; border.color: Theme.ring }
    MouseArea {
        id: mouseArea
        anchors.fill: parent
        enabled: root.enabled
        onPressed: { root.forceActiveFocus(); root.valueAt(mouse.x) }
        onPositionChanged: if (pressed) root.valueAt(mouse.x)
        onDoubleClicked: root.value = (root.minValue + root.maxValue) / 2
    }
}
