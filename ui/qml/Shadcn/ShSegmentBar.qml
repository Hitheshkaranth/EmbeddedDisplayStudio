/**
 * ShSegmentBar.qml
 * Segment Bar -- Automotive cluster widget. The battery / SOC bar of an EV
 * cluster: N cells filled in the accent blue up to the value, empty cells
 * in the track colour, an optional caption on the left and the percentage
 * on the right. At or below ``lowLevel`` the filled cells and the number
 * turn red.
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
                     : index === 0 ? Theme.autoAccentDeep : Theme.autoAccent
            }
        }
    }
}
