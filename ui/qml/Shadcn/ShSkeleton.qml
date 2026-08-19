/**
 * ShSkeleton.qml
 * Shadcn Skeleton loading component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Rectangle {
    id: root
    
    color: Theme.muted
    radius: Theme.radiusMd
    
    SequentialAnimation on opacity {
        loops: Animation.Infinite
        NumberAnimation { from: 0.5; to: 1.0; duration: 750; easing.type: Easing.InOutQuad }
        NumberAnimation { from: 1.0; to: 0.5; duration: 750; easing.type: Easing.InOutQuad }
    }
}
