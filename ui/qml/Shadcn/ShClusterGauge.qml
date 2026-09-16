/**
 * ShClusterGauge.qml
 * Cluster Gauge -- Automotive arc-based instrument. An arc track with redline
 * band, gradient value arc, tick marks + labels, a big centre readout, a
 * caption and an optional inner dial ring.
 *
 * Drawing (from outside in, all dimensions relative to d = Math.min(width, height)):
 * 1. Scale track   – arc of `sweep` degrees, radius 0.42d, stroke 0.05d
 * 2. Redline band  – same arc from redlineFrom..maximumValue
 * 3. Value arc     – gradient from accentDeep to accent, redline portion red
 * 4. Major ticks+labels  – every majorStep
 * 5. Minor ticks       – 4 between majors
 * 6. Inner dial        – optional filled circle with radial gradient
 * 7. Readout / readoutUnit  – crisp Text elements centred in the item
 * 8. Caption             – Amber text above the readout
 * 9. label               – bottom-right muted text
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 4.2
    property real minimumValue: 0.0
    property real maximumValue: 8.0
    property real majorStep: 1.0
    property real redlineFrom: 7.0
    property real sweep: 240.0
    property string readout: ""       // empty: show value.toFixed(decimals)
    property string readoutUnit: "km/h"
    property string caption: ""
    property string label: "x1000 RPM"
    property int decimals: 0
    property bool showInnerDial: true

    implicitWidth: 240
    implicitHeight: 240

    readonly property real _span: Math.max(0.0001, root.maximumValue - root.minimumValue)
    readonly property real _d: Math.max(1, Math.min(width, height))
    readonly property real _startAngle: 90 + (360 - root.sweep) / 2
    /** The major scale values, min..max every majorStep (at most 60). */
    readonly property var _majors: {
        var out = [];
        var step = Math.max(0.0001, root.majorStep);
        for (var v = root.minimumValue, i = 0; v <= root.maximumValue + 0.0001 && i < 60; v += step, ++i)
            out.push(v);
        return out;
    }
    readonly property real _clamped:
        Math.max(root.minimumValue, Math.min(root.maximumValue, root.value))

    Canvas {
        id: face
        anchors.fill: parent
        anchors.margins: 0

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var cx = width / 2, cy = height / 2;
            var d = Math.min(width, height);

            // -- 1. Scale track --
            var startAngle = 90 + (360 - root.sweep) / 2;
            var arcR = 0.42 * d;
            var strokeW = 0.05 * d;

            // Track (unfilled scale)
            ctx.beginPath();
            ctx.arc(cx, cy, arcR,
                    startAngle * Math.PI / 180,
                    (startAngle + root.sweep) * Math.PI / 180);
            ctx.lineWidth = strokeW;
            ctx.strokeStyle = Theme.autoTrack;
            ctx.stroke();

            // -- 2. Redline band (always visible) --
            if (root.redlineFrom < root.maximumValue) {
                var redStartFrac = (root.redlineFrom - root.minimumValue) / root._span;
                var redEndFrac = 1.0;
                var redStartAngle = startAngle + root.sweep * redStartFrac;
                ctx.beginPath();
                ctx.arc(cx, cy, arcR,
                        redStartAngle * Math.PI / 180,
                        (startAngle + root.sweep) * Math.PI / 180);
                ctx.lineWidth = strokeW;
                ctx.strokeStyle = Theme.autoRedline;
                ctx.stroke();
            }

            // -- 3. Value arc --
            var frac = (_clamped - root.minimumValue) / root._span;
            var valueAngle = startAngle + root.sweep * frac;

            // Gradient for the value arc
            var grad = ctx.createLinearGradient(
                    cx - arcR, cy, cx + arcR, cy);
            grad.addColorStop(0, Theme.autoAccentDeep);
            grad.addColorStop(1, Theme.autoAccent);

            ctx.beginPath();
            ctx.arc(cx, cy, arcR,
                    startAngle * Math.PI / 180,
                    valueAngle * Math.PI / 180);
            ctx.lineWidth = strokeW;
            ctx.strokeStyle = grad;
            ctx.stroke();

            // 2 px glow line on the outer edge of the value arc
            ctx.beginPath();
            ctx.arc(cx, cy, arcR + strokeW * 0.35,
                    startAngle * Math.PI / 180,
                    valueAngle * Math.PI / 180);
            ctx.lineWidth = 2;
            ctx.strokeStyle = Theme.autoGlow;
            ctx.stroke();

            // Redline portion of value arc (past redlineFrom)
            if (_clamped > root.redlineFrom && root.redlineFrom < root.maximumValue) {
                var redStartFrac2 = (root.redlineFrom - root.minimumValue) / root._span;
                var redStartAngle2 = startAngle + root.sweep * redStartFrac2;
                ctx.beginPath();
                ctx.arc(cx, cy, arcR,
                        redStartAngle2 * Math.PI / 180,
                        valueAngle * Math.PI / 180);
                ctx.lineWidth = strokeW;
                ctx.strokeStyle = Theme.autoRedline;
                ctx.stroke();
            }

            // -- 4. Major ticks and labels --
            var tickLen = 0.035 * d;
            var labelR = 0.52 * d;
            for (var mv = root.minimumValue; mv <= root.maximumValue + 0.0001; mv += root.majorStep) {
                var mvFrac = (mv - root.minimumValue) / root._span;
                var a = (startAngle + root.sweep * mvFrac) * Math.PI / 180;
                var tx1 = cx + (arcR + tickLen) * Math.cos(a);
                var ty1 = cy + (arcR + tickLen) * Math.sin(a);
                var tx2 = cx + arcR * Math.cos(a);
                var ty2 = cy + arcR * Math.sin(a);
                ctx.beginPath();
                ctx.moveTo(tx1, ty1);
                ctx.lineTo(tx2, ty2);
                ctx.lineWidth = 2;
                var isRedline = mv >= root.redlineFrom;
                ctx.strokeStyle = isRedline ? Theme.autoRedline : Theme.autoLine;
                ctx.stroke();

            }

            // -- 5. Minor ticks --
            var minorLen = tickLen * 0.5;
            var steps = Math.round(root._span / root.majorStep);
            for (var s = 0; s < steps; s++) {
                var baseVal = root.minimumValue + s * root.majorStep;
                for (var m = 1; m < 5; m++) {
                    var mVal = baseVal + m * (root.majorStep / 5);
                    if (mVal > root.maximumValue + 0.0001) break;
                    var mFrac = (mVal - root.minimumValue) / root._span;
                    var ma = (startAngle + root.sweep * mFrac) * Math.PI / 180;
                    var mx1 = cx + (arcR + minorLen) * Math.cos(ma);
                    var my1 = cy + (arcR + minorLen) * Math.sin(ma);
                    var mx2 = cx + arcR * Math.cos(ma);
                    var my2 = cy + arcR * Math.sin(ma);
                    ctx.beginPath();
                    ctx.moveTo(mx1, my1);
                    ctx.lineTo(mx2, my2);
                    ctx.lineWidth = 1.2;
                    ctx.strokeStyle = Theme.autoMuted;
                    ctx.stroke();
                }
            }

            // -- 6. Inner dial --
            if (root.showInnerDial) {
                var innerR = 0.3 * d;
                ctx.beginPath();
                ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
                ctx.fillStyle = Theme.autoPanel;
                ctx.fill();

                // Radial gradient overlay
                var radGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, innerR);
                radGrad.addColorStop(0, "rgba(10,79,138,0.20)");
                radGrad.addColorStop(1, "rgba(10,79,138,0.00)");
                ctx.beginPath();
                ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
                ctx.fillStyle = radGrad;
                ctx.fill();

                // Ring
                ctx.beginPath();
                ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
                ctx.lineWidth = 1.5;
                ctx.strokeStyle = Theme.autoTileBorder;
                ctx.stroke();
            }
        }

        Component.onCompleted: requestPaint()

        Connections {
            target: root
            function onValueChanged()    { face.requestPaint() }
            function onMinimumValueChanged() { face.requestPaint() }
            function onMaximumValueChanged() { face.requestPaint() }
            function onMajorStepChanged() { face.requestPaint() }
            function onRedlineFromChanged() { face.requestPaint() }
            function onSweepChanged()     { face.requestPaint() }
            function onShowInnerDialChanged() { face.requestPaint() }
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    // -- 4b. Scale labels, as Text so they stay crisp at any size --
    Repeater {
        model: root._majors
        delegate: Text {
            readonly property real angle: (root._startAngle + root.sweep * ((modelData - root.minimumValue) / root._span)) * Math.PI / 180
            x: width / 2 + root.width / 2 + 0.52 * root._d * Math.cos(angle) - width
            y: root.height / 2 + 0.52 * root._d * Math.sin(angle) - height / 2
            text: Number(modelData).toFixed(0)
            color: modelData >= root.redlineFrom ? Theme.autoRedline : Theme.autoLine
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(0.075 * root._d))
            font.weight: Theme.fontMedium
        }
    }

    // -- 7 & 8. Readout + caption (crisp Text elements) --

    Text {
        id: captionText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: readoutText.top
        anchors.bottomMargin: 4
        text: root.caption
        color: Theme.autoAmber
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.07 * root._d)
        font.weight: Theme.fontMedium
        visible: root.caption !== ""
    }

    Text {
        id: readoutText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -(0.07 * root._d)
        text: root.readout !== "" ? root.readout : root._clamped.toFixed(root.decimals)
        color: Theme.autoText
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.28 * root._d)
        font.weight: Theme.fontSemibold
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: readoutText.bottom
        anchors.topMargin: 2
        text: root.readoutUnit
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.08 * root._d)
    }

    // -- 9. Label (bottom-right) --
    Text {
        // At the foot of the arc's opening, beside the last scale label.
        x: root.width / 2 + 0.22 * root._d
        y: root.height / 2 + 0.36 * root._d - height / 2
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(0.045 * root._d))
        visible: root.label !== ""
    }
}