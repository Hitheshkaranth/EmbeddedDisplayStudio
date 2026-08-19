/**
 * ShIcon.qml
 * Icon component rendering Tabler Icons from vendored SVG data.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15
import "TablerIcons.js" as IconRegistry

Item {
    id: root
    
    /**
     * @property {string} name
     * The icon name.
     */
    property string name: ""
    
    /**
     * @property {int} size
     * Size in pixels. Defaults to 18.
     */
    property int size: 18
    
    /**
     * @property {color} color
     * Icon color. Defaults to Theme.foreground.
     */
    property color color: Theme.foreground
    
    implicitWidth: size
    implicitHeight: size
    
    Image {
        id: iconImg
        anchors.fill: parent
        source: {
            if (root.name === "") return "";
            var svgData = IconRegistry.icons[root.name];
            if (!svgData) {
                console.warn("ShIcon: Unknown icon name '" + root.name + "'");
                return "";
            }
            // Replace currentColor with hex
            var colorStr = root.color.toString();
            svgData = svgData.replace(/currentColor/g, colorStr);
            return "data:image/svg+xml;utf8," + encodeURIComponent(svgData);
        }
        visible: source !== ""
        fillMode: Image.PreserveAspectFit
    }
    
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.color: Theme.destructive
        border.width: 1
        visible: root.name !== "" && iconImg.source === ""
        
        Text {
            anchors.centerIn: parent
            text: "?"
            color: Theme.destructive
            font.pixelSize: Math.max(8, root.size - 4)
        }
    }
}
