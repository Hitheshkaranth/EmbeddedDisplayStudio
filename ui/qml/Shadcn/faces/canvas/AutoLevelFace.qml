/**
 * faces/canvas/AutoLevelFace.qml
 * Canvas painter for ShAutoLevel: the curved bar (track, red zone, gradient
 * fill, glow line) clipped to its outline, and the tick marks down its left
 * edge. Labels and the icon are the wrapper's job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   fraction (0..1) redZone ("low"|"high"|other) redZoneSpan (percent)
 *   showTicks barX barW barTop barH bulge tickMajor tickMinor
 *   track zone redline accentDeep accent glow line
 * The geometry keys are the wrapper's shared bar geometry (the labels use the
 * same numbers), so the face never derives them from its own size.
 * C++ twin: native/hmi-gui/src/faces/autolevelface.cpp.
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
        if (s.fraction === undefined) return;
        var x = s.barX, w = s.barW, top = s.barTop, h = s.barH, bulge = s.bulge;
        var bottom = top + h, midY = top + h / 2, r = w / 2;

        // The bar outline: two quadratic edges bulging left by bulge.
        function outline() {
            ctx.beginPath();
            ctx.moveTo(x, top + r);
            ctx.arc(x + r, top + r, r, Math.PI, 0);
            ctx.quadraticCurveTo(x + w - bulge, midY, x + w, bottom - r);
            ctx.arc(x + r, bottom - r, r, 0, Math.PI);
            ctx.quadraticCurveTo(x - bulge, midY, x, top + r);
            ctx.closePath();
        }

        ctx.save();
        outline();
        ctx.clip();

        // Track.
        ctx.fillStyle = s.track;
        ctx.fillRect(x - bulge - 1, top - 1, w + bulge + 2, h + 2);

        // Red zone: a slice of the track at the low or high end.
        var zone = Math.max(0, Math.min(1, s.redZoneSpan / 100)) * h;
        var zoneTop = -1, zoneBottom = -1;
        if (s.redZone === "low") { zoneTop = bottom - zone; zoneBottom = bottom; }
        else if (s.redZone === "high") { zoneTop = top; zoneBottom = top + zone; }
        if (zoneTop >= 0) {
            ctx.fillStyle = s.zone;
            ctx.fillRect(x - bulge - 1, zoneTop, w + bulge + 2, zoneBottom - zoneTop);
        }

        // Fill from the bottom to the value.
        var fillTop = bottom - h * s.fraction;
        if (s.fraction > 0) {
            var grad = ctx.createLinearGradient(0, bottom, 0, fillTop);
            grad.addColorStop(0, s.accentDeep);
            grad.addColorStop(1, s.accent);
            ctx.fillStyle = grad;
            ctx.fillRect(x - bulge - 1, fillTop, w + bulge + 2, bottom - fillTop);
            // Fill inside the red zone reads as red, not blue.
            if (zoneTop >= 0) {
                var rt = Math.max(zoneTop, fillTop), rb = Math.min(zoneBottom, bottom);
                if (rb > rt) {
                    ctx.fillStyle = s.redline;
                    ctx.fillRect(x - bulge - 1, rt, w + bulge + 2, rb - rt);
                }
            }
            ctx.fillStyle = s.glow;
            ctx.fillRect(x - bulge - 1, fillTop, w + bulge + 2, 2);
        }
        ctx.restore();

        // Ticks along the left edge of the bar.
        if (s.showTicks) {
            ctx.strokeStyle = s.line;
            for (var i = 0; i <= 10; ++i) {
                var f = i / 10;
                var y = bottom - h * f;
                // Left edge of the curve at this height.
                var t = 1 - Math.abs(f - 0.5) * 2;      // 0 at the ends, 1 mid
                var edge = x - bulge * (1 - (1 - t) * (1 - t)) * 0.5;
                var len = (i % 5 === 0) ? s.tickMajor : s.tickMinor;
                ctx.lineWidth = (i % 5 === 0) ? 1.5 : 1;
                ctx.beginPath();
                ctx.moveTo(edge - 2, y);
                ctx.lineTo(edge - 2 - len, y);
                ctx.stroke();
            }
        }
    }
}
