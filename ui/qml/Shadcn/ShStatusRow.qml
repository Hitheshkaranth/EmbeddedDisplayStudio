/**
 * ShStatusRow.qml
 * Status row -- Industrial kit widget: one line of a "Key Status" list:
 *     (o) Main Drive                         [ RUNNING ]
 * a glossy lamp dot, the label (foreground) and a status badge at the right
 * whose colours follow ``state``: ok = Theme.success with dark text, warn =
 * Theme.warning with dark text, fault = Theme.destructive with white text,
 * idle = Theme.muted with mutedForeground text (its lamp mutedForeground).
 * The lamp is the state colour with a rim 35 % darker and a highlight 55 %
 * lighter up and to the left.
 *
 * Geometry (shared with native/hmi-ui/src/widgets/w_shstatusrow.c): lamp
 * clamp(round(0.55 h), 6, 18) at x round(0.15 h); the label after a gap of
 * max(6, round(0.6 h)), regular clamp(round(0.5 h), 8, 18), shrinking to 75 %
 * then eliding; the badge clamp(round(0.72 h), 10, 28) tall,
 * max(text + h, round(0.29 w)) wide (at most half the row), right-aligned,
 * radius 2, semibold clamp(round(0.6 badge), 7, 16), centred. Stacked rows
 * line their badges up.
 */
import QtQuick 2.15

Item {
    id: root
    implicitWidth: 280
    implicitHeight: 26

    property string label: "Main drive"
    property string status: "RUNNING"
    // `state` is Item's own property (QML states); the kit reuses the name
    // as ShStatDot does.
    property string state: "ok"

    readonly property color _fill: state === "ok" ? Theme.success : state === "warn" ? Theme.warning
                                 : state === "fault" ? Theme.destructive : Theme.muted
    readonly property color _lamp: state === "ok" || state === "warn" || state === "fault" ? _fill : Theme.mutedForeground
    readonly property color _ink: state === "ok" ? "#07130b" : state === "warn" ? "#1a1203"
                                : state === "fault" ? "#ffffff" : Theme.mutedForeground

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    function _clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, Math.round(v))) }
    function _lineH(px) { return Math.floor(px * 2478 / 2048) }
    function _asc(px) { return _lineH(px) - Math.floor(px * 494 / 2048) }
    readonly property int _d: _clamp(_h * 0.55, 6, 18)
    readonly property int _dx: Math.round(_h * 0.15)
    readonly property int _bh: _clamp(_h * 0.72, 10, 28)
    readonly property int _bpx: _clamp(_bh * 0.6, 7, 16)
    readonly property int _bw: root.status === "" ? 0
        : Math.min(Math.max(Math.ceil(badgeMetrics.advanceWidth) + _bh, Math.round(_w * 0.29)), Math.floor(Math.round(_w) / 2))
    readonly property int _bx: Math.round(_w) - _bw
    readonly property int _lpx: _clamp(_h * 0.5, 8, 18)
    readonly property int _lx: _dx + _d + Math.max(6, Math.round(_h * 0.6))
    readonly property int _lw: (_bw > 0 ? _bx - 6 : Math.round(_w)) - _lx

    TextMetrics { id: badgeMetrics; text: root.status; font.family: Theme.fontFamily; font.kerning: false
                  font.pixelSize: root._bpx; font.weight: Theme.fontSemibold }

    Rectangle {
        id: lamp
        x: root._dx
        y: Math.floor((Math.round(root._h) - root._d) / 2)
        width: root._d
        height: root._d
        radius: width / 2
        color: root._lamp
        border.color: Theme.shade(root._lamp, -35)
        border.width: root._d >= 10 ? 1 : 0
        Rectangle {
            width: Math.max(2, Math.round(root._d * 0.36))
            height: width
            radius: width / 2
            x: Math.round(root._d * 0.22)
            y: Math.round(root._d * 0.18)
            color: Theme.shade(root._lamp, 55)
            opacity: 200 / 255
        }
    }

    Text {
        visible: root._lw > 0 && root.label !== ""
        x: root._lx
        y: Math.floor((Math.round(root._h) - root._lineH(root._lpx)) / 2) + root._asc(root._lpx) - baselineOffset
        width: Math.max(1, root._lw)
        text: root.label
        color: Theme.foreground
        font.family: Theme.fontFamily; font.kerning: false
        font.pixelSize: root._lpx; font.weight: Theme.fontNormal
        fontSizeMode: Text.HorizontalFit
        minimumPixelSize: Math.max(8, Math.round(root._lpx * 0.75))
        elide: Text.ElideRight; maximumLineCount: 1
    }

    Rectangle {
        visible: root._bw > 0
        x: root._bx
        y: Math.floor((Math.round(root._h) - root._bh) / 2)
        width: root._bw
        height: root._bh
        radius: 2
        color: root._fill
        Text {
            x: 2
            y: Math.floor((root._bh - root._lineH(root._bpx)) / 2) + root._asc(root._bpx) - baselineOffset
            width: Math.max(1, root._bw - 4)
            text: root.status
            color: root._ink
            horizontalAlignment: Text.AlignHCenter
            font.family: Theme.fontFamily; font.kerning: false
            font.pixelSize: root._bpx; font.weight: Theme.fontSemibold
            fontSizeMode: Text.HorizontalFit
            minimumPixelSize: Math.max(8, Math.round(root._bpx * 0.75))
            elide: Text.ElideRight; maximumLineCount: 1
        }
    }
}
