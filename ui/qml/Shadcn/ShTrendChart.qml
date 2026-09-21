/**
 * ShTrendChart.qml
 * History trend chart with grid lines, value trace, and severity zones.
 * Designed for continuous process monitoring in industrial HMI.
 */
import QtQuick 2.15

Item {
    id: root

    /** @property {var} data Array of numeric values to plot */
    property var data: []
    /** @property {real} minValue Y-axis minimum */
    property real minValue: 0
    /** @property {real} maxValue Y-axis maximum */
    property real maxValue: 100
    /** @property {real} warningLow Lower warning threshold */
    property real warningLow: 20
    /** @property {real} warningHigh Upper warning threshold */
    property real warningHigh: 80
    /** @property {int} maxPoints Maximum data points to display */
    property int maxPoints: 100
    /** @property {string} label Chart label */
    property string label: ""
    /** @property {string} unit Y-axis unit label */
    property string unit: ""
    /** @property {color} lineColor Line color */
    property color lineColor: Theme.brand
    /** @property {color} fillColor Fill gradient color */
    property color fillColor: Theme.brand
    /** @property {real} lineWidth Line width */
    property real lineWidth: 2

    implicitWidth: 300
    implicitHeight: 180

    readonly property int _visiblePoints: Math.min(root.data.length, root.maxPoints)
    readonly property real _yScale: 1.0 / (root.maxValue - root.minValue > 0 ? root.maxValue - root.minValue : 1)

    readonly property color _gridColor: Theme.border
    readonly property color _warnZoneColor: Qt.rgba(Theme.warning.r, Theme.warning.g, Theme.warning.b, 0.08)

    // Everything the face painter needs, values and colours alike; the
    // painter (faces/canvas or faces/native) never reads Theme itself.
    readonly property var _spec: ({
        data: root.data, minValue: root.minValue, maxValue: root.maxValue,
        maxPoints: root.maxPoints, lineWidth: root.lineWidth,
        lineColor: root.lineColor, fillColor: root.fillColor, background: Theme.background
    })

    // `data` (public API: the sample array) shadows Item's default property
    // of the same name, so children declared in the body would be assigned
    // to the array and never become visual children. The visual tree is
    // therefore held by a named property and parented explicitly.
    property Item _body: Item {
        parent: root
        anchors.fill: parent   // re-evaluated once parent is set

    Column {
        anchors.fill: parent
        spacing: 0

        Text {
            visible: root.label !== ""
            text: root.label
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXs
            font.weight: Theme.fontMedium
            color: Theme.mutedForeground
            elide: Text.ElideRight
        }

        Item {
            id: chartArea
            width: parent ? parent.width : root.implicitWidth
            height: root.implicitHeight - (root.label !== "" ? 18 : 0)
            clip: true

            Rectangle {
                anchors.fill: parent
                color: Theme.background
                border.color: Theme.border
                border.width: 1
                radius: Theme.radiusSm
            }

            // Warning zone background
            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                height: parent.height * (1 - (root.warningHigh - root.warningLow) * root._yScale)
                y: parent.height * (root.maxValue - root.warningHigh) * root._yScale
                color: root._warnZoneColor
            }

            // Horizontal grid lines
            Repeater {
                model: 5
                delegate: Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    height: 1
                    y: (index / 4) * parent.height
                    color: root._gridColor
                    opacity: 0.5
                }
            }

            // Y-axis labels
            Repeater {
                model: 5
                delegate: Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 2
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: (parent.height / 4) * (3 - index * 2)
                    text: Number(root.maxValue - (index / 4) * (root.maxValue - root.minValue)).toFixed(0)
                    font.family: Theme.fontFamily
                    font.pixelSize: 9
                    color: Theme.mutedForeground
                }
            }

            // Trend line path: faces/canvas/TrendChartFace.qml, or the C++
            // twin when the loader registered Shadcn.Native (Theme.nativeFaces).
            Loader {
                anchors.fill: parent
                anchors.margins: 2
                source: Theme.face("TrendChart")
                onLoaded: item.spec = Qt.binding(function() { return root._spec })
            }

            // Unit label
            Text {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: 4
                text: root.unit
                font.family: Theme.fontFamily
                font.pixelSize: 9
                color: Theme.mutedForeground
                visible: root.unit !== ""
            }
        }
    }
    }
}
