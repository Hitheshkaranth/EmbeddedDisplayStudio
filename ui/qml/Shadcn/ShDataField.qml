/**
 * ShDataField.qml
 * A labelled readout: what an EFIS bezel is mostly made of.
 *
 * The strip fields around a primary flight display -- WIND 12 KTS, GROUND
 * SPEED 130 KTS, LAT 20 18'25"N -- are all the same object: a caption, a
 * value that changes, and a unit that does not. Binding a tag to `value` is
 * the whole point, so it is the bindable property.
 */
import QtQuick 2.15

Item {
    id: root

    property string label: "LABEL"
    property string value: "---"
    property string units: ""
    /** advisory | caution | warning -- colours the value, never the label. */
    property string severity: "advisory"
    /** Label above the value, or beside it. */
    property bool stacked: true

    implicitWidth: 140
    implicitHeight: stacked ? 44 : 24

    readonly property color _valueColor: {
        if (root.severity === "warning") return Theme.efisWarning
        if (root.severity === "caution") return Theme.efisCaution
        return Theme.efisText
    }

    Text {
        id: labelText
        text: root.label
        color: Theme.mutedForeground
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeXs
        font.weight: Theme.fontMedium
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.verticalCenter: root.stacked ? undefined : parent.verticalCenter
        elide: Text.ElideRight
        width: root.stacked ? parent.width : Math.min(implicitWidth, parent.width * 0.5)
    }

    Row {
        spacing: Theme.spacing4
        anchors.left: root.stacked ? parent.left : labelText.right
        anchors.leftMargin: root.stacked ? 0 : Theme.spacing8
        anchors.top: root.stacked ? labelText.bottom : undefined
        anchors.topMargin: root.stacked ? 2 : 0
        anchors.verticalCenter: root.stacked ? undefined : parent.verticalCenter

        Text {
            text: root.value
            color: root._valueColor
            font.family: Theme.fontFamily
            font.pixelSize: root.stacked ? Theme.fontSizeXl : Theme.fontSizeBase
            font.weight: Theme.fontSemibold
        }
        Text {
            text: root.units
            color: Theme.mutedForeground
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXs
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 3
            visible: root.units !== ""
        }
    }
}
