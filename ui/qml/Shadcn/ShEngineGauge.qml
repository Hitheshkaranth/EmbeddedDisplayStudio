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

    Canvas {
        id: face
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var cx = width / 2, cy = height / 2;
            var dim = Math.min(width, height);
            var r = dim / 2 - dim * 0.12;
            var stroke = Math.max(4, dim * 0.11);
            // 240 degrees of sweep opening downward, as a round gauge reads.
            var start = 150, sweep = 240;

            function arc(fromValue, toValue, colour) {
                var a0 = (fromValue - root.minimumValue) / root._span;
                var a1 = (toValue - root.minimumValue) / root._span;
                ctx.beginPath();
                ctx.lineWidth = stroke;
                ctx.strokeStyle = colour;
                ctx.arc(cx, cy, r,
                        (start + sweep * a0) * Math.PI / 180,
                        (start + sweep * a1) * Math.PI / 180);
                ctx.stroke();
            }

            arc(root.minimumValue, root.greenLow, Theme.efisCaution);
            arc(root.greenLow, root.greenHigh, Theme.efisNormal);
            arc(root.greenHigh, root.cautionHigh, Theme.efisCaution);
            arc(root.cautionHigh, root.maximumValue, Theme.efisWarning);

            // Needle.
            var f = (root._clamped - root.minimumValue) / root._span;
            var a = (start + sweep * f) * Math.PI / 180;
            ctx.strokeStyle = Theme.efisLine;
            ctx.lineWidth = Math.max(2, dim * 0.025);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + Math.cos(a) * (r - stroke * 0.6),
                       cy + Math.sin(a) * (r - stroke * 0.6));
            ctx.stroke();
            ctx.fillStyle = Theme.efisLine;
            ctx.beginPath();
            ctx.arc(cx, cy, Math.max(2, dim * 0.03), 0, Math.PI * 2);
            ctx.fill();
        }
        Component.onCompleted: requestPaint()
        Connections {
            target: root
            function onValueChanged() { face.requestPaint() }
            function onMinimumValueChanged() { face.requestPaint() }
            function onMaximumValueChanged() { face.requestPaint() }
            function onGreenLowChanged() { face.requestPaint() }
            function onGreenHighChanged() { face.requestPaint() }
            function onCautionHighChanged() { face.requestPaint() }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
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
