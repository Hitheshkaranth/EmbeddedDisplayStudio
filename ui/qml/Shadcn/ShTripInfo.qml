/**
 * ShTripInfo.qml
 * Trip Info -- Automotive cluster widget. The "Distance / Day 352 km /
 * Total 110 593 km" box of a cluster: a muted title over two rows, each a
 * label on the left and a value with its unit on the right. Values are
 * strings so thin-space grouping survives; a row with neither label nor
 * value is hidden.
 */
import QtQuick 2.15

Item {
    id: root

    property string title: "Distance"
    property string row1Label: "Day"
    property string row1Value: "352"
    property string row1Unit: "km"
    property string row2Label: ""   // registry supplies the sample; "" hides the row
    property string row2Value: ""   // registry supplies the sample; "" hides the row
    property string row2Unit: ""   // registry supplies the sample; "" hides the row

    implicitWidth: 200
    implicitHeight: 110

    readonly property real _h: Math.max(1, height)
    readonly property real _pad: Math.round(root._h * 0.1)

    Rectangle {
        anchors.fill: parent
        radius: Math.round(root._h * 0.08)
        color: Qt.rgba(0.078, 0.11, 0.157, 0.6)    // Theme.autoTileBg at 60 %
        border.color: Theme.autoTileBorder
        border.width: 1
    }

    Text {
        id: heading
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: root._pad
        text: root.title
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._h * 0.15))
        visible: root.title !== ""
        height: visible ? implicitHeight : 0
    }

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: heading.visible ? heading.bottom : parent.top
        anchors.topMargin: heading.visible ? Math.round(root._h * 0.04) : root._pad
        anchors.leftMargin: root._pad
        anchors.rightMargin: root._pad

        Repeater {
            model: [[root.row1Label, root.row1Value, root.row1Unit],
                    [root.row2Label, root.row2Value, root.row2Unit]]
            delegate: Item {
                width: parent.width
                height: visible ? Math.round(root._h * 0.3) : 0
                visible: modelData[0] !== "" || modelData[1] !== ""

                Rectangle {
                    anchors.top: parent.top
                    width: parent.width
                    height: 1
                    color: Theme.autoTileBorder
                    visible: index > 0
                }
                Text {
                    id: rowLabel
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData[0]
                    color: Theme.autoLine
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(7, Math.round(root._h * 0.16))
                }
                Text {
                    id: rowUnit
                    anchors.right: parent.right
                    anchors.baseline: rowValue.baseline
                    text: modelData[2]
                    color: Theme.autoMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(7, Math.round(root._h * 0.14))
                    visible: text !== ""
                }
                Text {
                    id: rowValue
                    anchors.right: rowUnit.visible ? rowUnit.left : parent.right
                    anchors.rightMargin: rowUnit.visible ? 4 : 0
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(10, parent.width - rowLabel.width - rowUnit.width - 12)
                    horizontalAlignment: Text.AlignRight
                    text: modelData[1]
                    color: Theme.autoText
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(7, Math.round(root._h * 0.2))
                    font.weight: Theme.fontSemibold
                    fontSizeMode: Text.HorizontalFit
                    minimumPixelSize: 8
                }
            }
        }
    }
}
