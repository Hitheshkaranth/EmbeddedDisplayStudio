/**
 * ShProgress.qml
 * Shadcn Progress bar component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {real} value
     * Progress value between 0.0 and 1.0. Defaults to 0.0.
     */
    property real value: 0.0
    
    /**
     * @property {bool} indeterminate
     * True if the progress is indeterminate. Defaults to false.
     */
    property bool indeterminate: false
    
    implicitWidth: 200
    implicitHeight: 8
    
    Rectangle {
        id: track
        anchors.fill: parent
        radius: Theme.radiusFull
        color: Theme.secondary
        clip: true
        
        Rectangle {
            id: indicator
            height: parent.height
            radius: Theme.radiusFull
            color: Theme.primary
            
            width: root.indeterminate ? parent.width * 0.3 : parent.width * Math.max(0, Math.min(1, root.value))
            
            x: root.indeterminate ? (animator.running ? x : 0) : 0
            
            SequentialAnimation on x {
                id: animator
                running: root.indeterminate
                loops: Animation.Infinite
                NumberAnimation { from: -indicator.width; to: track.width; duration: 1000 }
            }
            
            Behavior on width {
                enabled: !root.indeterminate
                NumberAnimation { duration: 250; easing.type: Easing.OutCubic }
            }
        }
    }
}
