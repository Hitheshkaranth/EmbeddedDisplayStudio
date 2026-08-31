/**
 * ShButton.qml
 * Shadcn Button component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {string} text
     * The text displayed on the button. Defaults to empty string.
     */
    property string text: ""
    
    /**
     * @property {string} variant
     * Visual variant of the button (default/secondary/destructive/outline/ghost/link). Defaults to "default".
     */
    property string variant: "default"
    
    /**
     * @property {string} size
     * Size of the button (default/sm/lg/icon). Defaults to "default".
     */
    property string size: "default"

    // Optional designer overrides. Empty colors preserve the theme/variant,
    // so existing hand-written QML continues to look exactly as before.
    property color backgroundColor: "transparent"
    property color textColor: "transparent"
    property color borderColor: "transparent"
    property int borderWidth: 0
    property real cornerRadius: Theme.radiusMd
    
    /**
     * @property {bool} enabled
     * Whether the button is interactive. Defaults to true.
     */
    // `enabled` is inherited from Item. Redeclaring it would shadow the
    // base member, so a caller setting `enabled: false` and this file's
    // own hover/opacity logic would read two different properties.
    
    /**
     * @property {bool} pressed
     * Readonly. True when the button is actively pressed.
     */
    readonly property bool pressed: mouseArea.pressed
    
    /**
     * @property {bool} hovered
     * Readonly. True when the pointer is hovering over the button.
     */
    readonly property bool hovered: mouseArea.containsMouse
    
    /**
     * @signal clicked
     * Emitted when the button is clicked.
     */
    signal clicked()

    implicitWidth: size === "icon" ? 36 : textElement.implicitWidth + (size === "sm" ? 24 : size === "lg" ? 48 : 32)
    implicitHeight: size === "sm" ? 32 : size === "lg" ? 40 : 36
    
    opacity: enabled ? 1.0 : 0.5
    
    Rectangle {
        id: bgRect
        anchors.fill: parent
        radius: root.cornerRadius
        
        color: {
            if (root.backgroundColor.a > 0) return root.backgroundColor
            if (variant === "default") return root.hovered ? Qt.rgba(Theme.primary.r, Theme.primary.g, Theme.primary.b, 0.9) : Theme.primary
            if (variant === "secondary") return root.hovered ? Qt.rgba(Theme.secondary.r, Theme.secondary.g, Theme.secondary.b, 0.8) : Theme.secondary
            if (variant === "destructive") return root.hovered ? Qt.rgba(Theme.destructive.r, Theme.destructive.g, Theme.destructive.b, 0.9) : Theme.destructive
            if (variant === "outline" || variant === "ghost") return root.hovered ? Theme.accent : "transparent"
            return "transparent"
        }
        
        border.color: root.borderColor.a > 0 ? root.borderColor : (variant === "outline" ? Theme.border : "transparent")
        border.width: root.borderWidth > 0 ? root.borderWidth : (variant === "outline" ? 1 : 0)
        
        Behavior on color { ColorAnimation { duration: Theme.colorTransition } }
    }
    
    Text {
        id: textElement
        anchors.centerIn: parent
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.weight: Theme.fontMedium
        font.underline: variant === "link" && root.hovered
        
        color: {
            if (root.textColor.a > 0) return root.textColor
            if (variant === "default") return Theme.primaryForeground
            if (variant === "secondary") return Theme.secondaryForeground
            if (variant === "destructive") return Theme.destructiveForeground
            if (variant === "outline" || variant === "ghost") return root.hovered ? Theme.accentForeground : Theme.foreground
            if (variant === "link") return Theme.primary
            return Theme.foreground
        }
        
        Behavior on color { ColorAnimation { duration: Theme.colorTransition } }
    }
    
    Rectangle {
        id: focusRing
        anchors.fill: parent
        anchors.margins: -2
        color: "transparent"
        border.color: Theme.ring
        border.width: 2
        radius: root.cornerRadius + 2
        visible: root.activeFocus
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: root.enabled
        enabled: root.enabled
        onClicked: {
            root.forceActiveFocus()
            root.clicked()
        }
    }
    
    Keys.onSpacePressed: if (root.enabled) root.clicked()
    Keys.onReturnPressed: if (root.enabled) root.clicked()
}
