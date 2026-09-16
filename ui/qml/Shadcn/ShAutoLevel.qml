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

    Canvas {
        id: face
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var x = root._barX, w = root._barW, top = root._barTop, h = root._barH;
            var bottom = top + h, midY = top + h / 2, r = w / 2;

            // The bar outline: two quadratic edges bulging left by _bulge.
            function outline() {
                ctx.beginPath();
                ctx.moveTo(x, top + r);
                ctx.arc(x + r, top + r, r, Math.PI, 0);
                ctx.quadraticCurveTo(x + w - root._bulge, midY, x + w, bottom - r);
                ctx.arc(x + r, bottom - r, r, 0, Math.PI);
                ctx.quadraticCurveTo(x - root._bulge, midY, x, top + r);
                ctx.closePath();
            }

            ctx.save();
            outline();
            ctx.clip();

            // Track.
            ctx.fillStyle = Theme.autoTrack;
            ctx.fillRect(x - root._bulge - 1, top - 1, w + root._bulge + 2, h + 2);

            // Red zone: a slice of the track at the low or high end.
            var zone = Math.max(0, Math.min(1, root.redZoneSpan / 100)) * h;
            var zoneTop = -1, zoneBottom = -1;
            if (root.redZone === "low") { zoneTop = bottom - zone; zoneBottom = bottom; }
            else if (root.redZone === "high") { zoneTop = top; zoneBottom = top + zone; }
            if (zoneTop >= 0) {
                ctx.fillStyle = Qt.rgba(1.0, 0.176, 0.333, 0.85);   // Theme.autoRedline
                ctx.fillRect(x - root._bulge - 1, zoneTop, w + root._bulge + 2, zoneBottom - zoneTop);
            }

            // Fill from the bottom to the value.
            var fillTop = bottom - h * root._fraction;
            if (root._fraction > 0) {
                var grad = ctx.createLinearGradient(0, bottom, 0, fillTop);
                grad.addColorStop(0, Theme.autoAccentDeep);
                grad.addColorStop(1, Theme.autoAccent);
                ctx.fillStyle = grad;
                ctx.fillRect(x - root._bulge - 1, fillTop, w + root._bulge + 2, bottom - fillTop);
                // Fill inside the red zone reads as red, not blue.
                if (zoneTop >= 0) {
                    var rt = Math.max(zoneTop, fillTop), rb = Math.min(zoneBottom, bottom);
                    if (rb > rt) {
                        ctx.fillStyle = Theme.autoRedline;
                        ctx.fillRect(x - root._bulge - 1, rt, w + root._bulge + 2, rb - rt);
                    }
                }
                ctx.fillStyle = Theme.autoGlow;
                ctx.fillRect(x - root._bulge - 1, fillTop, w + root._bulge + 2, 2);
            }
            ctx.restore();

            // Ticks along the left edge of the bar.
            if (root.showTicks) {
                ctx.strokeStyle = Theme.autoLine;
                for (var i = 0; i <= 10; ++i) {
                    var f = i / 10;
                    var y = bottom - h * f;
                    // Left edge of the curve at this height.
                    var t = 1 - Math.abs(f - 0.5) * 2;      // 0 at the ends, 1 mid
                    var edge = x - root._bulge * (1 - (1 - t) * (1 - t)) * 0.5;
                    var len = (i % 5 === 0) ? root._w * 0.12 : root._w * 0.06;
                    ctx.lineWidth = (i % 5 === 0) ? 1.5 : 1;
                    ctx.beginPath();
                    ctx.moveTo(edge - 2, y);
                    ctx.lineTo(edge - 2 - len, y);
                    ctx.stroke();
                }
            }
        }
        Component.onCompleted: requestPaint()
        Connections {
            target: root
            function onValueChanged() { face.requestPaint() }
            function onMinimumValueChanged() { face.requestPaint() }
            function onMaximumValueChanged() { face.requestPaint() }
            function onRedZoneChanged() { face.requestPaint() }
            function onRedZoneSpanChanged() { face.requestPaint() }
            function onCurvedChanged() { face.requestPaint() }
            function onShowTicksChanged() { face.requestPaint() }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
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
