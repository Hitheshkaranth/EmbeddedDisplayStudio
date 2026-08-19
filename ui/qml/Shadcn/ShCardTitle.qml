/**
 * ShCardTitle.qml
 * Shadcn Card Title component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Text {
    id: root
    
    /**
     * @property {string} text
     * The title text.
     */
    // `text` is inherited from Text. Redeclaring it shadows the base
    // member: Qt warns, and the inherited text-metrics bindings
    // (implicitWidth/implicitHeight) would stop tracking the string.
    
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontSizeBase
    font.weight: Theme.fontSemibold
    font.letterSpacing: Theme.headingLetterSpacing
    color: Theme.cardForeground
    wrapMode: Text.WordWrap
}
