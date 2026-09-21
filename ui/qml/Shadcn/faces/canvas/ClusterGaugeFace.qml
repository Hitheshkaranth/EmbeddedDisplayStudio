/**
 * faces/canvas/ClusterGaugeFace.qml
 * Canvas painter for ShClusterGauge: track, redline band, gradient value arc
 * with glow, major and minor ticks, optional inner dial. Text is the
 * wrapper's job.
 *
 * Draws from `spec` only -- never from Theme or a literal colour. Keys:
 *   value minimumValue maximumValue majorStep redlineFrom sweep showInnerDial
 *   track redline accentDeep accent glow line muted panel tileBorder dialTint
 * The C++ twin (native/hmi-gui/src/faces/clustergaugeface.cpp) must paint the
 * same pixels from the same spec; tst_faces compares them.
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
        var d = Math.min(width, height);
        var span = Math.max(0.0001, s.maximumValue - s.minimumValue);
        var clamped = Math.max(s.minimumValue, Math.min(s.maximumValue, s.value));

        // -- 1. Scale track --
        var startAngle = 90 + (360 - s.sweep) / 2;
        var arcR = 0.38 * d;
        var strokeW = 0.05 * d;

        ctx.beginPath();
        ctx.arc(cx, cy, arcR,
                startAngle * Math.PI / 180,
                (startAngle + s.sweep) * Math.PI / 180);
        ctx.lineWidth = strokeW;
        ctx.strokeStyle = s.track;
        ctx.stroke();

        // -- 2. Redline band (always visible) --
        if (s.redlineFrom < s.maximumValue) {
            var redStartFrac = (s.redlineFrom - s.minimumValue) / span;
            var redStartAngle = startAngle + s.sweep * redStartFrac;
            ctx.beginPath();
            ctx.arc(cx, cy, arcR,
                    redStartAngle * Math.PI / 180,
                    (startAngle + s.sweep) * Math.PI / 180);
            ctx.lineWidth = strokeW;
            ctx.strokeStyle = s.redline;
            ctx.stroke();
        }

        // -- 3. Value arc --
        var frac = (clamped - s.minimumValue) / span;
        var valueAngle = startAngle + s.sweep * frac;

        var grad = ctx.createLinearGradient(cx - arcR, cy, cx + arcR, cy);
        grad.addColorStop(0, s.accentDeep);
        grad.addColorStop(1, s.accent);

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
        ctx.strokeStyle = s.glow;
        ctx.stroke();

        // Redline portion of value arc (past redlineFrom)
        if (clamped > s.redlineFrom && s.redlineFrom < s.maximumValue) {
            var redStartFrac2 = (s.redlineFrom - s.minimumValue) / span;
            var redStartAngle2 = startAngle + s.sweep * redStartFrac2;
            ctx.beginPath();
            ctx.arc(cx, cy, arcR,
                    redStartAngle2 * Math.PI / 180,
                    valueAngle * Math.PI / 180);
            ctx.lineWidth = strokeW;
            ctx.strokeStyle = s.redline;
            ctx.stroke();
        }

        // -- 4. Major ticks --
        var tickLen = 0.035 * d;
        for (var mv = s.minimumValue; mv <= s.maximumValue + 0.0001; mv += s.majorStep) {
            var mvFrac = (mv - s.minimumValue) / span;
            var a = (startAngle + s.sweep * mvFrac) * Math.PI / 180;
            var tx1 = cx + (arcR + tickLen) * Math.cos(a);
            var ty1 = cy + (arcR + tickLen) * Math.sin(a);
            var tx2 = cx + arcR * Math.cos(a);
            var ty2 = cy + arcR * Math.sin(a);
            ctx.beginPath();
            ctx.moveTo(tx1, ty1);
            ctx.lineTo(tx2, ty2);
            ctx.lineWidth = 2;
            var isRedline = mv >= s.redlineFrom;
            ctx.strokeStyle = isRedline ? s.redline : s.line;
            ctx.stroke();
        }

        // -- 5. Minor ticks --
        var minorLen = tickLen * 0.5;
        var steps = Math.round(span / s.majorStep);
        for (var st = 0; st < steps; st++) {
            var baseVal = s.minimumValue + st * s.majorStep;
            for (var m = 1; m < 5; m++) {
                var mVal = baseVal + m * (s.majorStep / 5);
                if (mVal > s.maximumValue + 0.0001) break;
                var mFrac = (mVal - s.minimumValue) / span;
                var ma = (startAngle + s.sweep * mFrac) * Math.PI / 180;
                var mx1 = cx + (arcR + minorLen) * Math.cos(ma);
                var my1 = cy + (arcR + minorLen) * Math.sin(ma);
                var mx2 = cx + arcR * Math.cos(ma);
                var my2 = cy + arcR * Math.sin(ma);
                ctx.beginPath();
                ctx.moveTo(mx1, my1);
                ctx.lineTo(mx2, my2);
                ctx.lineWidth = 1.2;
                ctx.strokeStyle = s.muted;
                ctx.stroke();
            }
        }

        // -- 6. Inner dial --
        if (s.showInnerDial) {
            var innerR = 0.28 * d;
            ctx.beginPath();
            ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
            ctx.fillStyle = s.panel;
            ctx.fill();

            // Radial tint: dialTint at the centre fading to the same colour at alpha 0.
            var radGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, innerR);
            radGrad.addColorStop(0, s.dialTint);
            radGrad.addColorStop(1, Qt.rgba(s.dialTint.r, s.dialTint.g, s.dialTint.b, 0));
            ctx.beginPath();
            ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
            ctx.fillStyle = radGrad;
            ctx.fill();

            // Ring
            ctx.beginPath();
            ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
            ctx.lineWidth = 1.5;
            ctx.strokeStyle = s.tileBorder;
            ctx.stroke();
        }
    }
}
