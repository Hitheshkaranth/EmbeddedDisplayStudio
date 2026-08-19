/**
 * ShCard.qml
 * Shadcn Card container component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Rectangle {
    id: root
    
    /**
     * @property {list<Object>} contentData
     * Default property for children.
     */
    default property alias contentData: root.data
    
    color: Theme.card
    radius: Theme.radiusXl
    border.color: Theme.border
    border.width: 1
    
    // Note: QtQuick Rectangle does not support CSS shadows natively without DropShadow effect.
    // We provide a visual approximation or leave flat depending on Qt version, avoiding graphical effects.
}
