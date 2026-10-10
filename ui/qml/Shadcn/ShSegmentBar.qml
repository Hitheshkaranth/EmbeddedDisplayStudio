/**
 * ShSegmentBar.qml
 * Segment Bar -- Automotive cluster widget. The battery / SOC bar of an EV
 * cluster: N cells filled in the accent blue up to the value, empty cells
 * in the track colour, an optional caption on the left and the percentage
 * on the right. At or below ``lowLevel`` the filled cells and the number
 * turn red. ``barColor`` fills the cells in that colour instead of the
 * accent (unset -- transparent, the Designer's "" -- keeps the accent).
 * ``style`` "solid" (default "segments"): one rounded track (autoTrack, a
 * rim of the fill colour at 80 %, max(1, 0.04 x its height) px) and, inset max(2, 0.1 x its height),
 * one rounded fill up to the value, shaded along its length from 25 % darker
 * to 20 % lighter, with the kit's soft glow (ShGlow). w_shsegmentbar.c draws
 * the same.
 */
import QtQuick 2.15

Item {
    id: root

    property real value: 60.0
    property real minimumValue: 0.0
    property real maximumValue: 100.0
    property int segments: 12
    property string label: "SOC"
    property bool showPercent: true
    property real lowLevel: 20.0
    property color barColor: "transparent"
    /** "segments" | "solid" */
    property string style: "segments"

    implicitWidth: 320
    implicitHeight: 36

    readonly property real _h: Math.max(1, height)
    readonly property real _span: Math.max(0.0001, root.maximumValue - root.minimumValue)
    readonly property real _fraction: Math.max(0, Math.min(1, (root.value - root.minimumValue) / root._span))
    readonly property int _count: Math.max(1, Math.min(60, root.segments))
    /** Cells at or below the level; a half-covered last cell counts. */
    readonly property int _filled: Math.min(root._count, Math.floor(root._fraction * root._count + 0.5))
    readonly property bool _low: root.lowLevel > 0 && root.value <= root.lowLevel
    readonly property real _gap: Math.round(root._h * 0.12)

    Text {
        id: caption
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._h * 0.4))
        visible: root.label !== ""
    }

    Text {
        id: percent
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: Math.round(root._fraction * 100) + "%"
        color: root._low ? Theme.autoRed : Theme.autoText
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(7, Math.round(root._h * 0.45))
        font.weight: Theme.fontSemibold
        visible: root.showPercent
    }

    Row {
        id: cells
        anchors.left: caption.visible ? caption.right : parent.left
        anchors.leftMargin: caption.visible ? Math.round(root._h * 0.3) : 0
        anchors.right: percent.visible ? percent.left : parent.right
        anchors.rightMargin: percent.visible ? Math.round(root._h * 0.3) : 0
        anchors.verticalCenter: parent.verticalCenter
        height: Math.round(root._h * 0.6)
        spacing: root._gap
        visible: root.style !== "solid"
        readonly property real cellWidth: Math.max(1, (width - root._gap * (root._count - 1)) / root._count)

        Repeater {
            model: root._count
            delegate: Rectangle {
                readonly property bool filled: index < root._filled
                width: cells.cellWidth
                height: cells.height
                radius: Math.round(root._h * 0.1)
                color: !filled ? Theme.autoTrack
                     : root._low ? Theme.autoRedline
                     : root.barColor.a > 0 ? root.barColor
                     : index === 0 ? Theme.autoAccentDeep : Theme.autoAccent
            }
        }
    }

    // -- style "solid" ---------------------------------------------------------
    Item {
        id: solid
        visible: root.style === "solid"
        x: cells.x
        y: Math.round(root._h / 2 - height / 2)
        width: cells.width
        height: cells.height
        readonly property color colour: root._low ? Theme.autoRedline
                                      : root.barColor.a > 0 ? root.barColor : Theme.autoAccent
        readonly property int rad: Math.round(height * 0.25)
        readonly property int inset: Math.max(2, Math.round(height * 0.1))
        Rectangle {
            anchors.fill: parent
            radius: solid.rad
            color: Theme.autoTrack
            border.width: Math.max(1, Math.round(solid.height * 0.04))
            border.color: Qt.rgba(solid.colour.r, solid.colour.g, solid.colour.b, 204 / 255)
        }
        Item {
            x: solid.inset
            y: solid.inset
            width: Math.round((solid.width - 2 * solid.inset) * root._fraction)
            height: solid.height - 2 * solid.inset
            visible: width >= 1
            ShGlow { anchors.fill: parent; color: solid.colour; radius: Math.max(0, solid.rad - solid.inset) }
            Rectangle {
                anchors.fill: parent
                radius: Math.max(0, solid.rad - solid.inset)
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.shade(solid.colour, -25) }
                    GradientStop { position: 1; color: Theme.shade(solid.colour, 20) }
                }
            }
        }
    }
}
