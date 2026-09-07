import QtQuick 2.15

Item {
    id: root
    property real value: 0
    property real minValue: 0
    property real maxValue: 1000
    property real step: 1
    property string unit: ""
    property string label: ""
    property int decimalPlaces: 0
    implicitWidth: 240
    implicitHeight: label ? 64 : 44
    opacity: enabled ? 1 : 0.5

    readonly property real _clamped: Math.max(minValue, Math.min(maxValue, value))
    function adjust(direction) { value = Math.max(minValue, Math.min(maxValue, _clamped + direction * (step > 0 ? step : 1))) }
    function commit() {
        var parsed = Number(valueInput.text)
        if (!isNaN(parsed)) value = Math.max(minValue, Math.min(maxValue, parsed))
        valueInput.text = Number(_clamped).toFixed(decimalPlaces)
    }

    Column {
        anchors.fill: parent; spacing: 4
        Text { width: parent.width; height: visible ? 16 : 0; visible: root.label !== ""; text: root.label; elide: Text.ElideRight; color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs }
        Row {
            width: parent.width; height: 40; spacing: 4
            ShButton { width: 40; height: 40; text: "\u2212"; variant: "outline"; enabled: root.enabled; onClicked: root.adjust(-1) }
            Rectangle {
                width: parent.width - 88; height: 40; radius: Theme.radiusMd; color: Theme.background
                border.color: valueInput.activeFocus ? Theme.ring : Theme.input; border.width: valueInput.activeFocus ? 2 : 1
                TextInput {
                    id: valueInput
                    anchors.fill: parent; anchors.leftMargin: Theme.spacing8; anchors.rightMargin: unitLabel.visible ? unitLabel.width + Theme.spacing12 : Theme.spacing8
                    text: Number(root._clamped).toFixed(root.decimalPlaces)
                    color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold
                    horizontalAlignment: TextInput.AlignHCenter; verticalAlignment: TextInput.AlignVCenter
                    selectByMouse: true; activeFocusOnTab: true; enabled: root.enabled
                    validator: DoubleValidator { bottom: root.minValue; top: root.maxValue; decimals: root.decimalPlaces }
                    onAccepted: root.commit()
                    onActiveFocusChanged: if (!activeFocus) root.commit()
                    Keys.onUpPressed: root.adjust(1)
                    Keys.onDownPressed: root.adjust(-1)
                }
                Text { id: unitLabel; anchors.right: parent.right; anchors.rightMargin: Theme.spacing8; anchors.verticalCenter: parent.verticalCenter; visible: root.unit !== ""; text: root.unit; color: Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs }
            }
            ShButton { width: 40; height: 40; text: "+"; variant: "outline"; enabled: root.enabled; onClicked: root.adjust(1) }
        }
    }
}
