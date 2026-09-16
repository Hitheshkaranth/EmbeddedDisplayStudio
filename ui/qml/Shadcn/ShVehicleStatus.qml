/**
 * ShVehicleStatus.qml
 * Vehicle Status -- Automotive cluster widget. A top-view car outline in
 * the accent blue with the four tyre pressures at its corners, as an EV
 * cluster shows TPMS. A wheel below ``warnBelow`` is drawn amber and its
 * readout red; 0 disables the limit.
 */
import QtQuick 2.15

Item {
    id: root

    property real frontLeft: 2.6
    property real frontRight: 2.5
    property real rearLeft: 1.6
    property real rearRight: 2.2
    property string unit: "bar"
    property real warnBelow: 1.8
    property int decimals: 1
    property string label: "TPMS"

    implicitWidth: 150
    implicitHeight: 190

    readonly property real _w: Math.max(1, width)
    readonly property real _h: Math.max(1, height)
    function low(v) { return root.warnBelow > 0 && v < root.warnBelow }

    // Body geometry shared by the canvas and the corner readouts.
    readonly property real _bodyW: root._w * 0.42
    readonly property real _bodyH: root._h * 0.7
    readonly property real _bodyX: (root._w - root._bodyW) / 2
    readonly property real _bodyY: (root._h - root._bodyH) / 2
    readonly property real _wheelW: root._w * 0.09
    readonly property real _wheelH: root._h * 0.14

    Canvas {
        id: car
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var x = root._bodyX, y = root._bodyY, w = root._bodyW, h = root._bodyH;
            var r = Math.min(root._w * 0.16, w / 2, h / 2);

            function roundedRect(rx, ry, rw, rh, rr) {
                ctx.beginPath();
                ctx.moveTo(rx + rr, ry);
                ctx.lineTo(rx + rw - rr, ry);
                ctx.arcTo(rx + rw, ry, rx + rw, ry + rr, rr);
                ctx.lineTo(rx + rw, ry + rh - rr);
                ctx.arcTo(rx + rw, ry + rh, rx + rw - rr, ry + rh, rr);
                ctx.lineTo(rx + rr, ry + rh);
                ctx.arcTo(rx, ry + rh, rx, ry + rh - rr, rr);
                ctx.lineTo(rx, ry + rr);
                ctx.arcTo(rx, ry, rx + rr, ry, rr);
                ctx.closePath();
            }

            // Wheels first, so the body's edge sits over them.
            var wheels = [
                [x - root._wheelW * 0.6, y + h * 0.12, root.frontLeft],
                [x + w - root._wheelW * 0.4, y + h * 0.12, root.frontRight],
                [x - root._wheelW * 0.6, y + h * 0.88 - root._wheelH, root.rearLeft],
                [x + w - root._wheelW * 0.4, y + h * 0.88 - root._wheelH, root.rearRight]];
            for (var i = 0; i < wheels.length; ++i) {
                ctx.fillStyle = root.low(wheels[i][2]) ? Theme.autoAmber : Qt.rgba(0.788, 0.827, 0.875, 0.7);
                roundedRect(wheels[i][0], wheels[i][1], root._wheelW, root._wheelH, root._wheelW * 0.3);
                ctx.fill();
            }

            // Body.
            ctx.fillStyle = Qt.rgba(0.039, 0.31, 0.541, 0.25);   // Theme.autoAccentDeep at 25 %
            ctx.strokeStyle = Theme.autoAccent;
            ctx.lineWidth = 1.5;
            roundedRect(x, y, w, h, r);
            ctx.fill();
            ctx.stroke();

            // Windscreen and rear window.
            ctx.strokeStyle = Qt.rgba(0.133, 0.659, 1.0, 0.6);   // Theme.autoAccent at 60 %
            ctx.lineWidth = 1.2;
            var inset = w * 0.12;
            ctx.beginPath();
            ctx.moveTo(x + inset, y + h * 0.28); ctx.lineTo(x + w - inset, y + h * 0.28);
            ctx.moveTo(x + inset, y + h * 0.72); ctx.lineTo(x + w - inset, y + h * 0.72);
            ctx.stroke();
        }
        Component.onCompleted: requestPaint()
        Connections {
            target: root
            function onFrontLeftChanged() { car.requestPaint() }
            function onFrontRightChanged() { car.requestPaint() }
            function onRearLeftChanged() { car.requestPaint() }
            function onRearRightChanged() { car.requestPaint() }
            function onWarnBelowChanged() { car.requestPaint() }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Repeater {
        // [value, x anchor (0 left / 1 right), y anchor (0 top / 1 bottom)]
        model: [[root.frontLeft, 0, 0], [root.frontRight, 1, 0], [root.rearLeft, 0, 1], [root.rearRight, 1, 1]]
        delegate: Text {
            readonly property real v: modelData[0]
            text: v.toFixed(root.decimals)
            color: root.low(v) ? Theme.autoRed : Theme.autoText
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(7, Math.round(root._h * 0.12))
            font.weight: Theme.fontSemibold
            x: modelData[1] === 0 ? root._bodyX - root._wheelW - width - 2 : root._bodyX + root._bodyW + root._wheelW + 2
            y: modelData[2] === 0 ? root._bodyY + root._h * 0.06 : root._bodyY + root._bodyH - root._h * 0.06 - height
        }
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        text: root.unit
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._h * 0.08))
        visible: root.unit !== ""
    }

    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._h * 0.08))
        visible: root.label !== ""
    }
}
