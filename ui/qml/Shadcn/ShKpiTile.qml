/**
 * ShKpiTile.qml
 * KPI tile -- Industrial kit widget: one tile of a plant dashboard's KPI
 * strip:
 *     [icon]  Production Rate
 *             3,015 tpd
 *             Target 3,200 tpd                 94 %
 *     [=================================------]
 * a rounded tile (tileColor, "" = Theme.card; 1 px Theme.border), an
 * optional kit icon at the left (mutedForeground), the title (foreground,
 * medium), the value (valueColor, "" = Theme.foreground, bold) with the unit
 * beside it on the same baseline, the subtitle under them (muted), and a thin
 * rounded progress bar along the bottom (barColor, "" = Theme.success, on
 * Theme.muted) for progress 0..100; a negative progress hides it.
 * progressText sits right-aligned just above the bar's right end.
 *
 * ``value`` is a number or a string ("3,015"); ``decimals`` >= 0 formats a
 * number with toFixed, -1 shows it as given.
 *
 * Geometry (shared with native/hmi-ui/src/widgets/w_shkpitile.c): padX
 * clamp(round(0.05 w), 6, 14), padY clamp(round(0.10 h), 4, 12); bar
 * clamp(round(0.06 h), 3, 8) tall, padY above the bottom, a gap of
 * clamp(round(0.04 h), 2, 6) over it; the icon clamp(round(min(0.62 content,
 * 0.20 w)), 12, 56) at padX, centred in the content height; the text column
 * after it (gap max(8, round(0.06 w))). Fonts: title clamp(round(0.145 h), 8,
 * 18), value clamp(round(0.27 h), 10, 40), unit round(0.72 value), subtitle
 * clamp(round(0.125 h), 8, 15), scaled down together when their lines do
 * not fit; the lines share the spare height evenly between and around them.
 */
import QtQuick 2.15

