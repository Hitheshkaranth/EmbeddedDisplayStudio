/**
 * ShStationLine.qml
 * Station Line -- Rail widget. A vertical route timeline for a metro cab:
 * the stations (comma-separated `stations`, up to 8) sit at even steps from
 * 0.09 h to 0.84 h on a 4 px line at x = 0.14 w, grey above the current
 * station and `accent` from it down, with a faint grey stub above the first
 * node. Passed stations get a small grey dot and dim text; the current one a
 * glowing accent ring holding the train icon, its name bold white and its
 * subtitle (the train number) in accent; the ones ahead an accent dot, the
 * terminus a hollow accent ring. Subtitles come from `details`, matched by
 * position. Names start at x = 0.24 w and wrap to at most two lines.
 * Mirrors native/hmi-ui/src/widgets/w_shstationline.c.
 */
import QtQuick 2.15

Item {
    id: root

    property string stations: 'Attiguppe,Vijayanagar,Hosahalli,Magadi Road,KSR Bengaluru'
    property string details: 'COMPLETED,P-412,NEXT · 1.1 km,UPCOMING · 2.3 km,Majestic'
    property int current: 1
    property string accent: '#a855f7'

    implicitWidth: 520
    implicitHeight: 680

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    readonly property real _k: Math.min(_w / 520, _h / 680)
    readonly property var _names: {
        var out = []
        var parts = String(root.stations).split(",")
        for (var i = 0; i < parts.length && out.length < 8; ++i) {
            var s = parts[i].trim()
            if (s !== "") out.push(s)
        }
        return out
    }
    readonly property var _subs: {
        var parts = String(root.details).split(",")
        var out = []
        for (var i = 0; i < parts.length && i < 8; ++i) out.push(parts[i].trim())
        return out
    }
    readonly property int _n: _names.length
    readonly property int _last: _n - 1

    readonly property int _lineX: Math.round(_w * 0.14)
    readonly property int _lineW: Math.max(2, Math.round(4 * _k))
    readonly property int _top: Math.round(_h * 0.09)
    readonly property int _bottom: Math.round(_h * 0.84)
    readonly property int _textX: Math.round(_w * 0.24)
    readonly property int _textW: Math.max(10, Math.round(_w - _textX - _w * 0.04))
    readonly property int _nameFs: Math.max(8, Math.round(34 * _k))
    readonly property int _subFs: Math.max(7, Math.round(22 * _k))
    readonly property int _nameLineH: Math.round(_nameFs * 1.21)
    readonly property int _gap: Math.round(2 * _k)
    readonly property int _dotR: Math.max(3, Math.round(13 * _k))
    readonly property int _ringR: Math.max(6, Math.round(38 * _k))
    readonly property int _ringW: Math.max(2, Math.round(4 * _k))
    readonly property int _termR: Math.max(4, Math.round(16 * _k))
    readonly property int _iconSz: Math.max(6, Math.round(36 * _k))
    readonly property int _stub: Math.round(_h * 0.06)

    function _nodeY(i) {
        return _n > 1 ? Math.round(_top + i * (_bottom - _top) / (_n - 1)) : _top
    }
    readonly property int _splitY: current <= 0 ? _nodeY(0) : (current >= _last ? _nodeY(_last) : _nodeY(current))

    // the line: a faint stub above the first node, grey to the train, accent after it
    Rectangle {
        visible: root._n > 0
        x: root._lineX - Math.floor(root._lineW / 2); y: root._nodeY(0) - root._stub
        width: root._lineW; height: root._stub
        color: "#3f3f46"; opacity: 0.5
    }
    Rectangle {
        visible: root._n > 1
        x: root._lineX - Math.floor(root._lineW / 2); y: root._nodeY(0)
        width: root._lineW; height: root._splitY - root._nodeY(0)
        color: "#3f3f46"
    }
    Rectangle {
        visible: root._n > 1
        x: root._lineX - Math.floor(root._lineW / 2); y: root._splitY
        width: root._lineW; height: root._nodeY(root._last) - root._splitY
        color: root.accent
    }

    Repeater {
        model: root._n
        delegate: Item {
            id: station
            readonly property int cy: root._nodeY(index)
            readonly property bool passed: index < root.current
            readonly property bool here: index === root.current
            readonly property bool terminus: index === root._last && index > root.current

            // passed / ahead: a solid dot
            Rectangle {
                visible: !station.here && !station.terminus
                x: root._lineX - root._dotR; y: station.cy - root._dotR
                width: 2 * root._dotR; height: width; radius: root._dotR
                color: station.passed ? "#52525b" : root.accent
            }
            // terminus: a hollow ring
            Rectangle {
                visible: station.terminus
                x: root._lineX - root._termR; y: station.cy - root._termR
                width: 2 * root._termR; height: width; radius: root._termR
                color: "#18181b"; border.color: root.accent; border.width: root._ringW
            }
            // the train: a glow, a dark disc ringed in accent, the icon
            Repeater {
                model: station.here ? [[22, 0.07], [14, 0.10], [7, 0.16]] : []
                delegate: Rectangle {
                    readonly property int r: root._ringR + Math.round(modelData[0] * root._k)
                    x: root._lineX - r; y: station.cy - r
                    width: 2 * r; height: width; radius: r
                    color: root.accent; opacity: modelData[1]
                }
            }
            Rectangle {
                visible: station.here
                x: root._lineX - root._ringR; y: station.cy - root._ringR
                width: 2 * root._ringR; height: width; radius: root._ringR
                color: "#18181b"; border.color: root.accent; border.width: root._ringW
            }
            ShIcon {
                visible: station.here
                x: root._lineX - Math.floor(root._iconSz / 2); y: station.cy - Math.floor(root._iconSz / 2)
                name: "train"; size: root._iconSz; color: "#fafafa"
            }

            Text {
                id: nameText
                x: root._textX; y: station.cy - Math.round(root._nameFs * 0.6)
                width: root._textW
                text: root._names[index]
                color: station.passed ? "#71717a" : "#fafafa"
                font.family: Theme.fontFamily
                font.pixelSize: root._nameFs
                font.weight: station.here ? Font.Bold : Font.DemiBold
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                lineHeightMode: Text.FixedHeight
                lineHeight: root._nameLineH
            }
            Text {
                x: root._textX
                y: nameText.y + Math.min(2, Math.max(1, nameText.lineCount)) * root._nameLineH + root._gap
                width: root._textW
                text: index < root._subs.length ? root._subs[index] : ""
                visible: text !== ""
                color: station.passed ? "#71717a" : (station.here ? root.accent : "#a1a1aa")
                font.family: Theme.fontFamily
                font.pixelSize: root._subFs
                elide: Text.ElideRight
            }
        }
    }
}
