/**
 * ShCardHeader.qml
 * Shadcn Card Header component.
 * Implements CONTRACT sections 11.2 (padding 24) and 7.1 (documentation).
 *
 * A Column so the title and description stack, pinned to the top of the card.
 */
import QtQuick 2.15

Column {
    id: root

    /**
     * @property {int} spacing
     * Gap between title and description, in px (shadcn: space-y-1.5).
     */
    spacing: Theme.spacing8

    // Null-guarded: a header is normally a child of ShCard, but it must also be
    // instantiable standalone (previews, tests, dynamic creation) where parent
    // is null at construction time. Unguarded parent.left throws a TypeError.
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined
    anchors.top: parent ? parent.top : undefined

    // shadcn card headers use a uniform p-6.
    padding: Theme.spacing24
}
