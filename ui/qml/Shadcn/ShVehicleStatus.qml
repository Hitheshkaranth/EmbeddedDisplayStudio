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

    // Everything the face painter needs, geometry and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        bodyX: root._bodyX, bodyY: root._bodyY, bodyW: root._bodyW, bodyH: root._bodyH,
        bodyRadius: Math.min(root._w * 0.16, root._bodyW / 2, root._bodyH / 2),
        wheelW: root._wheelW, wheelH: root._wheelH,
        frontLeftLow: root.low(root.frontLeft), frontRightLow: root.low(root.frontRight),
        rearLeftLow: root.low(root.rearLeft), rearRightLow: root.low(root.rearRight),
        wheel: Qt.rgba(0.788, 0.827, 0.875, 0.7), wheelLow: Theme.autoAmber,
        bodyFill: Qt.rgba(0.039, 0.31, 0.541, 0.25),   // Theme.autoAccentDeep at 25 %
        bodyLine: Theme.autoAccent,
        glass: Qt.rgba(0.133, 0.659, 1.0, 0.6)         // Theme.autoAccent at 60 %
    })

    // Face painter: faces/canvas/VehicleStatusFace.qml, or the C++ twin when
    // the loader registered Shadcn.Native (Theme.nativeFaces).
    Loader {
        id: car
        anchors.fill: parent
        source: Theme.face("VehicleStatus")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
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
