/**
 * ShCompass.qml
 * Heading rose with a fixed lubber line, a selected-heading bug and an
 * optional course needle.
 *
 * The card rotates by -heading so the number under the lubber line is the
 * heading being flown, which is the convention every other instrument on the
 * panel is read against.
 */
import QtQuick 2.15

Item {
    id: root

    property real heading: 0
    /** Selected heading. Negative hides the bug. */
    property real headingBug: -1
    /** Course/track needle in degrees. Negative hides it. */
    property real course: -1

    implicitWidth: 220
    implicitHeight: 220

    Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: Theme.efisPanel
        border.color: Theme.border
        border.width: 1
    }

    // Colours the card painter needs; it never reads Theme itself.
    readonly property var _spec: ({ line: Theme.efisLine, text: Theme.efisText })

    // Card painter: faces/canvas/CompassFace.qml, or the C++ twin when the
    // loader registered Shadcn.Native (Theme.nativeFaces). The card rotates
    // as a whole; the painting does not depend on the heading.
    Loader {
        id: card
        anchors.fill: parent
        rotation: -root.heading
        source: Theme.face("Compass")
        onLoaded: item.spec = Qt.binding(function() { return root._spec })
    }

    // Course needle, rotating with the card.
    Rectangle {
        visible: root.course >= 0
        width: 3
        height: parent.height * 0.62
        color: Theme.efisNav
        anchors.centerIn: parent
        rotation: root.course - root.heading
        transformOrigin: Item.Center
    }

    // Selected-heading bug, rotating with the card.
    Rectangle {
        visible: root.headingBug >= 0
        width: 14
        height: 10
        color: Theme.efisBug
        x: parent.width / 2 - 7
        y: 2
        transform: Rotation {
            origin.x: 7
            origin.y: root.height / 2 - 2
            angle: root.headingBug - root.heading
        }
    }

    // Fixed lubber line and the aircraft at the centre.
    Rectangle {
        width: 2; height: 14
        color: Theme.efisAircraft
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
    }
    Rectangle {
        width: 30; height: 2
        color: Theme.efisAircraft
        anchors.centerIn: parent
    }
}
