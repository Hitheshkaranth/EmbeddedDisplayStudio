/**
 * ShTractionBar.qml
 * Traction / Brake -- Rail cab widget. The metro cab's T/B indicator: the
 * title on top, an upper track that fills from its bottom in green while
 * value > 0 (traction / propulsion %), the signed percent and the mode word
 * between the tracks, and a lower track that fills from its top in amber
 * while value < 0 (braking %; a faint amber hint while idle). The side
 * labels are written bottom-to-top beside each track.
 *
 * The Qt-free twin is native/hmi-ui/src/widgets/w_shtractionbar.c and the
 * Designer painter designer/canvas/rail/traction_bar.py; keep the geometry
 * (fractions of width / height below) and colours in step.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 30.0
    property string title: 'T/B'
    property string powerLabel: 'POWER'
    property string brakeLabel: 'BRAKING'
    property string propulsionText: 'Propulsion'
    property string brakingText: 'Braking'

    implicitWidth: 140
    implicitHeight: 640

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    // Tracks: x 38 % of the width, 50 % wide; each 36 % of the height.
    readonly property real _tx: _w * 0.38
    readonly property real _tw: _w * 0.50
    readonly property real _th: _h * 0.36
    readonly property real _upTop: _h * 0.075
    readonly property real _lowTop: _h * 0.565
    readonly property real _radius: Math.min(_tw * 0.16, 12)
    readonly property real _ir: Math.max(0, _radius - 1)
    readonly property real _upBottom: _upTop + _th
    readonly property real _lowBottom: _lowTop + _th
    readonly property real _gap: _lowTop - _upBottom
    readonly property real _power: Math.max(0, Math.min(100, value)) / 100
    readonly property real _brake: Math.max(0, Math.min(100, -value)) / 100
    readonly property int _pct: Math.round(Math.min(100, Math.abs(value)))
    readonly property int _mode: _pct > 0 ? (value > 0 ? 1 : -1) : 0
    readonly property color _green: "#4ade80"
    readonly property color _amber: "#f59e0b"
    readonly property color _light: "#d4d4d8"
    readonly property real _fillTop: _upBottom - 1 - (_th - 2) * _power
    readonly property real _fillBottom: _lowTop + 1 + (_th - 2) * _brake

    // -- upper track: traction ------------------------------------------------
    Rectangle {
        x: root._tx; y: root._upTop; width: root._tw; height: root._th
        radius: root._radius
        color: "#0f1a12"
        border.color: "#1f3a26"; border.width: 1
    }
    Item {
        // the fill, clipped to the rows below the level
        visible: root._power > 0
        x: root._tx + 1; y: root._fillTop
        width: root._tw - 2; height: Math.max(0, root._upBottom - 1 - root._fillTop)
        clip: true
        Rectangle {
            readonly property real _gy: Math.max(root._upTop + 1, root._fillTop - root._ir)
            y: _gy - root._fillTop
            width: parent.width; height: root._upBottom - 1 - _gy
            radius: root._ir
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#166534" }
                GradientStop { position: 1.0; color: "#4ade80" }
            }
        }
    }
    Rectangle {
        // the level mark, only where the track is straight
        readonly property real _ly: root._fillTop - 1.5
        visible: root._power > 0 && _ly >= root._upTop + root._ir && _ly + 3 <= root._upBottom - root._ir
        x: root._tx + 1; y: _ly; width: root._tw - 2; height: 3
        color: "#bef264"
    }

    // -- lower track: braking -------------------------------------------------
    Rectangle {
        x: root._tx; y: root._lowTop; width: root._tw; height: root._th
        radius: root._radius
        color: "#1a140a"
        border.color: "#3a2a10"; border.width: 1
    }
    Rectangle {
        // the idle hint: a faint amber wash
        visible: root._brake <= 0
        x: root._tx + 1; y: root._lowTop + 1; width: root._tw - 2; height: root._th - 2
        radius: root._ir
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0.961, 0.620, 0.043, 0.16) }
            GradientStop { position: 1.0; color: Qt.rgba(0.573, 0.251, 0.055, 0.03) }
        }
    }
    Item {
        visible: root._brake > 0
        x: root._tx + 1; y: root._lowTop + 1
        width: root._tw - 2; height: Math.max(0, root._fillBottom - root._lowTop - 1)
        clip: true
        Rectangle {
            width: parent.width
            height: Math.min(root._lowBottom - 1, root._fillBottom + root._ir) - root._lowTop - 1
            radius: root._ir
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#f59e0b" }
                GradientStop { position: 1.0; color: "#92400e" }
            }
        }
    }
    Rectangle {
        readonly property real _ly: root._fillBottom - 1.5
        visible: root._brake > 0 && _ly >= root._lowTop + root._ir && _ly + 3 <= root._lowBottom - root._ir
        x: root._tx + 1; y: _ly; width: root._tw - 2; height: 3
        color: "#fcd34d"
    }

    // -- labels -----------------------------------------------------------------
    Text {
        text: root.title
        color: root._light
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(8, Math.round(Math.min(root._w * 0.21, root._h * 0.047)))
        font.weight: Font.DemiBold
        x: root._tx + root._tw / 2 - width / 2
        y: root._upTop / 2 - height / 2
    }
    Text {
        text: root._mode > 0 ? "+" + root._pct + "%" : root._mode < 0 ? "-" + root._pct + "%" : "0%"
        color: root._mode > 0 ? root._green : root._mode < 0 ? root._amber : "#a1a1aa"
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(10, Math.round(Math.min(root._w * 0.26, root._h * 0.056)))
        font.weight: Font.Bold
        x: root._w / 2 - width / 2
        y: root._upBottom + root._gap * 0.36 - height / 2
    }
    Text {
        text: root._mode > 0 ? root.propulsionText : root._mode < 0 ? root.brakingText : "Coast"
        color: root._light
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(Math.min(root._w * 0.13, root._h * 0.028)))
        font.weight: Font.Medium
        x: root._w / 2 - width / 2
        y: root._upBottom + root._gap * 0.76 - height / 2
    }
    Text {
        // read bottom-to-top beside the upper track
        text: root.powerLabel
        color: root._green
        rotation: -90
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(Math.min(root._w * 0.115, root._h * 0.025)))
        font.weight: Font.DemiBold
        font.letterSpacing: 1
        x: root._tx * 0.55 - width / 2
        y: root._upTop + root._th / 2 - height / 2
    }
    Text {
        text: root.brakeLabel
        color: root._amber
        rotation: -90
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(Math.min(root._w * 0.115, root._h * 0.025)))
        font.weight: Font.DemiBold
        font.letterSpacing: 1
        x: root._tx * 0.55 - width / 2
        y: root._lowTop + root._th / 2 - height / 2
    }
}
