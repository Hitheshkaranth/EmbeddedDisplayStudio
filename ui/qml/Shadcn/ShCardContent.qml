/**
 * ShCardContent.qml
 * Shadcn Card Content component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {list<Object>} contentData
     * Default property for children.
     */
    default property alias contentData: root.data
    
    // Null-guarded for the same reason as ShCardHeader: content is usually a
    // child of ShCard but must survive standalone instantiation.
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined

    anchors.leftMargin: Theme.spacing24
    anchors.rightMargin: Theme.spacing24
    anchors.bottomMargin: Theme.spacing24
}
