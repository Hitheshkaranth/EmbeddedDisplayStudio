/**
 * ShAttitude.qml
 * Attitude indicator: sky over ground, a pitch ladder, a bank scale and a
 * fixed aircraft symbol.
 *
 * The horizon rotates by -roll and slides by pitch; the aircraft symbol and
 * the bank pointer never move, which is what makes the instrument readable.
 * `pitch` and `roll` are in degrees, positive nose-up and right-wing-down.
 */
import QtQuick 2.15

Item {
    id: root

    property real pitch: 0
    property real roll: 0
    /** Pixels of travel per degree of pitch on the ladder. */
    property real pixelsPerDegree: 4

    implicitWidth: 220
    implicitHeight: 220
    clip: true

    Rectangle { anchors.fill: parent; color: Theme.efisPanel }

    Item {
        id: horizon
        anchors.centerIn: parent
        // Oversized so a rolled horizon still covers the corners.
        width: root.width * 2.4
        height: root.height * 2.4
        rotation: -root.roll
        transformOrigin: Item.Center

        Item {
            anchors.fill: parent
            y: root.pitch * root.pixelsPerDegree

            Rectangle {
                width: parent.width; height: parent.height / 2
                anchors.top: parent.top
                color: Theme.efisSky
            }
            Rectangle {
                width: parent.width; height: parent.height / 2
                anchors.bottom: parent.bottom
                color: Theme.efisGround
            }
            Rectangle {
                width: parent.width; height: 2
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.efisLine
            }

            // Pitch ladder: 10-degree majors labelled, 5-degree minors bare.
            Repeater {
                model: [-20, -15, -10, -5, 5, 10, 15, 20]
                delegate: Item {
                    property bool major: (modelData % 10) === 0
                    width: parent.width
                    height: 2
                    y: parent.height / 2 - modelData * root.pixelsPerDegree - 1
                    Rectangle {
                        anchors.centerIn: parent
                        width: major ? 70 : 36
                        height: 2
                        color: Theme.efisLine
                    }
                    Text {
                        visible: major
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: parent.horizontalCenter
                        anchors.rightMargin: 42
                        text: Math.abs(modelData)
                        color: Theme.efisText
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeXs
                    }
                }
            }
        }
    }

    // Bank pointer, fixed to the case.
    Canvas {
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.strokeStyle = Theme.efisLine;
            ctx.fillStyle = Theme.efisAircraft;
            ctx.lineWidth = 2;
            var cx = width / 2, cy = height / 2, r = Math.min(width, height) * 0.44;
            var marks = [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60];
            for (var i = 0; i < marks.length; i++) {
                var a = (marks[i] - 90) * Math.PI / 180;
                var inner = marks[i] % 30 === 0 ? r - 12 : r - 7;
                ctx.beginPath();
                ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
                ctx.lineTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
                ctx.stroke();
            }
            // Fixed aircraft symbol: wings and a centre dot.
            ctx.strokeStyle = Theme.efisAircraft;
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(cx - 46, cy); ctx.lineTo(cx - 16, cy);
            ctx.moveTo(cx + 16, cy); ctx.lineTo(cx + 46, cy);
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(cx, cy, 3, 0, Math.PI * 2);
            ctx.fill();
        }
        Component.onCompleted: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
}
