/**
 * ShStatDot.qml
 * State LED indicator component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {string} state
     * Indicator state (ok/warn/fault/idle). Defaults to idle.
     */
    property string state: "idle"
    
    /**
     * @property {int} size
     * Diameter in pixels. Defaults to 12.
     */
    property int size: 12
    
    implicitWidth: size
    implicitHeight: size
    
    Rectangle {
        id: dot
        anchors.fill: parent
        radius: width / 2
        
        color: {
            if (root.state === "ok") return Theme.success
            if (root.state === "warn") return Theme.warning
            if (root.state === "fault") return Theme.destructive
            return Theme.mutedForeground
        }
        
        SequentialAnimation on opacity {
            running: root.state === "fault"
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 0.3; duration: 500 }
            NumberAnimation { from: 0.3; to: 1.0; duration: 500 }
        }
        
        opacity: root.state === "fault" ? 1.0 : 1.0 // Animation takes over if fault
    }
}
