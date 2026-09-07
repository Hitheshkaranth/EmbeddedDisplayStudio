import QtQuick 2.15

Item {
    id: root
    property real value: 0
    property string unit: ""
    property string label: ""
    property int decimalPlaces: 2
    property real warningLow: 0
    property real warningHigh: 100
    property real faultLow: 0
    property real faultHigh: 1000
    property color normalColor: Theme.success
    property color warningColor: Theme.warning
    property color faultColor: Theme.destructive
    implicitWidth: 180
    implicitHeight: 80
    readonly property color _valueColor: isNaN(value) ? Theme.mutedForeground
        : value < faultLow || value >= faultHigh ? faultColor
        : value < warningLow || value >= warningHigh ? warningColor : normalColor
    readonly property string _displayValue: isNaN(value) ? "--" : Number(value).toFixed(decimalPlaces)
    Column {
        anchors.fill: parent; spacing: 2
        Text { width: parent.width; height: 16; text: root.label; elide: Text.ElideRight; horizontalAlignment: Text.AlignHCenter; color: Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter; height: 42; spacing: 4
            Text { text: root._displayValue; anchors.verticalCenter: parent.verticalCenter; color: root._valueColor; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXxxl; font.weight: Theme.fontSemibold }
            Text { text: root.unit; anchors.verticalCenter: parent.verticalCenter; color: Theme.mutedForeground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm }
        }
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 24; height: 3; radius: 2; color: root._valueColor }
    }
}
