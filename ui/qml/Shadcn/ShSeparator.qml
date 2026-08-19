/**
 * ShSeparator.qml
 * Shadcn Separator line component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Rectangle {
    id: root
    
    /**
     * @property {int} orientation
     * Qt.Horizontal or Qt.Vertical. Defaults to Qt.Horizontal.
     */
    property int orientation: Qt.Horizontal
    
    color: Theme.border
    
    implicitWidth: orientation === Qt.Horizontal ? 200 : 1
    implicitHeight: orientation === Qt.Horizontal ? 1 : 200
}
