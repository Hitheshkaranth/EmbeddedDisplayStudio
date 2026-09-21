/**
 * ShAutoLevel.qml
 * Level Bar -- Automotive cluster widget. The vertical fuel / coolant bar
 * of a cluster: a gently curved track filled from the bottom in the blue
 * accent gradient, a red zone at the empty or hot end that stays visible
 * (and turns the fill red inside it), F / 1/2 / E style labels down the
 * left, and a line icon under the bar.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 55.0
    property real minimumValue: 0.0
    property real maximumValue: 100.0
    property string topLabel: "F"
    property string midLabel: "1/2"
    property string bottomLabel: "E"
    property string redZone: "low"
    property real redZoneSpan: 12.0
    property string icon: "gas-station"
    property bool curved: true
    property bool showTicks: true

    implicitWidth: 90
    implicitHeight: 220

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    readonly property real _span: Math.max(0.0001, root.maximumValue - root.minimumValue)
    readonly property real _fraction: Math.max(0, Math.min(1,
        (root.value - root.minimumValue) / root._span))
    // The bar: right 45 % of the width, top 80 % of the height.
    readonly property real _barX: root._w * 0.55 + (root._w * 0.45 - root._w * 0.22) / 2
    readonly property real _barW: root._w * 0.22
    readonly property real _barTop: root._h * 0.02
    readonly property real _barH: root._h * 0.78
    readonly property real _bulge: root.curved ? root._w * 0.18 : 0

    // Everything the face painter needs, geometry and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        fraction: root._fraction, redZone: root.redZone, redZoneSpan: root.redZoneSpan,
        showTicks: root.showTicks,
        barX: root._barX, barW: root._barW, barTop: root._barTop, barH: root._barH,
        bulge: root._bulge, tickMajor: root._w * 0.12, tickMinor: root._w * 0.06,
        track: Theme.autoTrack, zone: Qt.rgba(1.0, 0.176, 0.333, 0.85),   // Theme.autoRedline at 85 %
        redline: Theme.autoRedline, accentDeep: Theme.autoAccentDeep, accent: Theme.autoAccent,
        glow: Theme.autoGlow, line: Theme.autoLine
    })

    // Face painter: faces/canvas/AutoLevelFace.qml, or the C++ twin when
    // the loader registered Shadcn.Native (Theme.nativeFaces).
    Loader {
        id: face
        anchors.fill: parent
        source: Theme.face("AutoLevel")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
    }

    // Labels at 100 / 50 / 0 %, left of the ticks.
    Repeater {
        model: [[root.topLabel, 1.0], [root.midLabel, 0.5], [root.bottomLabel, 0.0]]
        delegate: Text {
            x: 0
            width: Math.max(4, root._barX - root._bulge - root._w * 0.16)
            y: root._barTop + root._barH * (1 - modelData[1]) - height / 2
            text: modelData[0]
            color: Theme.autoLine
            horizontalAlignment: Text.AlignRight
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(root._w * 0.14))
            font.weight: Theme.fontSemibold
            visible: text !== ""
        }
    }

    ShIcon {
        visible: root.icon !== ""
        name: root.icon
        size: Math.round(root._w * 0.3)
        color: Theme.autoLine
        x: root._barX + root._barW / 2 - width / 2
        y: root._barTop + root._barH + (root._h - root._barTop - root._barH - height) / 2
    }
}
