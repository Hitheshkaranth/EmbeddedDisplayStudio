/**
 * NeonPaint.js
 * The kit's "neon" instrument strokes on a Canvas 2D context (ShClusterGauge
 * and ShSpeedArc style "neon"): a thick round-capped arc shaded along a
 * two-stop gradient, and its soft glow. The twin of hmi_draw_neon_arc /
 * hmi_draw_neon_glow in native/hmi-ui/src/widgets/draw_util.h, step for
 * step, so the panel and the desktop draw the same pixels:
 *
 *  - arcs run between whole degrees (LVGL has no float angles), cut into
 *    segments of about segDeg degrees, each in the gradient's colour at its
 *    middle; the gradient runs over [g0, g1] (the whole scale);
 *  - an opaque arc overlaps its segments by a degree and caps its ends with
 *    discs; a translucent one butts them and caps with half discs, so
 *    nothing is blended twice;
 *  - LVGL's arc geometry: centre rounded, outer edge round(r + w / 2),
 *    width round(w).
 * Angles are degrees, clockwise from 3 o'clock; colours are Qt colors.
 */
.pragma library

var CAP_START = 1;
var CAP_END = 2;
var CAPS = 3;
var GLOW_LAYERS = 8;
var GLOW_OPA = 30;          // of 255, per layer

function glowReach(d) { return Math.max(4, Math.min(16, 0.04 * d)); }

/** c0 moved toward c1 by 255ths, as lv_color_mix(c1, c0, round(255 t)). */
function mix(c0, c1, t) {
    var m = Math.round(255 * Math.max(0, Math.min(1, t))) / 255;
    return Qt.rgba(c0.r + (c1.r - c0.r) * m, c0.g + (c1.g - c0.g) * m, c0.b + (c1.b - c0.b) * m, 1);
}

function ramp(c0, c1, g0, g1, a) {
    return mix(c0, c1, g1 > g0 ? (a - g0) / (g1 - g0) : 0);
}

function _cround(v) { return Math.round(v); }

/** hmi_draw_arc: a butt-capped stroked arc. */
function arc(ctx, cx, cy, r, w, a0, a1, colour, opa) {
    if (a1 <= a0 || r <= 0 || w <= 0) return;
    var R = Math.round(r + w / 2), W = Math.round(w);
    if (W <= 0) return;
    ctx.globalAlpha = opa / 255;
    ctx.strokeStyle = colour;
    ctx.lineWidth = W;
    ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.arc(_cround(cx), _cround(cy), Math.max(0.5, R - W / 2), a0 * Math.PI / 180, a1 * Math.PI / 180, false);
    ctx.stroke();
}

/** The LVGL rounded arc (dsc.rounded = 1): one stroke, round caps. */
function arcRound(ctx, cx, cy, r, w, a0, a1, colour, opa) {
    if (a1 <= a0 || r <= 0 || w <= 0) return;
    var R = Math.round(r + w / 2), W = Math.round(w);
    if (W <= 0) return;
    ctx.globalAlpha = opa / 255;
    ctx.strokeStyle = colour;
    ctx.lineWidth = W;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(_cround(cx), _cround(cy), Math.max(0.5, R - W / 2), a0 * Math.PI / 180, a1 * Math.PI / 180, false);
    ctx.stroke();
    ctx.lineCap = "butt";
}

/** A filled pie of radius r from angle a0 to a1 around (cx, cy). */
function _pie(ctx, cx, cy, r, a0, a1, colour, opa) {
    ctx.globalAlpha = opa / 255;
    ctx.fillStyle = colour;
    ctx.beginPath();
    ctx.moveTo(_cround(cx), _cround(cy));
    ctx.arc(_cround(cx), _cround(cy), r, a0 * Math.PI / 180, a1 * Math.PI / 180, false);
    ctx.closePath();
    ctx.fill();
}

function neonArc(ctx, cx, cy, r, w, a0, a1, g0, g1, c0, c1, opa, segDeg, caps) {
    var ia0 = Math.round(a0), ia1 = Math.round(a1);
    if (ia1 <= ia0 || w < 1 || r <= 0 || opa <= 0) return;
    var span = ia1 - ia0;
    var n = Math.max(1, Math.min(48, Math.floor(span / (segDeg > 0 ? segDeg : 5))));
    var solid = opa >= 255;
    for (var i = 0; i < n; ++i) {
        var b0 = ia0 + Math.floor(span * i / n), b1 = ia0 + Math.floor(span * (i + 1) / n);
        arc(ctx, cx, cy, r, w, b0, solid && i < n - 1 ? b1 + 1 : b1, ramp(c0, c1, g0, g1, (b0 + b1) / 2), opa);
    }
    for (var end = 0; end < 2; ++end) {
        if (!(caps & (end ? CAP_END : CAP_START))) continue;
        var a = end ? ia1 : ia0;
        var ar = a * Math.PI / 180;
        var px = cx + r * Math.cos(ar), py = cy + r * Math.sin(ar);
        var c = ramp(c0, c1, g0, g1, a);
        if (solid) {
            _pie(ctx, px, py, Math.round(w / 2), 0, 360, c, opa);
        } else {
            var from = end ? a : a - 180;   // the half facing away from the arc
            _pie(ctx, px, py, Math.round(w / 2), from, from + 180, c, opa);
        }
    }
}

function neonGlow(ctx, cx, cy, r, w, a0, a1, g0, g1, c0, c1, reach, caps) {
    for (var k = GLOW_LAYERS; k >= 1; --k)
        neonArc(ctx, cx, cy, r, w + 2 * reach * k / GLOW_LAYERS, a0, a1, g0, g1, c0, c1, GLOW_OPA, 10, caps);
}

/** hmi_draw_line: a butt-capped line at least 1 px wide. */
function line(ctx, x1, y1, x2, y2, w, colour, opa) {
    ctx.globalAlpha = opa / 255;
    ctx.strokeStyle = colour;
    ctx.lineWidth = Math.max(1, Math.round(w));
    ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
}
