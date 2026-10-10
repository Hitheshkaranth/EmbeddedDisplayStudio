/**
 * ShTrendChart.qml
 * History trend chart with grid lines, value trace, and severity zones.
 * Designed for continuous process monitoring in industrial HMI.
 */
import QtQuick 2.15

Item {
    id: root

    /** @property {var} data Array of numeric values to plot */
    property var data: []
    /** @property {real} minValue Y-axis minimum */
    property real minValue: 0
    /** @property {real} maxValue Y-axis maximum */
    property real maxValue: 100
    /** @property {real} warningLow Lower warning threshold */
    property real warningLow: 20
    /** @property {real} warningHigh Upper warning threshold */
    property real warningHigh: 80
    /** @property {int} maxPoints Maximum data points to display */
    property int maxPoints: 100
    /** @property {string} label Chart label */
    property string label: ""
    /** @property {string} unit Y-axis unit label */
    property string unit: ""
    /** @property {color} lineColor Line color */
    property color lineColor: Theme.brand
    /** @property {color} fillColor Fill gradient color */
    property color fillColor: Theme.brand
    /** @property {real} lineWidth Line width */
    property real lineWidth: 2
    /**
     * @property {string} series "Label|#color|level;Label|#color|level;..."
     * "" (the default) is the single trace above. Set, the chart is a
     * multi-series dashboard trend: a framed plot with "nice" y ticks and
     * labels at the left (the unit above them), xLabels under the x axis, a
     * legend at the right; until live data each series draws a deterministic
     * gently-noisy line about its level (_noise(), the same formula as
     * w_shtrendchart.c's trend_noise()), and `data` feeds the first series.
     * The warning band is not drawn in this mode.
     */
    property string series: ""
    /** @property {string} xLabels "12:30,13:00,..." under the x axis (series mode) */
    property string xLabels: ""

    readonly property var _series: {
        var out = [];
        var palette = ["#ff3b3b", "#ff9f1c", "#ffd23f", "#3ee05a", "#22b8ff", "#a78bfa", "#f472b6", "#94a3b8"];
        var items = root.series.split(";");
        for (var i = 0; i < items.length && out.length < 8; ++i) {
            var item = items[i].trim();
            if (item === "") continue;
            var f = item.split("|");
            var col = f.length > 1 ? f[1].trim() : "";
            var lvl = f.length > 2 ? parseFloat(f[2]) : NaN;
            out.push({ label: f[0].trim(), colour: col.charAt(0) === "#" ? col : palette[out.length % 8],
                       level: isFinite(lvl) ? lvl : NaN });
        }
        return out;
    }
    readonly property var _xLabels: root.xLabels === "" ? [] : root.xLabels.split(",").slice(0, 12).map(function(s) { return s.trim() })
    on_SeriesChanged: seriesCanvas.requestPaint()
    on_XLabelsChanged: seriesCanvas.requestPaint()
    onDataChanged: if (root._series.length > 0) seriesCanvas.requestPaint()
    onWidthChanged: seriesCanvas.requestPaint()
    onHeightChanged: seriesCanvas.requestPaint()

    function _noise(s, i, n) {
        var h = (Math.imul(i, 374761393) + Math.imul(s + 1, 668265263)) >>> 0;
        h = Math.imul((h ^ (h >>> 13)) >>> 0, 1274126177) >>> 0;
        h = (h ^ (h >>> 16)) >>> 0;
        var r = h / 4294967295 * 2 - 1;
        var t = n > 1 ? i / (n - 1) : 0;
        return 0.62 * r + 0.38 * Math.sin(2 * Math.PI * (1.3 + 0.37 * s) * t + 1.7 * s);
    }
    function _niceStep(range, maxTicks) {
        if (range <= 0 || maxTicks < 1) return 1;
        var raw = range / maxTicks;
        var mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10));
        var steps = [1, 2, 2.5, 5, 10];
        for (var i = 0; i < steps.length; ++i)
            if (steps[i] * mag >= raw - 1e-9 * mag) return steps[i] * mag;
        return 10 * mag;
    }
    function _tick(v, step) {
        if (Math.abs(v) < step * 1e-6) v = 0;
        var dec = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log(step) / Math.LN10 - 1e-9));
        var s = v.toFixed(dec);
        var neg = s.charAt(0) === "-";
        if (neg) s = s.substring(1);
        var dot = s.indexOf(".");
        var ip = dot >= 0 ? s.substring(0, dot) : s;
        var out = "";
        for (var i = 0; i < ip.length; ++i) {
            out += ip.charAt(i);
            var left = ip.length - 1 - i;
            if (left > 0 && left % 3 === 0) out += ",";
        }
        return (neg ? "-" : "") + out + (dot >= 0 ? s.substring(dot) : "");
    }
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }

    implicitWidth: 300
    implicitHeight: 180

    readonly property int _visiblePoints: Math.min(root.data.length, root.maxPoints)
    readonly property real _yScale: 1.0 / (root.maxValue - root.minValue > 0 ? root.maxValue - root.minValue : 1)

    readonly property color _gridColor: Theme.border
    readonly property color _warnZoneColor: Qt.rgba(Theme.warning.r, Theme.warning.g, Theme.warning.b, 0.08)

    // Everything the face painter needs, values and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        data: root.data, minValue: root.minValue, maxValue: root.maxValue,
        maxPoints: root.maxPoints, lineWidth: root.lineWidth,
        lineColor: root.lineColor, fillColor: root.fillColor, background: Theme.background
    })

    // `data` (public API: the sample array) shadows Item's default property
    // of the same name, so children declared in the body would be assigned
    // to the array and never become visual children. The visual tree is
    // therefore held by a named property and parented explicitly.
    property Item _body: Item {
        parent: root
        anchors.fill: parent   // re-evaluated once parent is set

    // The series view (see `series`): one Canvas paints it all.
    Canvas {
        id: seriesCanvas
        anchors.fill: parent
        visible: root._series.length > 0
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var S = root._series;
            if (S.length === 0) return;
            var W = Math.max(1, width), H = Math.max(1, height);
            var fam = "'" + Theme.fontFamily + "'";
            function font(px, weight) { return weight + " " + px + "px " + fam }
            function tw(text, px, weight) { ctx.font = font(px, weight); return Math.ceil(ctx.measureText(text).width) }
            function text(t, px, weight, colour, x, y, w, align) {
                ctx.font = font(px, weight);
                ctx.fillStyle = colour;
                ctx.textAlign = align;
                ctx.textBaseline = "alphabetic";
                ctx.fillText(t, align === "right" ? x + w : x, y + root._asc(px));
            }
            var tickPx = Math.max(8, Math.min(12, Math.round(H * 0.055)));
            var legendPx = Math.max(8, Math.min(13, Math.round(H * 0.065)));
            var tickLH = root._lineH(tickPx);
            var muted = Theme.mutedForeground, grid = Theme.border;
            var top = 0;
            if (root.label !== "") {
                text(root.label, Theme.fontSizeXs, 500, muted, 0, 0, W, "left");
                top += root._lineH(Theme.fontSizeXs) + 4;
            }
            if (root.unit !== "") {
                text(root.unit, tickPx, 400, muted, 0, top, W / 3, "left");
                top += tickLH + 2;
            }
            top += Math.floor(tickLH / 2);
            var X = root._xLabels;
            var bottom = Math.floor(H) - (X.length > 0 ? tickLH + 4 : Math.floor(tickLH / 2)) - 1;
            var swatch = Math.max(8, Math.round(legendPx * 1.25));
            var legendW = 0;
            for (var s = 0; s < S.length; ++s) legendW = Math.max(legendW, tw(S[s].label, legendPx, 400));
            legendW += swatch + 8 + 10;
            if (legendW > W * 0.45) legendW = 0;
            var lo = root.minValue, hi = root.maxValue > root.minValue ? root.maxValue : root.minValue + 1;
            var maxTicks = Math.floor(Math.max(2, Math.min(10, (bottom - top) / (tickLH * 1.6))));
            var step = root._niceStep(hi - lo, maxTicks);
            var first = Math.ceil(lo / step - 1e-9) * step;
            var yLW = 0, v;
            for (v = first; v <= hi + step * 1e-6; v += step) yLW = Math.max(yLW, tw(root._tick(v, step), tickPx, 400));
            var x0 = yLW + 6;
            var x1 = Math.floor(W) - legendW - 6;
            if (X.length > 0 && legendW === 0)
                x1 = Math.min(x1, Math.floor(W) - (Math.floor(tw(X[X.length - 1], tickPx, 400) / 2) + 1));
            if (x1 - x0 < 10 || bottom - top < 10) return;
            var pw = x1 - x0, ph = bottom - top;
            ctx.fillStyle = Theme.background;
            ctx.fillRect(x0, top, pw, ph);
            ctx.fillStyle = Qt.rgba(grid.r, grid.g, grid.b, 150 / 255);
            var ticks = [];
            for (v = first; v <= hi + step * 1e-6; v += step) {
                var yi = Math.round(bottom - (v - lo) / (hi - lo) * ph);
                ticks.push([v, yi]);
                if (yi > top && yi < bottom) ctx.fillRect(x0, yi, pw, 1);
            }
            for (var k = 0; k < ticks.length; ++k)
                text(root._tick(ticks[k][0], step), tickPx, 400, muted, 0, ticks[k][1] - Math.floor(tickLH / 2), yLW, "right");
            for (var i = 0; i < X.length; ++i) {
                var xi = Math.round(X.length > 1 ? x0 + pw * i / (X.length - 1) : x0);
                if (xi > x0 && xi < x1) {
                    ctx.fillStyle = Qt.rgba(grid.r, grid.g, grid.b, 90 / 255);
                    ctx.fillRect(xi, top, 1, ph);
                }
                var w2 = tw(X[i], tickPx, 400);
                var tx = Math.max(0, Math.min(Math.floor(W) - w2, xi - Math.floor(w2 / 2)));
                text(X[i], tickPx, 400, muted, tx, bottom + 4, w2 + 2, "left");
            }
            ctx.fillStyle = Theme.shade(grid, 45);
            ctx.fillRect(x0, top, 1, ph + 1);
            ctx.fillRect(x0, bottom, pw, 1);
            // the lines
            ctx.lineWidth = Math.max(1, Math.round(root.lineWidth > 0 ? root.lineWidth : 2));
            ctx.lineJoin = "round";
            var n = Math.max(8, Math.min(160, Math.round(pw / 5)));
            var data = root.data || [];
            for (s = 0; s < S.length; ++s) {
                var live = s === 0 && data.length >= 2;
                var count = live ? Math.min(data.length, root.maxPoints) : n;
                var level = isNaN(S[s].level) ? (lo + hi) / 2 : S[s].level;
                ctx.strokeStyle = S[s].colour;
                ctx.beginPath();
                for (var j = 0; j < count; ++j) {
                    var val, x;
                    if (live) {
                        val = data[data.length - count + j];
                        x = x0 + pw * j / Math.max(1, root.maxPoints - 1);
                    } else {
                        val = level + (hi - lo) * 0.016 * root._noise(s, j, n);
                        x = x0 + pw * j / (n - 1);
                    }
                    var y = Math.max(top, Math.min(bottom, bottom - (val - lo) / (hi - lo) * ph));
                    if (j === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                }
                ctx.stroke();
            }
            // the legend
            if (legendW > 0) {
                var lx = x1 + 10, lh = root._lineH(legendPx);
                var rowH = Math.floor(Math.min(Math.round(lh * 2.1), ph / Math.max(1, S.length)));
                for (s = 0; s < S.length; ++s) {
                    var cy = top + rowH * s + Math.floor(rowH / 2);
                    ctx.fillStyle = S[s].colour;
                    ctx.fillRect(lx, cy - 2, swatch, 4);
                    text(S[s].label, legendPx, 400, Theme.foreground, lx + swatch + 8, cy - Math.floor(lh / 2),
                         legendW - swatch - 8, "left");
                }
            }
        }
    }

    Column {
        anchors.fill: parent
        spacing: 0
        visible: root._series.length === 0

        Text {
            visible: root.label !== ""
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXs
            font.weight: Theme.fontMedium
            color: Theme.mutedForeground
            elide: Text.ElideRight
        }

        Item {
            id: chartArea
            width: parent ? parent.width : root.implicitWidth
            height: root.implicitHeight - (root.label !== "" ? 18 : 0)
            clip: true

            Rectangle {
                anchors.fill: parent
                color: Theme.background
                border.color: Theme.border
                border.width: 1
                radius: Theme.radiusSm
            }

            // Warning zone background: warningLow..warningHigh, clipped to
            // the scale (its height was 1 - that share, which ran past the
            // chart's bottom edge).
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                height: Math.max(0, parent.height * (Math.min(root.warningHigh, root.maxValue)
                                                   - Math.max(root.warningLow, root.minValue)) * root._yScale)
                y: parent.height * (root.maxValue - Math.min(root.warningHigh, root.maxValue)) * root._yScale
                color: root._warnZoneColor
            }

            // Horizontal grid lines
            Repeater {
                model: 5
                delegate: Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    y: (index / 4) * parent.height
                    color: root._gridColor
                    opacity: 0.5
                }
            }

            // Y-axis labels
            Repeater {
                model: 5
                delegate: Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: (parent.height / 4) * (3 - index * 2)
                    text: Number(root.maxValue - (index / 4) * (root.maxValue - root.minValue)).toFixed(0)
                    font.family: Theme.fontFamily
                    font.pixelSize: 9
                    color: Theme.mutedForeground
                }
            }

            // Trend line path: faces/canvas/TrendChartFace.qml, or the C++
            // twin when the loader registered Shadcn.Native (Theme.nativeFaces).
            Loader {
                anchors.fill: parent
                anchors.margins: 2
                source: Theme.face("TrendChart")
                onLoaded: item.spec = Qt.binding(function() { return root._spec })
            }

            // Unit label
            Text {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 4
                text: root.unit
                font.family: Theme.fontFamily
                font.pixelSize: 9
                color: Theme.mutedForeground
                visible: root.unit !== ""
            }
        }
    }
    }
}
