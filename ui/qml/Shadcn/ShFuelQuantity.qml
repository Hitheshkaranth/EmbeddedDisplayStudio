import QtQuick 2.15

Item {
    id: root
    property real leftValue: 50
    property real rightValue: 50
    property real capacity: 100
    property real lowLevel: 15
    property string units: "KG"
    implicitWidth: 190
    implicitHeight: 130
    readonly property real _left: Math.max(0,Math.min(capacity,leftValue))
    readonly property real _right: Math.max(0,Math.min(capacity,rightValue))

    Rectangle { anchors.fill: parent; color: Theme.efisPanel; radius: Theme.radiusSm }
    Text { text:"FUEL QTY"; color:Theme.efisText; anchors.top:parent.top; anchors.horizontalCenter:parent.horizontalCenter; font.pixelSize:Theme.fontSizeSm; font.weight:Theme.fontSemibold }
    Row {
        anchors.centerIn: parent; spacing: 24
        Repeater {
            model: [{name:"L",value:root._left},{name:"R",value:root._right}]
            delegate: Column {
                spacing: 3
                Text { text:modelData.name; color:Theme.mutedForeground; anchors.horizontalCenter:parent.horizontalCenter; font.pixelSize:Theme.fontSizeXs }
                Rectangle {
                    width:44; height:58; color:"transparent"; border.color:Theme.efisLine
                    Rectangle { width:parent.width-4; height:(parent.height-4)*modelData.value/root.capacity; anchors.bottom:parent.bottom; anchors.bottomMargin:2; anchors.horizontalCenter:parent.horizontalCenter; color:modelData.value<=root.lowLevel?Theme.efisCaution:Theme.efisNormal }
                }
                Text { text:modelData.value.toFixed(0)+" "+root.units; color:modelData.value<=root.lowLevel?Theme.efisCaution:Theme.efisText; anchors.horizontalCenter:parent.horizontalCenter; font.pixelSize:Theme.fontSizeXs }
            }
        }
    }
}
