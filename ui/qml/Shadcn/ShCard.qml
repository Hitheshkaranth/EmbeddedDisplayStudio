/**
 * ShCard.qml
 * Shadcn Card container component.
 * Implements CONTRACT sections 11.2 (geometry) and 7.1 (documentation).
 *
 * The card sizes itself to whatever it contains, so `ShCard { width: 400 }`
 * with a header and content is all a caller ever has to write.
 *
 * It used to be a bare Rectangle with no implicit height, which meant every
 * caller computed the card's height by hand from the ids of its own children.
 * Any caller that forgot got a zero-height card with header and content drawn
 * on top of each other at y=0 -- and Fallback.qml, the screen CONTRACT
 * section 7 requires to stay legible when everything else has failed, was one
 * of the callers that forgot.
 *
 * Why childrenRect rather than an internal Column: a Column needs the caller's
 * children reparented into it, which means a `default property alias` onto the
 * Column's data. That alias is resolved during instantiation, and the order is
 * not stable -- attaching Layout.fillWidth/fillHeight to the card was enough to
 * make the children land on the Rectangle instead, leaving an empty Column and
 * implicitHeight 0. childrenRect is computed from the real children whatever
 * order they arrived in, so the sizing cannot be knocked out that way.
 */
import QtQuick 2.15

Rectangle {
    id: root

    /**
     * @property {list<Object>} contentData
     * Default property for children. ShCardHeader and ShCardContent place
     * themselves; anything else is positioned by the caller.
     */
    default property alias contentData: root.data

    color: Theme.card
    radius: Theme.radiusXl
    border.color: Theme.border
    border.width: 1

    // Content-driven sizing. An explicit width/height, or a Layout attached
    // property, still wins: implicit sizes are only a default.
    implicitWidth: childrenRect.width
    implicitHeight: childrenRect.height

    // Note: QtQuick Rectangle has no CSS-style shadow without a DropShadow
    // effect, which would pull QtGraphicalEffects into every panel image. The
    // kit stays flat rather than paying that.
}
