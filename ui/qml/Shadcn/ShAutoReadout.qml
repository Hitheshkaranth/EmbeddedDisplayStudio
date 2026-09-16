/**
 * ShAutoReadout.qml
 * Readout -- Automotive cluster widget. A big number with its unit on the
 * baseline and a line icon beside it ("58 l" with a pump, "90 °C" with a
 * thermometer, "13.5 v" with a battery). Outside warnBelow..warnAbove the
 * number and icon turn red; 0 disables a limit.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 90.0
    property string unit: "\u00B0C"
    property string icon: "temperature"
    property string iconSide: "right"
    property int decimals: 0
    property string label: ""
    property real warnBelow: 0.0
    property real warnAbove: 0.0

    implicitWidth: 150
    implicitHeight: 56

    readonly property real _h: Math.max(1, height)
    readonly property bool _warns: (root.warnBelow !== 0 && root.value < root.warnBelow)
                                || (root.warnAbove !== 0 && root.value > root.warnAbove)
    readonly property bool _iconLeft: root.iconSide === "left"
    readonly property real _iconSlot: root.icon !== "" ? Math.round(root._h * 0.6) + Math.round(root._h * 0.15) : 0

    ShIcon {
        id: glyph
        visible: root.icon !== ""
        name: root.icon
        size: Math.round(root._h * 0.6)
        color: root._warns ? Theme.autoRed : Theme.autoLine
        anchors.verticalCenter: parent.verticalCenter
        x: root._iconLeft ? 0 : root.width - width
    }

    Item {
        id: block
        x: root._iconLeft ? root._iconSlot : 0
        width: Math.max(1, root.width - root._iconSlot)
        anchors.verticalCenter: parent.verticalCenter
        height: caption.visible ? caption.height + reading.height : reading.height

        Text {
            id: caption
            anchors.top: parent.top
            anchors.left: parent.left
            text: root.label
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(root._h * 0.2))
            visible: root.label !== ""
        }

        Item {
            id: reading
            anchors.top: caption.visible ? caption.bottom : parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: number.height

            Text {
                id: number
                anchors.left: parent.left
                // Left-aligned (icon on the left) the number hugs its unit;
                // right-aligned it fills the block so the unit ends flush.
                width: root._iconLeft ? Math.min(implicitWidth, Math.max(10, parent.width - unitText.width - 3))
                                      : Math.max(10, parent.width - unitText.width - 3)
                text: root.value.toFixed(root.decimals)
                color: root._warns ? Theme.autoRed : Theme.autoText
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(8, Math.round(root._h * 0.5))
                font.weight: Theme.fontSemibold
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: 10
                horizontalAlignment: root._iconLeft ? Text.AlignLeft : Text.AlignRight
            }

            Text {
                id: unitText
                anchors.left: number.right
                anchors.leftMargin: 3
                anchors.baseline: number.baseline
                text: root.unit
                color: Theme.autoMuted
                font.family: Theme.fontFamily
                font.pixelSize: Math.max(7, Math.round(root._h * 0.28))
                visible: root.unit !== ""
            }
        }
    }
}
