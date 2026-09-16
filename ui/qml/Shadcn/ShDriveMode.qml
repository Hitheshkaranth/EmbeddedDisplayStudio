/**
 * ShDriveMode.qml
 * Drive Mode -- Automotive cluster widget. A caption over the current mode
 * name, flanked by chevrons that step through the mode list and wrap.
 *
 * ``activated(index)`` fires on a tap only. Telemetry writing
 * ``currentIndex`` back (the generator's ``Binding on``) must not re-fire
 * it, or a read would turn into a write.
 */
import QtQuick 2.15

Item {
    id: root

    property string label: "Drive mode"
    property string modes: "ECO,COMFORT,SPORT"
    property int currentIndex: 2
    // enabled: Item's own property; the registry exposes it, QML inherits it.

    signal activated(int index)

    implicitWidth: 180
    implicitHeight: 56

    readonly property var _modeList: root.modes.split(",").map(function(s) { return s.trim() })
                                         .filter(function(s) { return s !== "" })
    readonly property int _modeCount: root._modeList.length
    readonly property string _currentMode:
        (root.currentIndex >= 0 && root.currentIndex < root._modeCount)
            ? root._modeList[root.currentIndex] : ""
    readonly property real _h: Math.max(1, height)

    opacity: root.enabled ? 1.0 : 0.5

    function step(delta) {
        if (root._modeCount === 0)
            return;
        root.currentIndex = ((root.currentIndex + delta) % root._modeCount + root._modeCount) % root._modeCount;
        root.activated(root.currentIndex);
    }

    Text {
        id: caption
        anchors.top: parent.top
        anchors.topMargin: root._h * 0.04
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.label
        color: Theme.autoMuted
        font.family: Theme.fontFamily
        font.pixelSize: Math.max(8, Math.round(root._h * 0.24))
        font.weight: Theme.fontMedium
        visible: root.label !== ""
    }

    Row {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root._h * 0.02
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: Math.round(root._h * 0.2)

        Item {
            width: Math.round(root._h * 0.9); height: Math.round(root._h * 0.62)
            ShIcon {
                anchors.centerIn: parent
                name: "chevron-left"
                size: Math.round(root._h * 0.36)
                color: Theme.autoLine
                opacity: leftTap.pressed ? 0.5 : 1.0
            }
            MouseArea {
                id: leftTap
                anchors.fill: parent
                enabled: root.enabled
                onClicked: root.step(-1)
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root._currentMode
            color: Theme.autoAmber
            font.family: Theme.fontFamily
            font.pixelSize: Math.max(8, Math.round(root._h * 0.34))
            font.weight: Theme.fontSemibold
        }

        Item {
            width: Math.round(root._h * 0.9); height: Math.round(root._h * 0.62)
            ShIcon {
                anchors.centerIn: parent
                name: "chevron-right"
                size: Math.round(root._h * 0.36)
                color: Theme.autoLine
                opacity: rightTap.pressed ? 0.5 : 1.0
            }
            MouseArea {
                id: rightTap
                anchors.fill: parent
                enabled: root.enabled
                onClicked: root.step(1)
            }
        }
    }
}
