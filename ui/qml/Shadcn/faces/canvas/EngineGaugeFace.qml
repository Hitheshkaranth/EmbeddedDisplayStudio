/**
 * faces/canvas/EngineGaugeFace.qml
 * Canvas painter for ShEngineGauge: four coloured arc bands and a needle
 * with a hub. Text is the wrapper's job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   value minimumValue maximumValue greenLow greenHigh cautionHigh
 *   caution normal warning line
 * C++ twin: native/hmi-gui/src/faces/enginegaugeface.cpp.
 */
import QtQuick 2.15

Canvas {
    id: face
    property var spec: ({})
    onSpecChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Component.onCompleted: requestPaint()

    onPaint: {
        var s = spec;
        var ctx = getContext("2d");
        ctx.reset();
        if (s.value === undefined) return;
        var cx = width / 2, cy = height / 2;
        var dim = Math.min(width, height);
        var r = dim / 2 - dim * 0.12;
        var stroke = Math.max(4, dim * 0.11);
        var span = Math.max(0.0001, s.maximumValue - s.minimumValue);
        var clamped = Math.max(s.minimumValue, Math.min(s.maximumValue, s.value));
        // 240 degrees of sweep opening downward, as a round gauge reads.
        var start = 150, sweep = 240;

        function arc(fromValue, toValue, colour) {
            var a0 = (fromValue - s.minimumValue) / span;
            var a1 = (toValue - s.minimumValue) / span;
            ctx.beginPath();
            ctx.lineWidth = stroke;
            ctx.strokeStyle = colour;
            ctx.arc(cx, cy, r,
                    (start + sweep * a0) * Math.PI / 180,
                    (start + sweep * a1) * Math.PI / 180);
            ctx.stroke();
        }

        arc(s.minimumValue, s.greenLow, s.caution);
        arc(s.greenLow, s.greenHigh, s.normal);
        arc(s.greenHigh, s.cautionHigh, s.caution);
        arc(s.cautionHigh, s.maximumValue, s.warning);

        // Needle.
        var f = (clamped - s.minimumValue) / span;
        var a = (start + sweep * f) * Math.PI / 180;
        ctx.strokeStyle = s.line;
        ctx.lineWidth = Math.max(2, dim * 0.025);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * (r - stroke * 0.6),
                   cy + Math.sin(a) * (r - stroke * 0.6));
        ctx.stroke();
        ctx.fillStyle = s.line;
        ctx.beginPath();
        ctx.arc(cx, cy, Math.max(2, dim * 0.03), 0, Math.PI * 2);
        ctx.fill();
    }
}
