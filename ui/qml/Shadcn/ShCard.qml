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
 *
 * Style options (off by default: a card without them draws as it always did):
 *   headerHeight > 0  a title band across the top headerHeight px, in
 *                     headerColor (unset = the card colour lighter by 12 %),
 *                     under the border, with the card's top corner radius and
 *                     square bottom corners; its last row is a 1 px divider in
 *                     the border colour.
 *   fillGradient      (the Designer's "gradient") the fill runs from the card
 *                     colour lighter by 6 % at the top to the card colour at
 *                     the bottom. Rectangle already has a `gradient`, hence
 *                     the name; the generator maps it.
 * Both are drawn with the Rectangle's own gradient (hard stops for the band),
 * so they add no child: the caller's children and childrenRect are untouched.
 * native/hmi-ui/src/widgets/w_shcard.c draws the same.
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

    property int headerHeight: 0
    property color headerColor: "transparent"
    property bool fillGradient: false

    color: Theme.card
    radius: Theme.radiusXl
    border.color: Theme.border
    border.width: 1

    // Content-driven sizing. An explicit width/height, or a Layout attached
    // property, still wins: implicit sizes are only a default.
    implicitWidth: childrenRect.width
    implicitHeight: childrenRect.height

    // -- style: header band and gradient fill ---------------------------------
    readonly property bool _banded: headerHeight > border.width && height > 0
    readonly property color _top: fillGradient ? Theme.shade(color, 6) : color
    readonly property color _band: headerColor.a > 0 ? headerColor : Theme.shade(color, 12)
    // The fill colour at a fraction of the height (the gradient is linear).
    function _fillAt(p) {
        return Qt.rgba(_top.r + (color.r - _top.r) * p, _top.g + (color.g - _top.g) * p,
                       _top.b + (color.b - _top.b) * p, _top.a + (color.a - _top.a) * p)
    }
    readonly property real _divTop: _banded ? (headerHeight - 1) / height : 0
    readonly property real _divEnd: _banded ? headerHeight / height : 0
    readonly property real _eps: 0.0001

    property Gradient _plainGradient: Gradient {
        GradientStop { position: 0.0; color: root._top }
        GradientStop { position: 1.0; color: root.color }
    }
    property Gradient _bandGradient: Gradient {
        GradientStop { position: 0.0; color: root._band }
        GradientStop { position: root._divTop; color: root._band }
        GradientStop { position: root._divTop + root._eps; color: root.border.color }
        GradientStop { position: root._divEnd; color: root.border.color }
        GradientStop { position: Math.min(1, root._divEnd + root._eps); color: root._fillAt(root._divEnd) }
        GradientStop { position: 1.0; color: root.color }
    }
    gradient: _banded ? _bandGradient : (fillGradient ? _plainGradient : undefined)

    // Note: QtQuick Rectangle has no CSS-style shadow without a DropShadow
    // effect, which would pull QtGraphicalEffects into every panel image. The
    // kit stays flat rather than paying that.
}