Item {
    id: root
    implicitWidth: 250
    implicitHeight: 96

    property string icon: ""
    property string title: "KPI"
    property var value: 0
    property int decimals: -1
    property string unit: ""
    property string subtitle: ""
    property real progress: -1
    property string progressText: ""
    property string valueColor: ""
    property string barColor: ""
    property string tileColor: ""

    function _num(v) {
        if (typeof v === "number") return isFinite(v) ? v : NaN;
        if (typeof v === "string" && v.trim() !== "") {
            var n = Number(v);
            return isFinite(n) ? n : NaN;
        }
        return NaN;
    }
    readonly property string _text: {
        if (root.value === undefined || root.value === null) return "--";
        var n = _num(root.value);
        if (root.decimals >= 0 && !isNaN(n)) return n.toFixed(root.decimals);
        return String(root.value);
    }
    function _colour(c, fallback) { return c && c.charAt(0) === "#" ? c : fallback }

    // -- geometry ---------------------------------------------------------------
    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    function _clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, Math.round(v))) }
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }
    readonly property int _padX: _clamp(_w * 0.05, 6, 14)
    readonly property int _padY: _clamp(_h * 0.10, 4, 12)
    readonly property bool _bar: root.progress >= 0
    readonly property int _barH: _clamp(_h * 0.06, 3, 8)
    readonly property int _barY: Math.round(_h) - _padY - _barH
    readonly property int _top: _padY
    readonly property int _bottom: _bar ? _barY - _clamp(_h * 0.04, 2, 6) : Math.round(_h) - _padY
    readonly property int _contentH: Math.max(1, _bottom - _top)
    readonly property bool _hasIcon: root.icon !== ""
    readonly property int _iconSz: _hasIcon ? _clamp(Math.min(_contentH * 0.62, _w * 0.20), 12, 56) : 0
    readonly property int _textX: _hasIcon ? _padX + _iconSz + Math.max(8, Math.round(_w * 0.06)) : _padX
    readonly property int _textW: Math.max(1, Math.round(_w) - _padX - _textX)
    readonly property bool _hasTitle: root.title !== ""
    readonly property bool _hasSub: root.subtitle !== ""

    // [title, value, subtitle] px, scaled down together until the lines fit.
    readonly property var _fonts: {
        var t = _clamp(_h * 0.145, 8, 18), v = _clamp(_h * 0.27, 10, 40), s = _clamp(_h * 0.125, 8, 15);
        for (var g = 0; g < 40; ++g) {
            var stack = (_hasTitle ? _lineH(t) : 0) + _lineH(v) + (_hasSub ? _lineH(s) : 0);
            if (stack <= _contentH || (t <= 8 && v <= 10 && s <= 8)) break;
            if (v > 10) --v;
            if (g % 2 === 0 && t > 8) --t;
            if (g % 2 === 0 && s > 8) --s;
        }
        return [t, v, s];
    }
    readonly property int _titlePx: _fonts[0]
    readonly property int _valuePx: _fonts[1]
    readonly property int _subPx: _fonts[2]
    readonly property int _unitPx: Math.max(8, Math.round(_valuePx * 0.72))
    readonly property int _stack: (_hasTitle ? _lineH(_titlePx) : 0) + _lineH(_valuePx) + (_hasSub ? _lineH(_subPx) : 0)
    readonly property real _gap: Math.max(0, (_contentH - _stack) / (1 + (_hasTitle ? 1 : 0) + (_hasSub ? 1 : 0) + 1))
    readonly property int _titleTop: Math.round(_top + _gap)
    readonly property int _valueTop: Math.round(_top + _gap + (_hasTitle ? _lineH(_titlePx) + _gap : 0))
    readonly property int _subTop: _hasSub
        ? Math.round(_top + _gap + (_hasTitle ? _lineH(_titlePx) + _gap : 0) + _lineH(_valuePx) + _gap)
        : _bottom - _lineH(_subPx)
    readonly property bool _hasUnit: root.unit !== ""
    readonly property int _unitGap: _hasUnit ? Math.max(3, Math.round(_valuePx * 0.22)) : 0
    readonly property int _unitW: _hasUnit ? Math.min(Math.ceil(unitMetrics.advanceWidth) + 1, Math.floor(_textW / 2)) : 0
    readonly property int _valueSlot: Math.max(1, _textW - _unitGap - _unitW)
    readonly property int _pTextW: root.progressText !== ""
        ? Math.min(Math.ceil(pMetrics.advanceWidth) + 2, Math.round(_w) - 2 * _padX) : 0

    TextMetrics { id: unitMetrics; text: root.unit; font.family: Theme.fontFamily; font.kerning: false
                  font.pixelSize: root._unitPx; font.weight: Theme.fontNormal }
    TextMetrics { id: pMetrics; text: root.progressText; font.family: Theme.fontFamily; font.kerning: false
                  font.pixelSize: root._subPx; font.weight: Theme.fontMedium }

    Rectangle {
        anchors.fill: parent
        radius: Theme.radiusSm
        color: root._colour(root.tileColor, Theme.card)
        border.color: Theme.border
        border.width: 1
    }

    ShIcon {
        visible: root._hasIcon
        x: root._padX
        y: root._top + Math.floor((root._contentH - root._iconSz) / 2)
        name: root.icon
        size: root._iconSz
        color: Theme.mutedForeground
    }

    Text {
        visible: root._hasTitle
        x: root._textX
        y: root._titleTop + root._asc(root._titlePx) - baselineOffset
        width: root._textW
        text: root.title
        color: Theme.foreground
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._titlePx; font.weight: Theme.fontMedium
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._titlePx * 0.75))
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Text {
        id: valueText
        x: root._textX
        y: root._valueTop + root._asc(root._valuePx) - baselineOffset
        width: root._valueSlot
        text: root._text
        color: root._colour(root.valueColor, Theme.foreground)
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._valuePx; font.weight: 700
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._valuePx * 0.6))
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Text {
        visible: root._hasUnit
        x: root._textX + Math.min(Math.ceil(valueText.contentWidth), root._valueSlot) + root._unitGap
        // on the value's nominal baseline
        y: root._valueTop + root._asc(root._valuePx) - baselineOffset
        width: Math.max(1, root._unitW)
        text: root.unit
        color: root._colour(root.valueColor, Theme.foreground)
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._unitPx; font.weight: Theme.fontNormal
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._unitPx * 0.75))
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Text {
        visible: root._hasSub
        x: root._textX
        y: root._subTop + root._asc(root._subPx) - baselineOffset
        width: Math.max(1, root._textW - (root._pTextW > 0 ? root._pTextW + 6 : 0))
        text: root.subtitle
        color: Theme.mutedForeground
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._subPx; font.weight: Theme.fontNormal
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._subPx * 0.75))
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Text {
        visible: root.progressText !== ""
        x: Math.round(root._w) - root._padX - root._pTextW
        y: root._subTop + root._asc(root._subPx) - baselineOffset
        width: Math.max(1, root._pTextW)
        text: root.progressText
        color: Theme.foreground
        horizontalAlignment: Text.AlignRight
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._subPx; font.weight: Theme.fontMedium
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Rectangle {
        id: track
        visible: root._bar
        x: root._padX
        y: root._barY
        width: Math.max(1, Math.round(root._w) - 2 * root._padX)
        height: root._barH
        radius: height / 2
        color: Theme.muted
        Rectangle {
            width: Math.round(track.width * Math.min(100, Math.max(0, root.progress)) / 100)
            height: parent.height
            radius: height / 2
            visible: width > 0
            color: root._colour(root.barColor, Theme.success)
        }
    }
}
