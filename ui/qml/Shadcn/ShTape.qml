/**
 * ShTape.qml
 * A moving-tape readout: airspeed on the left of a PFD, altitude on the right.
 *
 * One component rather than two. An airspeed tape and an altitude tape differ
 * only in their range, their step and which side the current-value box points
 * from -- duplicating the whole instrument to change three numbers is how the
 * two drift apart.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 0
    property real minimumValue: 0
    property real maximumValue: 200
    /** Value between two labelled major ticks. */
    property real step: 10
    /** How much of the range is visible at once. */
    property real span: 60
    property string label: ""
    property string units: ""
    /** left | right -- which edge the value box points out of. */
    property string side: "left"

    implicitWidth: 78
    implicitHeight: 260
    clip: true

    readonly property real _clamped:
        Math.max(root.minimumValue, Math.min(root.maximumValue, root.value))
    readonly property real _pxPerUnit: root.span > 0 ? height / root.span : 1

    Rectangle { anchors.fill: parent; color: Theme.efisPanel; opacity: 0.85 }

    // The caption owns the bottom strip; the scale stops above it. Drawn over
    // the ticks it landed on whichever label was lowest, which reads as a
    // corrupted number rather than as two overlapping strings.
    readonly property real _captionBand:
        (root.label !== "" || root.units !== "") ? 16 : 0

    Item {
        id: scale
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root._captionBand
        clip: true

        Repeater {
            // Every tick that can fall inside the visible span, plus a margin.
            model: Math.floor(root.span / root.step) + 3
            delegate: Item {
                property real tickValue:
                    (Math.round(root._clamped / root.step) - Math.floor(root.span / root.step / 2) - 1 + index) * root.step
                property bool inRange:
                    tickValue >= root.minimumValue && tickValue <= root.maximumValue
                width: parent.width
                height: 1
                y: parent.height / 2 - (tickValue - root._clamped) * root._pxPerUnit
                visible: inRange

                Rectangle {
                    width: 10; height: 2
                    color: Theme.efisLine
                    anchors.right: root.side === "left" ? parent.right : undefined
                    anchors.left: root.side === "left" ? undefined : parent.left
                }
                Text {
                    text: tickValue
                    color: Theme.efisText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeXs
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.right: root.side === "left" ? parent.right : undefined
                    anchors.rightMargin: root.side === "left" ? 14 : 0
                    anchors.left: root.side === "left" ? undefined : parent.left
                    anchors.leftMargin: root.side === "left" ? 0 : 14
                }
            }
        }
    }

    // Current value, always centred on the scale: the tape moves, this does not.
    Rectangle {
        anchors.verticalCenter: scale.verticalCenter
        anchors.left: parent.left
        anchors.right: parent.right
        height: 26
        color: Theme.efisPanel
        border.color: Theme.efisLine
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: root._clamped.toFixed(0)
            color: Theme.efisText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeLg
            font.weight: Theme.fontSemibold
        }
    }

    Text {
        text: root.label + (root.units !== "" ? " " + root.units : "")
        color: Theme.mutedForeground
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeXs
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 2
        visible: text !== ""
    }
}
