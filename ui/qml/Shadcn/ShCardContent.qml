/**
 * ShCardContent.qml
 * Shadcn Card Content component.
 * Implements CONTRACT sections 11.2 (padding 24, top 0) and 7.1.
 *
 * Sits below whatever was declared before it in the card and sizes itself to
 * its own children.
 *
 * Previously it anchored left and right but never top or bottom, and had no
 * implicit height: a zero-height item pinned at y=0, drawn over the header,
 * with its children outside the card's measured extent. Every caller that
 * worked did so by writing `anchors.top: someHeaderId.bottom` by hand and
 * naming an id that belonged to a sibling -- which the fallback screen, the
 * README's example and any new app were all free to forget.
 */
import QtQuick 2.15

Item {
    id: root

    // Null-guarded for the same reason as ShCardHeader: content is usually a
    // child of ShCard but must survive standalone instantiation.
    anchors.left: parent ? parent.left : undefined
    anchors.right: parent ? parent.right : undefined

    // shadcn card content is p-6 pt-0: the section above already supplied the
    // top whitespace, so repeating it here would double the gap.
    anchors.leftMargin: Theme.spacing24
    anchors.rightMargin: Theme.spacing24
    implicitHeight: childrenRect.height + Theme.spacing24

    /**
     * Anchors this item below the sibling declared before it, or to the top of
     * the card when it is the first thing in it.
     *
     * Args:    none (reads parent.children)
     * Returns: nothing
     * Side effects: assigns anchors.top, once, at construction.
     *
     * Done in JavaScript because the previous sibling is not nameable from a
     * declarative binding: the header is the caller's object, declared in the
     * caller's file, and requiring every caller to give it an id and repeat it
     * here is exactly the manual step that kept going wrong.
     */
    function _anchorBelowPreviousSibling() {
        if (!parent)
            return;
        var siblings = parent.children;
        var previous = null;
        for (var i = 0; i < siblings.length; ++i) {
            if (siblings[i] === root)
                break;
            // Skip non-visual children (attached objects, timers, models).
            if (siblings[i] && siblings[i].height !== undefined)
                previous = siblings[i];
        }
        if (previous)
            anchors.top = previous.bottom;
        else
            anchors.top = parent.top;
    }

    Component.onCompleted: _anchorBelowPreviousSibling()
}
