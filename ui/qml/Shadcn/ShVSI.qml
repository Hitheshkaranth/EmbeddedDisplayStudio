/**
 * ShVSI.qml
 * Vertical speed indicator: a needle against a scale symmetric about zero,
 * in feet per minute.
 *
 * The scale is deliberately linear. A logarithmic VSI reads better in a real
 * cockpit but is misread on a bench, and this is a panel builder preview as
 * much as an instrument.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 0
    /** Full-scale deflection, plus and minus. */
    property real range: 2000
    property string units: "FPM"

    implicitWidth: 70
    implicitHeight: 220

    readonly property real _clamped: Math.max(-root.range, Math.min(root.range, root.value))

    Rectangle {
        anchors.fill: parent
        color: Theme.efisPanel
        border.color: Theme.border
        border.width: 1
        radius: Theme.radiusSm
    }

    // As in ShTape: the units caption owns the bottom strip.
    Item {
        id: scale
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
    }

    Repeater {
        model: 5
        delegate: Item {
            property real tick: root.range - index * (root.range / 2)
            width: parent.width
            height: 1
            y: scale.y + scale.height / 2 - (tick / root.range) * (scale.height / 2 - 12)
            Rectangle {
                width: Math.abs(tick) === root.range || tick === 0 ? 14 : 8
                height: tick === 0 ? 2 : 1
                color: Theme.efisLine
                anchors.left: parent.left
                anchors.leftMargin: 4
            }
            Text {
                text: Math.abs(tick) >= 1000 ? (Math.abs(tick) / 1000).toFixed(0) : ""
                color: Theme.efisText
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeXs
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 20
            }
        }
    }

    // The needle: a bar from the zero line out to the current rate.
    Rectangle {
        width: parent.width - 26
        height: 3
        color: Math.abs(root._clamped) >= root.range ? Theme.efisCaution : Theme.efisNormal
        x: 22
        y: scale.y + scale.height / 2 - (root._clamped / root.range) * (scale.height / 2 - 12) - 1
        Behavior on y { NumberAnimation { duration: Theme.colorTransition } }
    }

    Text {
        text: root.units
        color: Theme.mutedForeground
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeXs
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 2
    }
}
