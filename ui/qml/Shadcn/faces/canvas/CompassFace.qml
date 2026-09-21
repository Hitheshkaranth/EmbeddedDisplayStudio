/**
 * faces/canvas/CompassFace.qml
 * Canvas painter for ShCompass: the rotating heading card -- 72 tick marks
 * and the N/E/S/W and tens labels, each label rotated to stay tangent to the
 * card. The wrapper rotates this item by -heading; the painting itself does
 * not depend on the heading.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   line text
 * Font: 13 px "sans-serif" (the one literal, both painters).
 * C++ twin: native/hmi-gui/src/faces/compassface.cpp.
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
        if (s.line === undefined) return;
        var cx = width / 2, cy = height / 2, r = Math.min(width, height) / 2 - 4;
        ctx.strokeStyle = s.line;
        ctx.fillStyle = s.text;
        ctx.textAlign = "center";
        for (var deg = 0; deg < 360; deg += 5) {
            var a = (deg - 90) * Math.PI / 180;
            var major = deg % 30 === 0;
            var inner = r - (major ? 14 : 7);
            ctx.lineWidth = major ? 2 : 1;
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
            ctx.lineTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
            ctx.stroke();
            if (major) {
                var text = deg === 0 ? "N" : deg === 90 ? "E"
                         : deg === 180 ? "S" : deg === 270 ? "W" : (deg / 10);
                ctx.save();
                ctx.translate(cx + Math.cos(a) * (r - 28), cy + Math.sin(a) * (r - 28));
                ctx.rotate((deg) * Math.PI / 180);
                ctx.font = "13px sans-serif";
                ctx.fillText(text, 0, 5);
                ctx.restore();
            }
        }
    }
}
