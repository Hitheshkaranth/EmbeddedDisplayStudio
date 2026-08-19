/**
 * ShBadge.qml
 * Shadcn Badge component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Rectangle {
    id: root
    
    /**
     * @property {string} text
     * Text displayed on the badge.
     */
    property string text: ""
    
    /**
     * @property {string} variant
     * Visual variant (default/secondary/destructive/outline/success/warning). Defaults to "default".
     */
    property string variant: "default"
    
    implicitWidth: textElement.implicitWidth + 20
    implicitHeight: 20
    
    radius: Theme.radiusFull
    
    color: {
        if (variant === "default") return Theme.primary
        if (variant === "secondary") return Theme.secondary
        if (variant === "destructive") return Theme.destructive
        if (variant === "success") return Theme.success
        if (variant === "warning") return Theme.warning
        return "transparent"
    }
    
    border.color: variant === "outline" ? Theme.foreground : "transparent"
    border.width: variant === "outline" ? 1 : 0
    
    Text {
        id: textElement
        anchors.centerIn: parent
        text: root.text
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeXs
        font.weight: Theme.fontSemibold
        
        color: {
            if (variant === "default") return Theme.primaryForeground
            if (variant === "secondary") return Theme.secondaryForeground
            if (variant === "destructive") return Theme.destructiveForeground
            if (variant === "success") return Theme.successForeground
            if (variant === "warning") return Theme.warningForeground
            if (variant === "outline") return Theme.foreground
            return Theme.foreground
        }
    }
}
