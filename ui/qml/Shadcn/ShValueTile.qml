/**
 * ShValueTile.qml
 * Large numeric readout tile for HMI dashboards.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

ShCard {
    id: root
    
    /** @property {string} value Value text */
    property string value: "--"
    /** @property {string} label Label text */
    property string label: "Label"
    /** @property {string} unit Unit text */
    property string unit: ""
    /** @property {string} state State (ok/warn/fault/idle) */
    property string state: "idle"
    
    implicitWidth: 200
    implicitHeight: 120
    
    ShCardContent {
        anchors.fill: parent
        anchors.margins: Theme.spacing16
        
        Column {
            // ShCardContent is itself a Column, and Qt refuses fill/centerIn
            // anchors on an item inside a Column (the layout would fight the
            // anchor and silently stop functioning). Width-following is the
            // supported way to stretch a child of a Column.
            width: parent ? parent.width : implicitWidth
            spacing: Theme.spacing8
            
            Row {
                width: parent.width
                
                Text {
                    text: root.label
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                    font.weight: Theme.fontMedium
                    color: Theme.mutedForeground
                    width: parent.width - badge.width
                    elide: Text.ElideRight
                }
                
                ShBadge {
                    id: badge
                    text: root.state.toUpperCase()
                    variant: root.state === "ok" ? "success" :
                             root.state === "warn" ? "warning" :
                             root.state === "fault" ? "destructive" : "secondary"
                }
            }
            
            Row {
                // A bottom anchor here would be an item-inside-a-Column anchor,
                // which makes Qt disable the enclosing Column's layout entirely
                // (silently collapsing the tile). Vertical rhythm comes from the
                // Column's own spacing instead.
                spacing: Theme.spacing4

                Text {
                    text: root.value
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeXxxl
                    font.weight: Theme.fontSemibold
                    color: Theme.foreground
                    anchors.baseline: unitText.baseline
                }
                
                Text {
                    id: unitText
                    text: root.unit
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                    color: Theme.mutedForeground
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                }
            }
        }
    }
}
