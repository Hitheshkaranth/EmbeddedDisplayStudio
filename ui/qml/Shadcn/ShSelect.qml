import QtQuick 2.15
import QtQuick.Controls.Basic 2.15 as QQC

Item {
    id: root
    property var model: []
    property int currentIndex: 0
    property string placeholder: "Select..."
    property string label: ""
    signal activated(int index)
    implicitWidth: 200
    implicitHeight: label ? 56 : 40
    opacity: enabled ? 1 : 0.5

    Column {
        anchors.fill: parent
        spacing: 4
        Text {
            width: parent.width; height: visible ? 16 : 0
            visible: root.label !== ""; text: root.label; elide: Text.ElideRight
            color: Theme.foreground; font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeXs
        }
        QQC.ComboBox {
            id: combo
            width: parent.width; height: 36
            model: root.model
            currentIndex: root.currentIndex
            enabled: root.enabled
            textRole: ""
            displayText: currentIndex >= 0 && currentIndex < count ? currentText : root.placeholder
            onActivated: function(index) { root.currentIndex = index; root.activated(index) }
            contentItem: Text {
                leftPadding: Theme.spacing12; rightPadding: 30
                text: combo.displayText; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                color: combo.currentIndex >= 0 && combo.count > 0 ? Theme.foreground : Theme.mutedForeground
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm
            }
            indicator: Text {
                x: combo.width - width - Theme.spacing12; anchors.verticalCenter: parent.verticalCenter
                text: combo.popup.visible ? "\u25B2" : "\u25BC"; color: Theme.mutedForeground; font.pixelSize: 10
            }
            background: Rectangle {
                radius: Theme.radiusMd; color: Theme.background
                border.color: combo.activeFocus ? Theme.ring : Theme.input; border.width: combo.activeFocus ? 2 : 1
            }
            popup: QQC.Popup {
                y: combo.height + 2; width: combo.width
                implicitHeight: Math.min(contentItem.implicitHeight + 2, 220)
                padding: 1
                contentItem: ListView {
                    clip: true; implicitHeight: contentHeight; model: combo.popup.visible ? combo.delegateModel : null
                    currentIndex: combo.highlightedIndex
                    QQC.ScrollIndicator.vertical: QQC.ScrollIndicator { }
                }
                background: Rectangle { color: Theme.popover; border.color: Theme.border; border.width: 1; radius: Theme.radiusMd }
            }
            delegate: QQC.ItemDelegate {
                required property var modelData
                required property int index
                width: combo.width; height: 36
                highlighted: combo.highlightedIndex === index
                contentItem: Text {
                    text: modelData; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter
                    color: parent.highlighted ? Theme.accentForeground : Theme.popoverForeground
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontSizeSm
                }
                background: Rectangle { color: parent.highlighted ? Theme.accent : "transparent"; radius: Theme.radiusSm }
            }
        }
    }
}
