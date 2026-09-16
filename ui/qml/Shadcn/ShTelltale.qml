/**
 * ShTelltale.qml
 * Telltale -- Automotive cluster widget. CONTRACT STUB: the property API
 * below is fixed; the visuals are still to be drawn.
 */
import QtQuick 2.15

Item {
    id: root

    property string icon: "bulb"
    property string color: "amber"
    property bool lit: true
    property bool blink: false
    property string label: ""

    implicitWidth: 48
    implicitHeight: 48

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: Theme.autoPanel
        border.color: Theme.autoTileBorder
        Text {
            anchors.centerIn: parent
            text: "Telltale"
            color: Theme.autoMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
        }
    }
}
