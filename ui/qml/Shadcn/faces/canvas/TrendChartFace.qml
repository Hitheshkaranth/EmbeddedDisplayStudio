/**
 * faces/canvas/TrendChartFace.qml
 * Canvas painter for ShTrendChart: the gradient fill under the trace, the
 * trace itself and the current-value dot. Grid, zones and labels are the
 * wrapper's job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   data (array of numbers) minValue maxValue maxPoints lineWidth
 *   lineColor fillColor background
 * C++ twin: native/hmi-gui/src/faces/trendchartface.cpp.
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
        if (s.data === undefined) return;

        var pts = s.data.slice(-s.maxPoints);
        if (pts.length < 2) return;

        var w = width;
        var h = height;
        var stepX = w / (s.maxPoints - 1);
        var yScale = 1.0 / (s.maxValue - s.minValue > 0 ? s.maxValue - s.minValue : 1);

        // Fill area
        ctx.beginPath();
        ctx.moveTo(0, h);
        for (var i = 0; i < pts.length; i++) {
            var x = i * stepX;
            var y = h - (pts[i] - s.minValue) * yScale * h;
            ctx.lineTo(x, y);
        }
        ctx.lineTo((pts.length - 1) * stepX, h);
        ctx.closePath();

        var grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, Qt.rgba(s.fillColor.r, s.fillColor.g, s.fillColor.b, 0.2));
        grad.addColorStop(1, Qt.rgba(s.fillColor.r, s.fillColor.g, s.fillColor.b, 0.02));
        ctx.fillStyle = grad;
        ctx.fill();

        // Line
        ctx.beginPath();
        for (var j = 0; j < pts.length; j++) {
            var lx = j * stepX;
            var ly = h - (pts[j] - s.minValue) * yScale * h;
            if (j === 0) ctx.moveTo(lx, ly);
            else ctx.lineTo(lx, ly);
        }
        ctx.strokeStyle = s.lineColor;
        ctx.lineWidth = s.lineWidth;
        ctx.lineJoin = "round";
        ctx.stroke();

        // Current value dot
        var lastX = (pts.length - 1) * stepX;
        var lastY = h - (pts[pts.length - 1] - s.minValue) * yScale * h;
        ctx.beginPath();
        ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
        ctx.fillStyle = s.fillColor;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
        ctx.fillStyle = s.background;
        ctx.fill();
    }
}
