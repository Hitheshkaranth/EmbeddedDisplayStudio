/**
 * ShInput.qml
 * Shadcn Text Input component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {string} text
     * The text in the input. Defaults to empty string.
     */
    property alias text: textInput.text
    
    /**
     * @property {string} placeholderText
     * Placeholder shown when input is empty. Defaults to empty string.
     */
    property string placeholderText: ""
    
    /**
     * @property {bool} enabled
     * Whether the input is editable. Defaults to true.
     */
    property bool enabled: true
    
    /**
     * @property {bool} readOnly
     * Whether the input is read-only. Defaults to false.
     */
    property bool readOnly: false
    
    /**
     * @signal accepted
     * Emitted when Return or Enter is pressed.
     */
    signal accepted()
    
    // No explicit `textChanged` signal: QML already generates one from the
    // `text` property, and declaring it by hand is a duplicate-signal error
    // that breaks compilation of this file and therefore the module import.
    // Consumers bind to onTextChanged as usual.

    implicitWidth: 200
    implicitHeight: 36
    
    opacity: enabled ? 1.0 : 0.5
    
    Rectangle {
        id: bgRect
        anchors.fill: parent
        color: "transparent"
        radius: Theme.radiusMd
        border.color: textInput.activeFocus ? Theme.ring : Theme.input
        border.width: 1
        
        Behavior on border.color { ColorAnimation { duration: Theme.colorTransition } }
    }
    
    Rectangle {
        id: focusRing
        anchors.fill: parent
        color: "transparent"
        border.color: Theme.ring
        border.width: 1
        radius: Theme.radiusMd
        visible: textInput.activeFocus
    }

    Text {
        anchors.fill: parent
        anchors.leftMargin: Theme.spacing12
        anchors.rightMargin: Theme.spacing12
        verticalAlignment: Text.AlignVCenter
        text: root.placeholderText
        color: Theme.mutedForeground
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        visible: textInput.text === "" && !textInput.activeFocus
    }

    TextInput {
        id: textInput
        anchors.fill: parent
        anchors.leftMargin: Theme.spacing12
        anchors.rightMargin: Theme.spacing12
        verticalAlignment: TextInput.AlignVCenter
        color: Theme.foreground
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        enabled: root.enabled
        readOnly: root.readOnly
        clip: true
        
        onAccepted: root.accepted()
        onTextChanged: root.textChanged()
    }
}
