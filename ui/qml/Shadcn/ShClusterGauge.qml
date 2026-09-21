/**
 * ShClusterGauge.qml
 * Cluster Gauge -- Automotive arc-based instrument. An arc track with redline
 * band, gradient value arc, tick marks + labels, a big centre readout, a
 * caption and an optional inner dial ring.
 *
 * Drawing (from outside in, all dimensions relative to d = Math.min(width, height)):
 * 1. Scale track   – arc of `sweep` degrees, radius 0.38d, stroke 0.05d
 * 2. Redline band  – same arc from redlineFrom..maximumValue
 * 3. Value arc     – gradient from accentDeep to accent, redline portion red
 * 4. Major ticks+labels  – every majorStep
 * 5. Minor ticks       – 4 between majors
 * 6. Inner dial        – optional filled circle with radial gradient
 * 7. Readout / readoutUnit  – crisp Text elements centred in the item
 * 8. Caption             – Amber text above the readout
 * 9. label               – bottom-right muted text
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 4.2
    property real minimumValue: 0.0
    property real maximumValue: 8.0
    property real majorStep: 1.0
    property real redlineFrom: 7.0
    property real sweep: 240.0
    property string readout: ""       // empty: show value.toFixed(decimals)
    property string readoutUnit: "km/h"
    property string caption: ""
    property string label: "x1000 RPM"
    property int decimals: 0
    property bool showInnerDial: true

    implicitWidth: 240
    implicitHeight: 240

    readonly property real _span: Math.max(0.0001, root.maximumValue - root.minimumValue)
    readonly property real _d: Math.max(1, Math.min(width, height))
    readonly property real _startAngle: 90 + (360 - root.sweep) / 2
    /** The major scale values, min..max every majorStep (at most 60). */
    readonly property var _majors: {
        var out = [];
        var step = Math.max(0.0001, root.majorStep);
        for (var v = root.minimumValue, i = 0; v <= root.maximumValue + 0.0001 && i < 60; v += step, ++i)
            out.push(v);
        return out;
    }
    readonly property real _clamped:
        Math.max(root.minimumValue, Math.min(root.maximumValue, root.value))

    // Everything the face painter needs, values and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        value: root.value, minimumValue: root.minimumValue, maximumValue: root.maximumValue,
        majorStep: root.majorStep, redlineFrom: root.redlineFrom, sweep: root.sweep,
        showInnerDial: root.showInnerDial,
        track: Theme.autoTrack, redline: Theme.autoRedline,
        accentDeep: Theme.autoAccentDeep, accent: Theme.autoAccent, glow: Theme.autoGlow,
        line: Theme.autoLine, muted: Theme.autoMuted, panel: Theme.autoPanel,
        tileBorder: Theme.autoTileBorder, dialTint: Qt.rgba(10 / 255, 79 / 255, 138 / 255, 0.20)
    })

    // Face painter: faces/canvas/ClusterGaugeFace.qml, or the C++ twin when
    // the loader registered Shadcn.Native (Theme.nativeFaces).
    Loader {
        id: face
        anchors.fill: parent
        source: Theme.face("ClusterGauge")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
    }

    // -- 4b. Scale labels, as Text so they stay crisp at any size --
    Repeater {
        model: root._majors
        delegate: Text {
            readonly property real angle: (root._startAngle + root.sweep * ((modelData - root.minimumValue) / root._span)) * Math.PI / 180
            x: width / 2 + root.width / 2 + 0.47 * root._d * Math.cos(angle) - width
            y: root.height / 2 + 0.47 * root._d * Math.sin(angle) - height / 2
            text: Number(modelData).toFixed(0)
            color: modelData >= root.redlineFrom ? Theme.autoRedline : Theme.autoLine
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(0.068 * root._d))
            font.weight: Theme.fontMedium
        }
    }

    // -- 7 & 8. Readout + caption (crisp Text elements) --

    Text {
        id: captionText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: readoutText.top
        anchors.bottomMargin: 4
        text: root.caption
        color: Theme.autoAmber
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.07 * root._d)
        font.weight: Theme.fontMedium
        visible: root.caption !== ""
    }

    Text {
        id: readoutText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -(0.07 * root._d)
        text: root.readout !== "" ? root.readout : root._clamped.toFixed(root.decimals)
        color: Theme.autoText
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.28 * root._d)
        font.weight: Theme.fontSemibold
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: readoutText.bottom
        anchors.topMargin: 2
        text: root.readoutUnit
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.round(0.08 * root._d)
    }

    // -- 9. Label (bottom-right) --
    Text {
        // At the foot of the arc's opening, beside the last scale label.
        x: root.width / 2 + 0.2 * root._d
        y: root.height / 2 + 0.33 * root._d - height / 2
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(0.045 * root._d))
        visible: root.label !== ""
    }
}