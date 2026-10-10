/**
 * ShProcessValue.qml
 * Process value -- Industrial kit widget: one SCADA reading row, as on a
 * plant overview's side cards:
 *     Hot Blast Temp   [~sparkline~] [   1185 ] °C
 * the label at the left (foreground, elided), an optional sparkline of the
 * recent values on a dark mini-box (trend), a dark inset value box with the
 * bright digits right-aligned in it (valueColor; Theme.warning beyond
 * warnAbove / warnBelow, 0 = off), and the unit column at the right (muted;
 * collapses when the unit is empty).
 *
 * ``value`` is a number or a string ("76,600"). ``decimals`` >= 0 formats a
 * number (or a numeric string) with toFixed; -1 shows it as given.
 *
 * Geometry (shared with native/hmi-ui/src/widgets/w_shprocessvalue.c):
 * unit column round(0.22 w) after a 6 px gap; value box
 * max(digits + 2 x 8, round(0.26 w)) wide, inset round(0.08 h) top and
 * bottom; sparkline box round(0.18 w) with 6 px gaps; the label takes the
 * rest. The columns are fixed shares of the width so stacked rows line their
 * boxes up. Each text sits on the baseline of a line slot centred in the row,
 * laid out as the native face does (Inter hhea 1984/-494 of 2048, truncated
 * like LVGL's tiny_ttf), and shrinks to fit (the label to 70 %, the digits
 * and the unit to 60 %) before it elides.
 *
 * bevel (off by default) draws the value box and the sparkline box inset: a
 * 1 px line in the box colour darker by 70 % along the top and one lighter by
 * 20 % along the bottom, inside the border and clear of its rounded corners.
 */
import QtQuick 2.15

