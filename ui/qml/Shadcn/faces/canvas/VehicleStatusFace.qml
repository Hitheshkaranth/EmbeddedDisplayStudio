/**
 * faces/canvas/VehicleStatusFace.qml
 * Canvas painter for ShVehicleStatus: four wheels, the rounded car body and
 * the two window lines. Readouts and labels are the wrapper's job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   bodyX bodyY bodyW bodyH bodyRadius wheelW wheelH
 *   frontLeftLow frontRightLow rearLeftLow rearRightLow (bool)
 *   wheel wheelLow bodyFill bodyLine glass
 * C++ twin: native/hmi-gui/src/faces/vehiclestatusface.cpp.
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
        if (s.bodyW === undefined) return;
        var x = s.bodyX, y = s.bodyY, w = s.bodyW, h = s.bodyH;
        var r = s.bodyRadius;
        var wheelW = s.wheelW, wheelH = s.wheelH;

        function roundedRect(rx, ry, rw, rh, rr) {
            ctx.beginPath();
            ctx.moveTo(rx + rr, ry);
            ctx.lineTo(rx + rw - rr, ry);
            ctx.arcTo(rx + rw, ry, rx + rw, ry + rr, rr);
            ctx.lineTo(rx + rw, ry + rh - rr);
            ctx.arcTo(rx + rw, ry + rh, rx + rw - rr, ry + rh, rr);
            ctx.lineTo(rx + rr, ry + rh);
            ctx.arcTo(rx, ry + rh, rx, ry + rh - rr, rr);
            ctx.lineTo(rx, ry + rr);
            ctx.arcTo(rx, ry, rx + rr, ry, rr);
            ctx.closePath();
        }

        // Wheels first, so the body's edge sits over them.
        var wheels = [
            [x - wheelW * 0.6, y + h * 0.12, s.frontLeftLow],
            [x + w - wheelW * 0.4, y + h * 0.12, s.frontRightLow],
            [x - wheelW * 0.6, y + h * 0.88 - wheelH, s.rearLeftLow],
            [x + w - wheelW * 0.4, y + h * 0.88 - wheelH, s.rearRightLow]];
        for (var i = 0; i < wheels.length; ++i) {
            ctx.fillStyle = wheels[i][2] ? s.wheelLow : s.wheel;
            roundedRect(wheels[i][0], wheels[i][1], wheelW, wheelH, wheelW * 0.3);
            ctx.fill();
        }

        // Body.
        ctx.fillStyle = s.bodyFill;
        ctx.strokeStyle = s.bodyLine;
        ctx.lineWidth = 1.5;
        roundedRect(x, y, w, h, r);
        ctx.fill();
        ctx.stroke();

        // Windscreen and rear window.
        ctx.strokeStyle = s.glass;
        ctx.lineWidth = 1.2;
        var inset = w * 0.12;
        ctx.beginPath();
        ctx.moveTo(x + inset, y + h * 0.28); ctx.lineTo(x + w - inset, y + h * 0.28);
        ctx.moveTo(x + inset, y + h * 0.72); ctx.lineTo(x + w - inset, y + h * 0.72);
        ctx.stroke();
    }
}
