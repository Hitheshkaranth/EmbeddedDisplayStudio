/**
 * ShSwitch.qml
 * Shadcn Toggle Switch component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {bool} checked
     * True if the switch is on. Defaults to false.
     */
    property bool checked: false
    
    /**
     * @property {bool} enabled
     * True if interactive. Defaults to true.
     */
    // `enabled` is inherited from Item. Redeclaring it would shadow the
    // base member, so a caller setting `enabled: false` and this file's
    // own hover/opacity logic would read two different properties.
    
    /**
     * @signal toggled
     * Emitted when the switch state changes.
     */
    signal toggled()

    implicitWidth: 36
    implicitHeight: 20
    opacity: enabled ? 1.0 : 0.5
    
    Rectangle {
        id: track
        anchors.fill: parent
        radius: Theme.radiusFull
        color: root.checked ? Theme.primary : Theme.input
        
        Behavior on color { ColorAnimation { duration: Theme.colorTransition } }
        
        Rectangle {
            id: thumb
            width: 16
            height: 16
            radius: Theme.radiusFull
            color: "#ffffff"
            anchors.verticalCenter: parent.verticalCenter
            x: root.checked ? root.width - width - 2 : 2
            
            Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.InOutQuad } }
        }
    }
    
    Rectangle {
        id: focusRing
        anchors.fill: parent
        anchors.margins: -2
        color: "transparent"
        border.color: Theme.ring
        border.width: 2
        radius: Theme.radiusFull + 2
        visible: root.activeFocus
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.enabled
        onClicked: {
            root.forceActiveFocus()
            root.checked = !root.checked
            root.toggled()
        }
    }
    
    Keys.onSpacePressed: if (root.enabled) { root.checked = !root.checked; root.toggled() }
}
