/**
 * ShDriveMode.qml
 * Drive Mode -- Automotive cluster widget. Shows a label with the current
 * mode name flanked by chevron arrows that cycle through the mode list.
 */
import QtQuick 2.15

Item {
    id: root

    property string label: "Drive mode"
    property string modes: "ECO,COMFORT,SPORT"
    property int currentIndex: 2
    // enabled: Item's own property; the registry exposes it, QML inherits it.

    signal activated(int index)

    readonly property int _modeCount: root.modes.split(",").length
    readonly property string _currentMode: {
        var parts = root.modes.split(",");
        var idx = root.currentIndex;
        if (idx < 0 || idx >= parts.length)
            return "";
        return parts[idx].trim();
    }

    implicitWidth: 180
    implicitHeight: 56

    opacity: root.enabled ? 1.0 : 0.5

    Column {
        anchors.fill: parent
        spacing: 0

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: 4
            text: root.label
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Math.round(root.implicitHeight * 0.24)
            font.weight: Theme.fontMedium
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            spacing: Math.round(root.implicitHeight * 0.24)

            Item {
                width: Math.round(root.implicitHeight * 0.9)
                height: width

                ShIcon {
                    id: leftIcon
                    anchors.centerIn: parent
                    name: "chevron-left"
                    size: Math.round(root.implicitHeight * 0.36)
                    color: Theme.autoLine
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.enabled
                    hoverEnabled: false
                    onClicked: function(mouse) {
                        mouse.accepted = true;
                        root.currentIndex = (root.currentIndex - 1 + root._modeCount) % root._modeCount;
                        root.activated(root.currentIndex);
                    }
                    onPressed: function() { leftIcon.opacity = 0.5 }
                    onReleased: function() { leftIcon.opacity = 1.0 }
                }
            }

            Text {
                text: root._currentMode
                color: Theme.autoAmber
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(root.implicitHeight * 0.34)
                font.weight: Theme.fontSemibold
            }

            Item {
                width: Math.round(root.implicitHeight * 0.9)
                height: width

                ShIcon {
                    id: rightIcon
                    anchors.centerIn: parent
                    name: "chevron-right"
                    size: Math.round(root.implicitHeight * 0.36)
                    color: Theme.autoLine
                }

                MouseArea {
                    anchors.fill: parent
                    enabled: root.enabled
                    hoverEnabled: false
                    onClicked: function(mouse) {
                        mouse.accepted = true;
                        root.currentIndex = (root.currentIndex + 1) % root._modeCount;
                        root.activated(root.currentIndex);
                    }
                    onPressed: function() { rightIcon.opacity = 0.5 }
                    onReleased: function() { rightIcon.opacity = 1.0 }
                }
            }
        }
    }

    Component.onCompleted: {
        if (root.currentIndex >= root._modeCount)
            root.currentIndex = root._modeCount - 1;
        if (root.currentIndex < 0)
            root.currentIndex = 0;
    }
}