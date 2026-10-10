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
 *
 * style "neon" (default "classic"): no ticks, scale numbers, needle or
 * inner dial. A dim track (12 %) and a thick round-capped value arc
 * (radius 0.40d, stroke 0.085d) shaded along the scale from accentColor to
 * accentColor2 (unset: the accent 35 % lighter), autoRedline past
 * redlineFrom, over a soft glow (NeonPaint.js). Centre: the caption
 * (0.075d, semibold, accent), the value bold ~0.30d (smaller when long),
 * the unit (0.075d) and the label (0.06d) under it, muted.
 * native/hmi-ui/src/widgets/w_shclustergauge.c draws the same.
 */
import QtQuick 2.15
import "NeonPaint.js" as Neon

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
    /** The value arc's colour (orange RPM, yellow payload). Unset
     *  (transparent, the Designer's "") keeps Theme.autoAccent. The deep end
     *  of the gradient is this colour 35 % of the way to black, the glow
     *  line 35 % of the way to white (hmi-ui mixes the same). */
    property color accentColor: "transparent"
    /** "classic" | "neon" */
    property string style: "classic"
    /** neon: the gradient's far end (the scale's end); unset = the accent 35 % lighter. */
    property color accentColor2: "transparent"

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
    /** Characters in the longest scale number; past four the numbers shrink. */
    readonly property int _longestMajor: {
        var dp = root.majorStep >= 1 ? 0 : root.majorStep >= 0.1 ? 1 : 2;
        var n = 1;
        for (var i = 0; i < root._majors.length; ++i)
            n = Math.max(n, Number(root._majors[i]).toFixed(dp).length);
        return n;
    }
    readonly property real _clamped:
        Math.max(root.minimumValue, Math.min(root.maximumValue, root.value))
    readonly property bool _custom: root.accentColor.a > 0
    readonly property color _accent: root._custom ? root.accentColor : Theme.autoAccent
    readonly property color _accentDeep: root._custom ? Qt.tint(root.accentColor, Qt.rgba(0, 0, 0, 0.35))
                                                      : Theme.autoAccentDeep
    readonly property color _glow: root._custom ? Qt.tint(root.accentColor, Qt.rgba(1, 1, 1, 0.35))
                                                : Theme.autoGlow
    readonly property bool _neon: root.style === "neon"
    readonly property color _accent2: root.accentColor2.a > 0 ? root.accentColor2 : Theme.shade(root._accent, 35)
    readonly property string _readoutText: root.readout !== "" ? root.readout : root._clamped.toFixed(root.decimals)
    /** neon value face: ~0.30 d, smaller when long so it stays inside the arc */
    readonly property int _neonFs: Math.max(8, Math.round(Math.min(0.30 * root._d,
                                   0.62 * root._d / (Math.max(1, root._readoutText.length) * 0.6))))

    // Everything the face painter needs, values and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        value: root.value, minimumValue: root.minimumValue, maximumValue: root.maximumValue,
        majorStep: root.majorStep, redlineFrom: root.redlineFrom, sweep: root.sweep,
        showInnerDial: root.showInnerDial,
        track: Theme.autoTrack, redline: Theme.autoRedline,
        accentDeep: root._accentDeep, accent: root._accent, glow: root._glow,
        line: Theme.autoLine, muted: Theme.autoMuted, panel: Theme.autoPanel,
        tileBorder: Theme.autoTileBorder,
        dialTint: root._custom ? Qt.rgba(root._accentDeep.r, root._accentDeep.g, root._accentDeep.b, 0.20)
                               : Qt.rgba(10 / 255, 79 / 255, 138 / 255, 0.20)
    })

    // Face painter: faces/canvas/ClusterGaugeFace.qml, or the C++ twin when
    // the loader registered Shadcn.Native (Theme.nativeFaces).
    Loader {
        id: face
        anchors.fill: parent
        visible: !root._neon
        source: Theme.face("ClusterGauge")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
    }

    // -- neon: track, glow and value arc --
    Canvas {
        id: neonFace
        anchors.fill: parent
        visible: root._neon
        readonly property var spec: root._neon ? [root.value, root.minimumValue, root.maximumValue,
                                                  root.redlineFrom, root.sweep, root._accent, root._accent2,
                                                  root.width, root.height] : []
        onSpecChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            if (!root._neon) return;
            var d = Math.min(width, height), cx = width / 2, cy = height / 2;
            var span = Math.max(0.0001, root.maximumValue - root.minimumValue);
            var a0 = 90 + (360 - root.sweep) / 2, a1 = a0 + root.sweep;
            var arcR = 0.40 * d, strokeW = 0.085 * d, reach = Neon.glowReach(d);
            var c0 = root._accent, c1 = root._accent2, red = Theme.autoRedline;
            function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
            var redA = root.redlineFrom < root.maximumValue
                ? Math.round(a0 + root.sweep * clamp((root.redlineFrom - root.minimumValue) / span, 0, 1))
                : Math.round(a1);
            var valueA = Math.round(a0 + root.sweep * (root._clamped - root.minimumValue) / span);
            var redStart = redA <= Math.round(a0), redEnd = redA >= Math.round(a1);
            // 1. dim track, red past the redline
            Neon.neonArc(ctx, cx, cy, arcR, strokeW, a0, redA, a0, a1, c0, c1, 31, 10,
                         redEnd ? Neon.CAPS : Neon.CAP_START);
            Neon.neonArc(ctx, cx, cy, arcR, strokeW, redA, a1, a0, a1, red, red, 31, 10,
                         redStart ? Neon.CAPS : Neon.CAP_END);
            // 2. glow, 3. value
            var vEnd = Math.min(valueA, redA), intoRed = valueA > redA;
            Neon.neonGlow(ctx, cx, cy, arcR, strokeW, a0, vEnd, a0, a1, c0, c1, reach,
                          intoRed ? Neon.CAP_START : Neon.CAPS);
            if (intoRed)
                Neon.neonGlow(ctx, cx, cy, arcR, strokeW, redA, valueA, a0, a1, red, red, reach,
                              redStart ? Neon.CAPS : Neon.CAP_END);
            Neon.neonArc(ctx, cx, cy, arcR, strokeW, a0, vEnd, a0, a1, c0, c1, 255, 5,
                         intoRed ? Neon.CAP_START : Neon.CAPS);
            if (intoRed)
                Neon.neonArc(ctx, cx, cy, arcR, strokeW, redA, valueA, a0, a1, red, red, 255, 5,
                             redStart ? Neon.CAPS : Neon.CAP_END);
        }
    }

    // -- 4b. Scale labels, as Text so they stay crisp at any size --
    Repeater {
        model: root._neon ? [] : root._majors
        delegate: Text {
            readonly property real angle: (root._startAngle + root.sweep * ((modelData - root.minimumValue) / root._span)) * Math.PI / 180
            x: width / 2 + root.width / 2 + 0.47 * root._d * Math.cos(angle) - width
            y: root.height / 2 + 0.47 * root._d * Math.sin(angle) - height / 2
            // As many decimals as the step needs (0.5 steps read "0.5", not "1").
            text: Number(modelData).toFixed(root.majorStep >= 1 ? 0 : root.majorStep >= 0.1 ? 1 : 2)
            color: modelData >= root.redlineFrom ? Theme.autoRedline : Theme.autoLine
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(0.068 * root._d * (root._longestMajor > 4 ? 4 / root._longestMajor : 1)))
            font.weight: Theme.fontMedium
        }
    }

    // -- 7 & 8. Readout + caption (crisp Text elements) --

    Text {
        id: captionText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: readoutText.top
        anchors.bottomMargin: root._neon ? -Math.round(0.10 * root._neonFs) : 4
        text: root.caption
        color: root._neon ? root._accent : Theme.autoAmber
        font.family: Theme.fontFamily
        // Inside the ring of scale numbers: the chord at the caption's
        // height, and a smaller face for a long caption (as hmi-ui does).
        // Neon: 0.56 d wide, 0.075 d.
        width: root._neon ? Math.round(0.56 * root._d) : 2 * Math.sqrt(0.40 * 0.40 - 0.26 * 0.26) * root._d
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        font.pixelSize: root._neon
            ? Math.max(7, Math.round(Math.min(0.075 * root._d,
                       0.56 * root._d / Math.max(1, root.caption.length * 0.62))))
            : Math.max(7, Math.round(Math.min(0.07 * root._d,
                       width / Math.max(1, root.caption.length * 0.56))))
        font.weight: root._neon ? Theme.fontSemibold : Theme.fontMedium
        visible: root.caption !== ""
    }

    Text {
        id: readoutText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: root._neon ? -Math.round(0.03 * root._d) : -(0.07 * root._d)
        text: root._readoutText
        color: Theme.autoText
        font.family: Theme.fontFamily
        font.pixelSize: root._neon ? root._neonFs : Math.round(0.28 * root._d)
        font.weight: root._neon ? Font.Bold : Theme.fontSemibold
    }

    Text {
        id: unitText
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: readoutText.bottom
        anchors.topMargin: root._neon ? -Math.round(0.12 * root._neonFs) : 2
        text: root.readoutUnit
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: root._neon ? Math.max(7, Math.round(0.075 * root._d)) : Math.round(0.08 * root._d)
        font.weight: root._neon ? Theme.fontMedium : Font.Normal
        visible: !root._neon || root.readoutUnit !== ""
    }

    // -- 9. Label (bottom-right; neon: under the unit) --
    Text {
        // At the foot of the arc's opening, beside the last scale label.
        x: root._neon ? Math.floor((root.width - width) / 2) : root.width / 2 + 0.2 * root._d
        y: !root._neon ? root.height / 2 + 0.33 * root._d - height / 2
           : unitText.visible ? unitText.y + unitText.height
           : readoutText.y + readoutText.height - Math.round(0.12 * root._neonFs)
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round((root._neon ? 0.06 : 0.045) * root._d))
        visible: root.label !== ""
    }
}