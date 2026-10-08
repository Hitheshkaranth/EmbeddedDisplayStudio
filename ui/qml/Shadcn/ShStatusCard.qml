/**
 * ShStatusCard.qml
 * Status Card -- Rail kit widget: a cab-display subsystem card (HVAC,
 * PA SYSTEM, PEA ...). A rounded dark card with the subsystem icon
 * top-left in ``iconColor``, a glowing state dot top-right, and at the
 * bottom the title (up to two lines -- a second line is drawn smaller and
 * muted, e.g. "PEA\n(Emergency Alarm)") over the status, bold and coloured
 * by ``state`` (ok green, warn amber, fault red, idle grey).
 * Scales with s = min(width/240, height/180); long text shrinks (to 60 %)
 * and then elides. Mirrors native/hmi-ui/src/widgets/w_shstatuscard.c.
 */
import QtQuick 2.15

Item {
    id: root
    implicitWidth: 240
    implicitHeight: 180

    property string icon: 'snowflake'
    property string title: 'HVAC:'
    property string status: 'ACTIVE (21°C)'
    property string state: 'ok'
    property string iconColor: '#38bdf8'

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    readonly property real _s: Math.min(_w / 240, _h / 180)
    readonly property int _pad: Math.max(4, Math.round(20 * _s))
    readonly property int _iconSize: Math.max(8, Math.round(44 * _s))
    readonly property real _dotR: Math.max(2, 7 * _s)
    readonly property real _haloR: _dotR * 1.9
    readonly property real _dotCx: _w - _pad - _dotR
    readonly property real _dotCy: Math.max(_pad * 0.5 + _haloR, 18 * _s + _iconSize / 2 - 8 * _s)
    readonly property var _lines: {
        var t = String(root.title).replace(/\\n/g, "\n").split("\n");
        return [t[0] || "", t.length > 1 ? t[1] : ""];
    }
    readonly property color _dotColor: root.state === "warn" ? "#f59e0b"
                                     : root.state === "fault" ? "#ef4444"
                                     : root.state === "idle" ? "#52525b" : "#4ade80"
    readonly property color _statusColor: root.state === "idle" ? "#a1a1aa" : _dotColor
    readonly property int _textWidth: Math.max(10, _w - 2 * _pad)

    Rectangle {
        anchors.fill: parent
        radius: Math.round(16 * root._s)
        color: "#26262c"
        border.color: "#3a3a44"
        border.width: 1
    }

    ShIcon {
        x: root._pad
        y: Math.round(18 * root._s)
        name: root.icon
        size: root._iconSize
        color: root.iconColor !== "" && root.iconColor.charAt(0) === "#" ? root.iconColor : "#38bdf8"
    }

    Rectangle {
        x: Math.round(root._dotCx - root._haloR)
        y: Math.round(root._dotCy - root._haloR)
        width: Math.round(2 * root._haloR)
        height: width
        radius: width / 2
        color: root._dotColor
        opacity: 0.22
    }
    Rectangle {
        x: Math.round(root._dotCx - root._dotR)
        y: Math.round(root._dotCy - root._dotR)
        width: Math.round(2 * root._dotR)
        height: width
        radius: width / 2
        color: root._dotColor
    }

    // Line slots as the native face lays them out (Inter hhea 1984/-494 of
    // 2048, truncated like LVGL's tiny_ttf): each line sits by its baseline.
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }
    readonly property int _statusPx: Math.max(8, Math.round(28 * _s))
    readonly property int _titlePx: Math.max(8, Math.round(24 * _s))
    readonly property int _subPx: Math.max(7, Math.round(16 * _s))
    readonly property int _gap: Math.round(2 * _s)
    readonly property int _statusTop: _h - _pad - _lineH(_statusPx) + _gap
    readonly property int _subTop: _statusTop - _gap - _lineH(_subPx)
    readonly property int _titleTop: (_lines[1] !== "" ? _subTop : _statusTop - _gap) - _lineH(_titlePx)

    Text {
        x: root._pad
        y: root._statusTop + root._asc(root._statusPx) - baselineOffset
        width: root._textWidth
        text: root.status
        color: root._statusColor
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._statusPx
        font.weight: Font.Bold
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._statusPx * 0.6))
        elide: Text.ElideRight
        maximumLineCount: 1
    }

    Text {
        x: root._pad
        y: root._subTop + root._asc(root._subPx) - baselineOffset
        width: root._textWidth
        visible: root._lines[1] !== ""
        text: root._lines[1]
        color: "#a1a1aa"
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._subPx
        font.weight: Font.Medium
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._subPx * 0.6))
        elide: Text.ElideRight
        maximumLineCount: 1
    }

    Text {
        x: root._pad
        y: root._titleTop + root._asc(root._titlePx) - baselineOffset
        width: root._textWidth
        text: root._lines[0]
        color: "#fafafa"
        font.family: Theme.fontFamily
        font.kerning: false
        font.pixelSize: root._titlePx
        font.weight: Font.Medium
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._titlePx * 0.6))
        elide: Text.ElideRight
        maximumLineCount: 1
    }
}
