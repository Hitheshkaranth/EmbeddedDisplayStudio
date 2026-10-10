/**
 * ShSpeedArc.qml
 * Speed Arc -- Rail widget. The driver-cab speedometer of a metro train:
 * two neon arcs on a transparent background, open on the lower right.
 *
 * Drawing (all dimensions relative to d = Math.min(width, height); angles
 * clockwise from 3 o'clock; both arcs run 240 degrees from 90 (6 o'clock)
 * up the left side and over the top to 330):
 * 1. Wedge       – a faint outerColor pie from the start to the needle, at
 *                  radius 0.323d, brighter over the last 40 and 14 degrees
 * 2. Inner arc   – the full sweep in innerColor, radius 0.335d, stroke 0.024d,
 *                  over two wide translucent glow strokes (3x at 10 %, 1.9x at 18 %)
 * 3. Outer arc   – a faint track (14 %), then the value: value / maximumValue
 *                  of the sweep in outerColor, radius 0.40d, stroke 0.034d, with glow
 * 4. Needle      – outerColor line at the value angle from 0.20d out past the
 *                  outer arc (0.011d, over a 0.026d glow at 25 %)
 * 5. Target tick – white 0.010d line across the outer arc (showTarget)
 * 6. Readout     – the value (decimals places), white bold 0.226d (smaller
 *                  when long), 0.045d above the centre; unit below in outerColor
 * 7. Callout     – "<targetLabel>: <target> <unit, lower case>" in a dark box
 *                  (#1c1c22, 1 px #3a3a44) above the tick on the upper dial,
 *                  pushed outwards elsewhere, never over the readout
 * Values outside 0..maximumValue clamp. The hmi-ui twin is
 * native/hmi-ui/src/widgets/w_shspeedarc.c.
 *
 * style "neon" (default "classic"): no wedge, needle or callout. The value
 * as three concentric round-capped arcs over the same 240 degrees: the
 * outermost (radius 0.40d, stroke 0.055d) over a 14 % track and a soft
 * glow, shaded from outerColor 10 % darker to 40 % lighter along the scale;
 * inside it 0.325d / 0.04d in outerColor halfway to innerColor at 85 %, and
 * 0.26d / 0.028d in innerColor at 60 %. The value bold ~0.28d (smaller when
 * long), the unit (0.08d, #b4bfcc) under it; the target a white tick.
 */
import QtQuick 2.15
import "NeonPaint.js" as Neon

