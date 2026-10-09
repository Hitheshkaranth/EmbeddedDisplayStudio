/**
 * ShGearIndicator.qml
 * Gear Indicator -- the "P R N D" row of an automatic cluster, in order,
 * with the engaged gear large and bright and the others dimmed. A
 * ``modeNumber`` above 0 follows the engaged gear as a lighter digit
 * ("D4"). A gear that is not in the list is still shown, appended, so a
 * telemetry value the list did not foresee never blanks the display.
 *
 * ``orientation: "vertical"`` stacks the gears top to bottom in a rounded
 * rail (a haul truck's shifter strip): the engaged gear is a dark letter on
 * a bright disc, the others muted letters. The rail shows no mode number.
 */
import QtQuick 2.15

Item {
    id: root

    property string gears: "P,R,N,D"
    property string gear: "D"
    property int modeNumber: 4
    property bool showAll: true
    property string orientation: "horizontal"   // "horizontal" | "vertical"

    implicitWidth: 120
    implicitHeight: 70

    readonly property real _h: Math.max(1, height)
    readonly property var _list: {
        var parts = root.gears.split(",").map(function(s) { return s.trim() })
                        .filter(function(s) { return s !== "" });
        // A gear is a letter; a number (a simulator feeding 0, an unmapped
        // register) is not shown as one.
        var known = root.gear !== "" && isNaN(Number(root.gear));
        if (known && parts.indexOf(root.gear) < 0)
            parts.push(root.gear);
        return root.showAll ? parts : (known ? [root.gear] : []);
    }

    readonly property bool _vertical: root.orientation === "vertical"

    Row {
        visible: !root._vertical
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root._h * 0.12
        spacing: Math.round(root._h * 0.12)
        // Sized from the height; a row wider than the widget shrinks to fit
        // rather than spilling (hmi-ui scales its glyphs the same way).
        scale: implicitWidth > 0 ? Math.min(1, root.width * 0.96 / implicitWidth) : 1
        transformOrigin: Item.Bottom

        Repeater {
            model: root._list
            delegate: Row {
                readonly property bool current: modelData === root.gear
                anchors.bottom: parent.bottom
                spacing: 1
                Text {
                    anchors.bottom: parent.bottom
                    text: modelData
                    color: current ? Theme.autoText : Theme.autoMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(8, Math.round(root._h * (current ? 0.62 : 0.4)))
                    font.weight: current ? Theme.fontSemibold : Theme.fontMedium
                }
                Text {
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: Math.round(root._h * 0.02)
                    visible: current && root.modeNumber > 0
                    text: visible ? root.modeNumber.toString() : ""
                    color: Theme.autoLine
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(8, Math.round(root._h * 0.45))
                }
            }
        }
    }

    // -- vertical: the rail --------------------------------------------------
    Rectangle {
        id: rail
        visible: root._vertical
        anchors.fill: parent
        radius: Math.min(width, height) / 2
        color: Theme.autoTileBg
        border.color: Theme.autoTileBorder
        border.width: 1

        readonly property int count: Math.max(1, root._list.length)
        readonly property real pad: Math.min(width * 0.25, height * 0.05)
        readonly property real slot: Math.max(1, (height - 2 * pad) / count)
        readonly property real disc: Math.max(4, Math.min(width * 0.82, slot * 0.92))

        Repeater {
            model: root._vertical ? root._list : []
            delegate: Item {
                readonly property bool current: modelData === root.gear
                x: 0
                y: rail.pad + rail.slot * index
                width: rail.width
                height: rail.slot
                Rectangle {
                    visible: parent.current
                    anchors.centerIn: parent
                    width: rail.disc
                    height: rail.disc
                    radius: rail.disc / 2
                    color: Theme.autoText
                }
                Text {
                    anchors.centerIn: parent
                    text: modelData
                    color: parent.current ? Theme.autoPanel : Theme.autoMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Math.max(7, Math.round(parent.current ? rail.disc * 0.62
                                                 : Math.min(rail.slot * 0.5, rail.width * 0.5)))
                    font.weight: parent.current ? Theme.fontSemibold : Theme.fontMedium
                }
            }
        }
    }
}