Item {
    id: root
    implicitWidth: 260
    implicitHeight: 30

    property string label: "Value"
    property var value: 0
    property int decimals: -1
    property string unit: ""
    property color valueColor: "#3ee05a"
    property color boxColor: "#0a0d0b"
    property bool trend: false
    property bool bevel: false
    property color trendColor: "#f5a524"
    property real warnAbove: 0.0
    property real warnBelow: 0.0

    // -- the reading ------------------------------------------------------------
    // A number, or a string that is one ("1185", " 12.5"); NaN otherwise.
    function _num(v) {
        if (typeof v === "number") return isFinite(v) ? v : NaN;
        if (typeof v === "string" && v.trim() !== "") {
            var n = Number(v);
            return isFinite(n) ? n : NaN;
        }
        return NaN;
    }
    readonly property real _n: _num(root.value)
    readonly property string _text: {
        if (root.value === undefined || root.value === null) return "--";
        if (root.decimals >= 0 && !isNaN(root._n)) return root._n.toFixed(root.decimals);
        return String(root.value);
    }
    readonly property bool _warns: !isNaN(_n) && ((root.warnAbove !== 0 && _n > root.warnAbove)
                                                 || (root.warnBelow !== 0 && _n < root.warnBelow))

    // The last 32 numeric values, for the sparkline. The value the page was
    // built with is not history; every later numeric update is.
    // (A var property's declared value is assigned over the default during
    // creation and does notify, so history starts once the item is complete.)
    property var _history: []
    property bool _live: false
    Component.onCompleted: _live = true
    onValueChanged: {
        if (!root._live || isNaN(root._n)) return;
        var h = root._history.slice();
        h.push(root._n);
        if (h.length > 32) h.splice(0, h.length - 32);
        root._history = h;
        spark.requestPaint();
    }

    // -- geometry -----------------------------------------------------------------
    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }
    readonly property int _valuePx: Math.max(9, Math.min(18, Math.round(_h * 0.56)))
    readonly property int _labelPx: Math.max(8, Math.min(15, Math.round(_h * 0.46)))
    readonly property int _unitPx: Math.max(8, Math.min(14, Math.round(_h * 0.42)))
    readonly property int _inset: Math.max(1, Math.round(_h * 0.08))
    readonly property int _boxH: Math.max(6, Math.round(_h) - 2 * _inset)
    readonly property int _unitW: root.unit !== "" ? Math.round(_w * 0.22) : 0
    readonly property int _unitGap: root.unit !== "" ? 6 : 0
    readonly property int _digitsW: Math.ceil(digitsMetrics.advanceWidth)
    readonly property int _boxW: Math.min(Math.max(_digitsW + 16, Math.round(_w * 0.26)),
                                          Math.max(16, Math.round(_w) - _unitW - _unitGap))
    readonly property int _boxX: Math.round(_w) - _unitW - _unitGap - _boxW
    readonly property int _sparkW: root.trend ? Math.round(_w * 0.18) : 0
    readonly property int _sparkX: _boxX - 6 - _sparkW
    readonly property int _labelW: Math.max(0, (root.trend ? _sparkX : _boxX) - 6)
    function _slotTop(px) { return Math.round((_h - _lineH(px)) / 2) }

    TextMetrics {
        id: digitsMetrics
        text: root._text
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._valuePx
        font.weight: Theme.fontSemibold
    }

    Text {
        id: labelText
        x: 0
        y: root._slotTop(root._labelPx) + root._asc(root._labelPx) - baselineOffset
        width: root._labelW
        visible: root._labelW > 0
        text: root.label
        color: Theme.foreground
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._labelPx
        font.weight: Theme.fontNormal
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._labelPx * 0.7))
        elide: Text.ElideRight
        maximumLineCount: 1
    }

    // The sparkline, on a mini-box like the value box.
    Rectangle {
        id: sparkBox
        visible: root.trend
        x: root._sparkX
        y: root._inset
        width: root._sparkW
        height: root._boxH
        radius: 3
        color: root.boxColor
        border.color: "#3a3f45"
        border.width: 1

        ShProcessBevel { visible: root.bevel; fill: root.boxColor }

        Canvas {
            id: spark
            anchors.fill: parent
            antialiasing: true
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                // Before live data: a gentle rising zigzag, so a design shows
                // a sparkline. One live point is a flat line.
                var pts = root._history;
                var ys = [];
                if (pts.length === 0) {
                    ys = [0.30, 0.52, 0.40, 0.62, 0.48, 0.70, 0.58, 0.80];
                } else {
                    var lo = pts[0], hi = pts[0];
                    for (var i = 1; i < pts.length; ++i) { lo = Math.min(lo, pts[i]); hi = Math.max(hi, pts[i]); }
                    for (var j = 0; j < pts.length; ++j) ys.push(hi - lo > 1e-9 ? (pts[j] - lo) / (hi - lo) : 0.5);
                    if (ys.length === 1) ys.push(ys[0]);
                }
                var padX = 4, padY = Math.max(3, Math.round(height * 0.16));
                var pw = width - 2 * padX, ph = height - 2 * padY;
                if (pw <= 0 || ph <= 0) return;
                ctx.strokeStyle = root.trendColor;
                ctx.lineWidth = 2;
                ctx.lineCap = "round";
                ctx.lineJoin = "round";
                ctx.beginPath();
                for (var k = 0; k < ys.length; ++k) {
                    var px = padX + pw * k / (ys.length - 1);
                    var py = padY + ph * (1 - ys[k]);
                    if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
                }
                ctx.stroke();
            }
        }
    }
    onTrendColorChanged: spark.requestPaint()
    onTrendChanged: spark.requestPaint()

    // The value box: near-black, a 1 px border a little lighter than a card.
    Rectangle {
        id: box
        x: root._boxX
        y: root._inset
        width: root._boxW
        height: root._boxH
        radius: 3
        color: root.boxColor
        border.color: "#3a3f45"
        border.width: 1

        ShProcessBevel { visible: root.bevel; fill: root.boxColor }
    }

    Text {
        id: valueText
        // Ends 8 px inside the box; the slot starts 4 px in (as on the panel).
        x: root._boxX + 4
        y: root._slotTop(root._valuePx) + root._asc(root._valuePx) - baselineOffset
        width: Math.max(1, root._boxW - 12)
        text: root._text
        color: root._warns ? Theme.warning : root.valueColor
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._valuePx
        font.weight: Theme.fontSemibold
        horizontalAlignment: Text.AlignRight
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._valuePx * 0.6))
        elide: Text.ElideRight
        maximumLineCount: 1
    }

    Text {
        id: unitText
        visible: root.unit !== ""
        x: root._boxX + root._boxW + root._unitGap
        y: root._slotTop(root._unitPx) + root._asc(root._unitPx) - baselineOffset
        width: Math.max(1, root._unitW)
        text: root.unit
        color: Theme.mutedForeground
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._unitPx
        font.weight: Theme.fontNormal
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._unitPx * 0.6))
        elide: Text.ElideRight
        maximumLineCount: 1
    }

    // The inset bevel of a box: two 1 px lines inside its border.
    component ShProcessBevel: Item {
        property color fill
        anchors.fill: parent
        Rectangle {
            x: 2; y: 1; width: parent.width - 4; height: 1
            visible: parent.width >= 6 && parent.height >= 4
            color: Theme.shade(parent.fill, -70)
        }
        Rectangle {
            x: 2; y: parent.height - 2; width: parent.width - 4; height: 1
            visible: parent.width >= 6 && parent.height >= 4
            color: Theme.shade(parent.fill, 20)
        }
    }
}
