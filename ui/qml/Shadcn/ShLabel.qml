/**
 * ShLabel.qml
 * Shadcn simple label component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Text {
    id: root
    
    /**
     * @property {string} text
     * The text of the label.
     */
    // `text` is inherited from Text. Redeclaring it shadows the base
    // member: Qt warns, and the inherited text-metrics bindings
    // (implicitWidth/implicitHeight) would stop tracking the string.
    
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeSm
    font.weight: Theme.fontMedium
    color: Theme.foreground
}
