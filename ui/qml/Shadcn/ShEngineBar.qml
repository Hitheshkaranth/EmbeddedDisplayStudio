import QtQuick 2.15

Item {
    id: root
    property real value: 0
    property real minimumValue: 0
    property real maximumValue: 100
    property real cautionValue: 80
    property real warningValue: 90
    property string label: "N1"
    property string units: "%"
    implicitWidth: 76
    implicitHeight: 190
    readonly property real _span: Math.max(.0001, maximumValue-minimumValue)
    readonly property real _value: Math.max(minimumValue,Math.min(maximumValue,value))
    readonly property real _fraction: (_value-minimumValue)/_span
    readonly property color _color: _value>=warningValue ? Theme.efisWarning : _value>=cautionValue ? Theme.efisCaution : Theme.efisNormal

    Rectangle { anchors.fill: parent; color: Theme.efisPanel; radius: Theme.radiusSm }
    Text { text: root.label; color: Theme.efisText; anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
    Rectangle {
        id: well; width: 18; anchors.top: parent.top; anchors.topMargin: 25; anchors.bottom: valueText.top; anchors.bottomMargin: 5
        anchors.horizontalCenter: parent.horizontalCenter; color: "transparent"; border.color: Theme.efisLine
        Rectangle { width: parent.width-4; height: (parent.height-4)*root._fraction; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 2; color: root._color }
        Rectangle { width: parent.width+8; height: 2; y: (parent.height-height)*(1-(root.cautionValue-root.minimumValue)/root._span); x: -4; color: Theme.efisCaution }
        Rectangle { width: parent.width+8; height: 2; y: (parent.height-height)*(1-(root.warningValue-root.minimumValue)/root._span); x: -4; color: Theme.efisWarning }
    }
    Text { id:valueText; text: root._value.toFixed(0)+root.units; color: root._color; anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
}
