/**
 * ShEngineGauge.qml
 * Round engine instrument: an arc with green, amber and red bands and a
 * needle, as an oil pressure or oil temperature gauge is read.
 *
 * ShGauge already exists, but it colours the whole value arc by threshold.
 * An engine gauge shows the bands themselves all the time -- where the limits
 * are is information even when the needle is nowhere near them.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 0
    property real minimumValue: 0
    property real maximumValue: 100
    /** Band edges: greenLow..greenHigh is normal, up to cautionHigh is
        caution, above it is warning. */
    property real greenLow: 20
    property real greenHigh: 70
    property real cautionHigh: 85
    property string label: ""
    property string units: ""

    implicitWidth: 130
    implicitHeight: 130

    readonly property real _span: Math.max(0.0001, root.maximumValue - root.minimumValue)
    readonly property real _clamped:
        Math.max(root.minimumValue, Math.min(root.maximumValue, root.value))

    // Everything the face painter needs, values and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        value: root.value, minimumValue: root.minimumValue, maximumValue: root.maximumValue,
        greenLow: root.greenLow, greenHigh: root.greenHigh, cautionHigh: root.cautionHigh,
        caution: Theme.efisCaution, normal: Theme.efisNormal, warning: Theme.efisWarning,
        line: Theme.efisLine
    })

    // Face painter: faces/canvas/EngineGaugeFace.qml, or the C++ twin when
    // the loader registered Shadcn.Native (Theme.nativeFaces).
    Loader {
        id: face
        anchors.fill: parent
        source: Theme.face("EngineGauge")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        spacing: 0
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root._clamped.toFixed(0) + (root.units !== "" ? " " + root.units : "")
            color: Theme.efisText
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.weight: Theme.fontSemibold
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label
            color: Theme.mutedForeground
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXs
            visible: root.label !== ""
        }
    }
}
