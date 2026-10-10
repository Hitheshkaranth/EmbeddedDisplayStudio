/**
 * ShEngineBar.qml
 * Engine Bar -- a bar gauge with caution and warning colouring.
 *
 * orientation "vertical" (default): the EFIS column -- label on top, a
 * well with caution/warning markers, the value and units below.
 * orientation "horizontal": a vitals row -- the label at the left, a thin
 * rounded bar filling from the left, the value with its units at the right
 * (no panel, no markers: it sits in a card).
 * barColor: the fill colour; unset (transparent, the Designer's "") keeps
 * the normal/caution/warning colouring by value.
 * glow: the kit's soft glow (ShGlow) around the fill in its colour.
 */
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
    property string orientation: "vertical"   // "vertical" | "horizontal"
    property color barColor: "transparent"
    property bool glow: false
    implicitWidth: 76
    implicitHeight: 190
    readonly property real _span: Math.max(.0001, maximumValue-minimumValue)
    readonly property real _value: Math.max(minimumValue,Math.min(maximumValue,value))
    readonly property real _fraction: (_value-minimumValue)/_span
    readonly property color _color: barColor.a > 0 ? barColor : _value>=warningValue ? Theme.efisWarning : _value>=cautionValue ? Theme.efisCaution : Theme.efisNormal
    readonly property bool _horizontal: orientation === "horizontal"

    Item {
        anchors.fill: parent
        visible: !root._horizontal
        Rectangle { anchors.fill: parent; color: Theme.efisPanel; radius: Theme.radiusSm }
        // The bar's width at most: a long name shrinks, then elides (as hmi-ui).
        Text { text: root.label; color: Theme.efisText; anchors.top: parent.top; anchors.horizontalCenter: parent.horizontalCenter; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight; fontSizeMode: Text.HorizontalFit; minimumPixelSize: 8; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
        Rectangle {
            id: well; width: 18; anchors.top: parent.top; anchors.topMargin: 25; anchors.bottom: valueText.top; anchors.bottomMargin: 5
            anchors.horizontalCenter: parent.horizontalCenter; color: "transparent"; border.color: Theme.efisLine
            ShGlow { anchors.fill: vFill; color: root._color; visible: root.glow && vFill.height > 0 }
            Rectangle { id: vFill; width: parent.width-4; height: (parent.height-4)*root._fraction; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 2; color: root._color }
            Rectangle { width: parent.width+8; height: 2; y: (parent.height-height)*(1-(root.cautionValue-root.minimumValue)/root._span); x: -4; color: Theme.efisCaution; visible: parent.height >= 20 }
            Rectangle { width: parent.width+8; height: 2; y: (parent.height-height)*(1-(root.warningValue-root.minimumValue)/root._span); x: -4; color: Theme.efisWarning; visible: parent.height >= 20 }
        }
        Text { id:valueText; text: root._value.toFixed(0)+root.units; color: root._color; anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; font.pixelSize: Theme.fontSizeSm; font.weight: Theme.fontSemibold }
    }

    // -- horizontal: label | bar | value -------------------------------------
    // Text is min(fontSizeSm, 0.5 h) px; the label takes at most 0.3 w, the
    // value 0.25 w (right-aligned); the bar, min(10, max(4, 0.22 h)) px
    // tall, fills what is left with an 8 px gap each side, on an efisLine
    // track at 18 %.
    Item {
        id: hrow
        anchors.fill: parent
        visible: root._horizontal
        readonly property int fs: Math.max(7, Math.min(Theme.fontSizeSm, Math.round(root.height * 0.5)))
        readonly property real barH: Math.round(Math.min(10, Math.max(4, root.height * 0.22)))
        Text {
            id: hLabel
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: root.label !== "" ? Math.min(implicitWidth, root.width * 0.3) : 0
            visible: root.label !== ""
            text: root.label
            elide: Text.ElideRight
            color: Theme.efisText
            font.family: Theme.fontFamily
            font.pixelSize: hrow.fs
            font.weight: Theme.fontMedium
        }
        Text {
            id: hValue
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, root.width * 0.25)
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            text: root._value.toFixed(0) + root.units
            color: Theme.efisText
            font.family: Theme.fontFamily
            font.pixelSize: hrow.fs
            font.weight: Theme.fontSemibold
        }
        Rectangle {
            id: hTrack
            x: hLabel.visible ? hLabel.width + 8 : 0
            width: Math.max(1, hValue.x - 8 - x)
            height: hrow.barH
            anchors.verticalCenter: parent.verticalCenter
            radius: height / 2
            color: Qt.rgba(Theme.efisLine.r, Theme.efisLine.g, Theme.efisLine.b, 0.18)
            ShGlow {
                anchors.fill: hFill
                color: root._color
                radius: hFill.radius
                visible: root.glow && hFill.visible
            }
            Rectangle {
                id: hFill
                width: Math.round(parent.width * root._fraction)
                height: parent.height
                radius: parent.radius
                color: root._color
                visible: width > 0
            }
        }
    }
}
