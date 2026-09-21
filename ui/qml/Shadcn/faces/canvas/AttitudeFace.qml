/**
 * faces/canvas/AttitudeFace.qml
 * Canvas painter for ShAttitude: the fixed bank scale (eleven marks on the
 * upper arc) and the fixed aircraft symbol (two wing bars and a centre dot).
 * The moving horizon behind it is the wrapper's (Rectangle) job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   line aircraft
 * C++ twin: native/hmi-gui/src/faces/attitudeface.cpp.
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
        ctx.strokeStyle = s.line;
        ctx.fillStyle = s.aircraft;
        ctx.lineWidth = 2;
        var cx = width / 2, cy = height / 2, r = Math.min(width, height) * 0.44;
        var marks = [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60];
        for (var i = 0; i < marks.length; i++) {
            var a = (marks[i] - 90) * Math.PI / 180;
            var inner = marks[i] % 30 === 0 ? r - 12 : r - 7;
            ctx.beginPath();
            ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
            ctx.lineTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
            ctx.stroke();
        }
        // Fixed aircraft symbol: wings and a centre dot.
        ctx.strokeStyle = s.aircraft;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(cx - 46, cy); ctx.lineTo(cx - 16, cy);
        ctx.moveTo(cx + 16, cy); ctx.lineTo(cx + 46, cy);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(cx, cy, 3, 0, Math.PI * 2);
        ctx.fill();
    }
}
