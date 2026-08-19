/**
 * ShCardHeader.qml
 * Shadcn Card Header component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Column {
    id: root
    
    /**
     * @property {int} spacing
     * Spacing between items.
     */
    spacing: Theme.spacing8
    
    // Null-guarded: a header is normally a child of ShCard, but it must also be
    // instantiable standalone (previews, tests, dynamic creation) where parent
    // is null at construction time. Unguarded parent.left throws a TypeError.
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined
    anchors.top: parent ? parent.top : undefined

    padding: Theme.spacing24
}
