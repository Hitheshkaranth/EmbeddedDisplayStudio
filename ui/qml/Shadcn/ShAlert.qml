/**
 * ShAlert.qml
 * Shadcn Alert component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Rectangle {
    id: root
    
    /**
     * @property {string} title
     * The title of the alert.
     */
    property string title: ""
    
    /**
     * @property {string} description
     * The detailed description.
     */
    property string description: ""
    
    /**
     * @property {string} variant
     * Visual variant (default/destructive). Defaults to "default".
     */
    property string variant: "default"
    
    implicitWidth: 300
    implicitHeight: column.implicitHeight + Theme.spacing32
    
    radius: Theme.radiusLg
    color: "transparent"
    border.color: variant === "destructive" ? Theme.destructive : Theme.border
    border.width: 1
    
    Column {
        id: column
        anchors.fill: parent
        anchors.margins: Theme.spacing16
        spacing: Theme.spacing4
        
        Text {
            text: root.title
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.weight: Theme.fontMedium
            color: root.variant === "destructive" ? Theme.destructive : Theme.foreground
            wrapMode: Text.WordWrap
            width: parent.width
        }
        
        Text {
            text: root.description
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            color: root.variant === "destructive" ? Theme.destructive : Theme.mutedForeground
            wrapMode: Text.WordWrap
            width: parent.width
        }
    }
}