Item {
    id: root
    implicitWidth: 420
    implicitHeight: 420
    property real value: 55.0
    property real maximumValue: 100.0
    property real target: 60.0
    property bool showTarget: true
    property string unit: 'KM/H'
    property string targetLabel: 'TARGET'
    property int decimals: 0
    property string outerColor: '#22d3ee'
    property string innerColor: '#a855f7'
    /** "classic" | "neon" */
    property string style: 'classic'
    readonly property bool _neon: style === 'neon'

    readonly property real _d: Math.max(1, Math.min(width, height))
    readonly property real _cx: width / 2
    readonly property real _cy: height / 2
    readonly property real _span: Math.max(0.0001, root.maximumValue)
    readonly property int _dp: Math.max(0, Math.min(6, root.decimals))
    readonly property real _outerR: 0.40 * _d
    readonly property real _outerW: 0.034 * _d
    readonly property real _innerR: 0.335 * _d
    readonly property real _innerW: 0.024 * _d

    function _clamp(v) { return Math.max(0, Math.min(root.maximumValue, v)) }
    function _angle(v) { return 90 + 240 * root._clamp(v) / root._span }

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            if (root._neon) {
                root._paintNeon(ctx);
                return;
            }
            var d = root._d, cx = root._cx, cy = root._cy;
            var rad = Math.PI / 180;
            var a0 = 90, a1 = 330, av = root._angle(root.value);
            var outer = root.outerColor, inner = root.innerColor;
            ctx.lineCap = "round";

            function wedge(r, from, to, alpha) {
                if (to <= from) return;
                ctx.globalAlpha = alpha;
                ctx.fillStyle = outer;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.arc(cx, cy, r, from * rad, to * rad, false);
                ctx.closePath();
                ctx.fill();
            }
            function arc(r, w, from, to, colour, alpha) {
                if (to <= from) return;
                ctx.globalAlpha = alpha;
                ctx.strokeStyle = colour;
                ctx.lineWidth = w;
                ctx.beginPath();
                ctx.arc(cx, cy, r, from * rad, to * rad, false);
                ctx.stroke();
            }
            function neon(r, w, from, to, colour) {
                arc(r, w * 3.0, from, to, colour, 0.10);
                arc(r, w * 1.9, from, to, colour, 0.18);
                arc(r, w, from, to, colour, 1.0);
            }
            function line(r0, r1, a, w, colour, alpha) {
                ctx.globalAlpha = alpha;
                ctx.strokeStyle = colour;
                ctx.lineWidth = Math.max(1, Math.round(w));
                ctx.lineCap = "butt";
                ctx.beginPath();
                ctx.moveTo(cx + r0 * Math.cos(a * rad), cy + r0 * Math.sin(a * rad));
                ctx.lineTo(cx + r1 * Math.cos(a * rad), cy + r1 * Math.sin(a * rad));
                ctx.stroke();
                ctx.lineCap = "round";
            }

            // 1. wedge
            var wedgeR = root._innerR - root._innerW / 2;
            wedge(wedgeR, a0, av, 0.06);
            wedge(wedgeR, Math.max(a0, av - 40), av, 0.07);
            wedge(wedgeR, Math.max(a0, av - 14), av, 0.08);
            // 2. inner arc
            neon(root._innerR, root._innerW, a0, a1, inner);
            // 3. outer arc: track, then the value
            arc(root._outerR, root._outerW, a0, a1, outer, 0.14);
            if (av > a0) neon(root._outerR, root._outerW, a0, av, outer);
            // 4. needle
            var r1 = root._outerR + root._outerW / 2 + 0.01 * d;
            line(0.20 * d, r1, av, 0.026 * d, outer, 0.25);
            line(0.20 * d, r1, av, 0.011 * d, outer, 1.0);
            // 5. target tick
            if (root.showTarget) {
                line(root._outerR - root._outerW / 2 - 0.022 * d, root._outerR + root._outerW / 2 + 0.022 * d,
                     root._angle(root.target), 0.010 * d, "#ffffff", 1.0);
            }
        }
    }

    function _paintNeon(ctx) {
        var d = root._d, cx = root._cx, cy = root._cy;
        var outer = Qt.tint(root.outerColor, "transparent"), inner = Qt.tint(root.innerColor, "transparent");
        var mid = Neon.mix(outer, inner, 128 / 255);   // lv_color_mix(inner, outer, 128)
        var a0 = 90, a1 = 330, av = Math.round(root._angle(root.value));
        var r0 = 0.40 * d, w0 = 0.055 * d;
        Neon.arcRound(ctx, cx, cy, r0, w0, a0, a1, outer, 35);
        Neon.neonGlow(ctx, cx, cy, r0, w0, a0, av, a0, a1, outer, outer, Neon.glowReach(d), Neon.CAPS);
        Neon.neonArc(ctx, cx, cy, r0, w0, a0, av, a0, a1, Theme.shade(outer, -10), Theme.shade(outer, 40),
                     255, 5, Neon.CAPS);
        Neon.arcRound(ctx, cx, cy, 0.325 * d, 0.04 * d, a0, av, mid, 216);
        Neon.arcRound(ctx, cx, cy, 0.26 * d, 0.028 * d, a0, av, inner, 153);
        if (root.showTarget) {
            var at = root._angle(root.target) * Math.PI / 180;
            var t0 = r0 - w0 / 2 - 0.015 * d, t1 = r0 + w0 / 2 + 0.015 * d;
            Neon.line(ctx, cx + t0 * Math.cos(at), cy + t0 * Math.sin(at), cx + t1 * Math.cos(at),
                      cy + t1 * Math.sin(at), Math.max(2, 0.010 * d), "#ffffff", 255);
        }
        ctx.globalAlpha = 1;
    }

    onStyleChanged: canvas.requestPaint()
    onValueChanged: canvas.requestPaint()
    onMaximumValueChanged: canvas.requestPaint()
    onTargetChanged: canvas.requestPaint()
    onShowTargetChanged: canvas.requestPaint()
    onOuterColorChanged: canvas.requestPaint()
    onInnerColorChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    // -- 6. readout + unit --
    Text {
        id: readoutText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -Math.round((root._neon ? 0.035 : 0.045) * root._d)
        text: root._clamp(root.value).toFixed(root._dp)
        color: "#ffffff"
        font.family: Theme.fontFamily
        // a long readout ("100.0") takes a smaller face so it stays inside the inner arc
        font.pixelSize: root._neon
            ? Math.max(8, Math.round(Math.min(0.28 * root._d, 0.46 * root._d / (Math.max(1, text.length) * 0.6))))
            : Math.max(8, Math.round(Math.min(0.226 * root._d,
                       0.58 * root._d / (Math.max(1, text.length) * 0.62))))
        font.weight: 700
    }

    Text {
        id: unitText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: readoutText.bottom
        anchors.topMargin: root._neon ? -Math.round(0.12 * readoutText.font.pixelSize) : -Math.round(0.03 * root._d)
        text: root.unit
        color: root._neon ? "#b4bfcc" : root.outerColor
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round((root._neon ? 0.08 : 0.071) * root._d))
        font.weight: 500
    }

    // -- 7. target callout --
    Rectangle {
        id: callout
        visible: root.showTarget && !root._neon
        readonly property real _padH: Math.round(0.026 * root._d)
        readonly property real _padV: Math.round(0.012 * root._d)
        width: calloutText.implicitWidth + 2 * _padH + 2
        height: calloutText.implicitHeight + 2 * _padV + 2
        radius: Math.round(0.018 * root._d)
        color: "#1c1c22"
        border.color: "#3a3a44"
        border.width: 1

        readonly property point _pos: {
            var d = root._d, cx = root._cx, cy = root._cy;
            var at = root._angle(root.target) * Math.PI / 180;
            var tr = root._outerR + root._outerW / 2 + 0.022 * d;
            var gap = 0.014 * d, bw = width, bh = height, bx, by;
            if (Math.sin(at) < -0.35) {
                bx = cx + root._outerR * Math.cos(at) - bw / 2;
                by = cy + tr * Math.sin(at) - gap - bh;
            } else {
                bx = cx + tr * Math.cos(at) + Math.cos(at) * (bw / 2 + gap) - bw / 2;
                by = cy + tr * Math.sin(at) + Math.sin(at) * (bh / 2 + gap) - bh / 2;
            }
            bx = Math.max(0, Math.min(Math.max(0, root.width - bw), bx));
            by = Math.max(0, Math.min(Math.max(0, root.height - bh), by));
            // never over the readout: step up or down out of its band
            var half = readoutText.width / 2 + gap;
            var top = cy - 0.15 * d, bottom = cy + 0.15 * d;
            if (bx < cx + half && bx + bw > cx - half && by < bottom && by + bh > top) {
                var up = top - bh, down = bottom;
                by = Math.abs(by - up) <= Math.abs(by - down) ? up : down;
                by = Math.max(0, Math.min(Math.max(0, root.height - bh), by));
            }
            return Qt.point(Math.round(bx), Math.round(by));
        }
        x: _pos.x
        y: _pos.y

        Text {
            id: calloutText
            anchors.centerIn: parent
            text: {
                var u = root.unit.toLowerCase();
                return (root.targetLabel !== "" ? root.targetLabel + ": " : "")
                    + root._clamp(root.target).toFixed(root._dp) + (u !== "" ? " " + u : "");
            }
            color: "#ffffff"
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(0.048 * root._d))
            font.weight: 500
        }
    }
}
