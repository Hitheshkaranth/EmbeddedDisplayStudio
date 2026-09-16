/**
 * ShGearIndicator.qml
 * Gear Indicator -- the "P R N D" row of an automatic cluster, in order,
 * with the engaged gear large and bright and the others dimmed. A
 * ``modeNumber`` above 0 follows the engaged gear as a lighter digit
 * ("D4"). A gear that is not in the list is still shown, appended, so a
 * telemetry value the list did not foresee never blanks the display.
 */
import QtQuick 2.15

Item {
    id: root

    property string gears: "P,R,N,D"
    property string gear: "D"
    property int modeNumber: 4
    property bool showAll: true

    implicitWidth: 120
    implicitHeight: 70

    readonly property real _h: Math.max(1, height)
    readonly property var _list: {
        var parts = root.gears.split(",").map(function(s) { return s.trim() })
                        .filter(function(s) { return s !== "" });
        if (parts.indexOf(root.gear) < 0 && root.gear !== "")
            parts.push(root.gear);
        return root.showAll ? parts : [root.gear];
    }

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root._h * 0.12
        spacing: Math.round(root._h * 0.12)

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
}
