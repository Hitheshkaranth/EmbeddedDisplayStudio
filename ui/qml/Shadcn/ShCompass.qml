/**
 * ShCompass.qml
 * Heading rose with a fixed lubber line, a selected-heading bug and an
 * optional course needle.
 *
 * The card rotates by -heading so the number under the lubber line is the
 * heading being flown, which is the convention every other instrument on the
 * panel is read against.
 */
import QtQuick 2.15

Item {
    id: root

    property real heading: 0
    /** Selected heading. Negative hides the bug. */
    property real headingBug: -1
    /** Course/track needle in degrees. Negative hides it. */
    property real course: -1

    implicitWidth: 220
    implicitHeight: 220

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: Theme.efisPanel
        border.color: Theme.border
        border.width: 1
    }

    Canvas {
        id: card
        anchors.fill: parent
        rotation: -root.heading
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            var cx = width / 2, cy = height / 2, r = Math.min(width, height) / 2 - 4;
            ctx.strokeStyle = Theme.efisLine;
            ctx.fillStyle = Theme.efisText;
            ctx.textAlign = "center";
            for (var deg = 0; deg < 360; deg += 5) {
                var a = (deg - 90) * Math.PI / 180;
                var major = deg % 30 === 0;
                var inner = r - (major ? 14 : 7);
                ctx.lineWidth = major ? 2 : 1;
                ctx.beginPath();
                ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
                ctx.lineTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
                ctx.stroke();
                if (major) {
                    var text = deg === 0 ? "N" : deg === 90 ? "E"
                             : deg === 180 ? "S" : deg === 270 ? "W" : (deg / 10);
                    ctx.save();
                    ctx.translate(cx + Math.cos(a) * (r - 28), cy + Math.sin(a) * (r - 28));
                    ctx.rotate((deg) * Math.PI / 180);
                    ctx.font = "13px sans-serif";
                    ctx.fillText(text, 0, 5);
                    ctx.restore();
                }
            }
        }
        Component.onCompleted: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    // Course needle, rotating with the card.
    Rectangle {
        visible: root.course >= 0
        width: 3
        height: parent.height * 0.62
        color: Theme.efisNav
        anchors.centerIn: parent
        rotation: root.course - root.heading
        transformOrigin: Item.Center
    }

    // Selected-heading bug, rotating with the card.
    Rectangle {
        visible: root.headingBug >= 0
        width: 14
        height: 10
        color: Theme.efisBug
        x: parent.width / 2 - 7
        y: 2
        transform: Rotation {
            origin.x: 7
            origin.y: root.height / 2 - 2
            angle: root.headingBug - root.heading
        }
    }

    // Fixed lubber line and the aircraft at the centre.
    Rectangle {
        width: 2; height: 14
        color: Theme.efisAircraft
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
    }
    Rectangle {
        width: 30; height: 2
        color: Theme.efisAircraft
        anchors.centerIn: parent
    }
}
