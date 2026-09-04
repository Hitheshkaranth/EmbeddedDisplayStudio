/**
 * ShAnnunciator.qml
 * A caption lamp: lit or unlit, at one of the three alert levels.
 *
 * Unlit is drawn as a dimmed caption rather than as nothing, because a crew
 * needs to know the lamp exists before it lights -- a panel of empty squares
 * says nothing about what could go wrong.
 */
import QtQuick 2.15

Item {
    id: root

    property string text: "CAPTION"
    /** advisory | caution | warning */
    property string severity: "caution"
    property bool lit: true

    implicitWidth: 130
    implicitHeight: 36

    readonly property color _colour: {
        if (root.severity === "warning") return Theme.efisWarning
        if (root.severity === "advisory") return Theme.efisNormal
        return Theme.efisCaution
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSm
        color: root.lit ? root._colour : Theme.efisPanel
        border.color: root._colour
        border.width: 1
        opacity: root.lit ? 1.0 : 0.35
        Behavior on opacity { NumberAnimation { duration: Theme.colorTransition } }
    }

    Text {
        anchors.centerIn: parent
        text: root.text
        color: root.lit ? Theme.efisPanel : root._colour
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.weight: Theme.fontSemibold
        opacity: root.lit ? 1.0 : 0.75
    }
}
