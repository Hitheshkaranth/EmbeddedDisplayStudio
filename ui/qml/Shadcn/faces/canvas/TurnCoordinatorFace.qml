/**
 * faces/canvas/TurnCoordinatorFace.qml
 * Canvas painter for ShTurnCoordinator: the upper half-circle scale and its
 * five index marks. The aircraft symbol and the slip ball are the wrapper's
 * (Rectangle) job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   line
 * C++ twin: native/hmi-gui/src/faces/turncoordinatorface.cpp.
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
        var c = getContext("2d");
        c.reset();
        if (s.line === undefined) return;
        var cx = width / 2, cy = height * 0.43, r = Math.min(width * 0.38, height * 0.38);
        c.strokeStyle = s.line;
        c.lineWidth = 2;
        c.beginPath();
        c.arc(cx, cy, r, Math.PI, 2 * Math.PI);
        c.stroke();
        for (var i = -2; i <= 2; i++) {
            var x = cx + i * r / 2;
            c.beginPath();
            c.moveTo(x, cy - r);
            c.lineTo(x, cy - r + 8);
            c.stroke();
        }
    }
}
