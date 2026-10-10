/**
 * ShGlow.qml
 * The kit's soft outer glow (ShButton glowColor, ShAnnunciator glow), for
 * QtQuick 2.15 without QtQuick.Effects: rounded rings stacked behind the
 * item, each one pixel larger than the last, whose opacities add up to the
 * fall-off in `profile` -- the glow's coverage 1, 2, ... px outside the edge.
 *
 *     ShGlow { anchors.fill: parent; color: "#22c55e"; radius: 12 }
 *
 * Place it before the item it surrounds (it draws under it). The profile is
 * the one hmi-ui's LVGL box shadow draws for the same glow (draw_util.h
 * hmi_set_glow: blur 16 px, spread 2, opa 255), measured off its render, so
 * the two kits glow alike: ~8 px, from a little over half the colour at the
 * edge to nothing.
 */
import QtQuick 2.15

Item {
    id: root
    property color color: "transparent"
    property real radius: 0
    property var profile: [0.55, 0.43, 0.32, 0.23, 0.15, 0.089, 0.042, 0.010]

    readonly property int _reach: profile.length
    function _target(d) { return d >= 1 && d <= _reach ? profile[d - 1] : 0 }
    // Ring d covers everything up to d px out and is drawn over rings
    // d+1 .. reach, so its own opacity is what takes their combined coverage
    // to the profile at distance d.
    function _ringOpacity(d) {
        return Math.max(0, 1 - (1 - _target(d)) / (1 - _target(d + 1)));
    }

    Repeater {
        model: root.color.a > 0 ? root._reach : 0
        Rectangle {
            // Outermost first, so each nearer ring draws over the farther ones.
            readonly property int d: root._reach - index
            anchors.fill: parent
            anchors.margins: -d
            radius: root.radius > 0 ? root.radius + d : 0
            color: root.color
            opacity: root._ringOpacity(d)
        }
    }
}
