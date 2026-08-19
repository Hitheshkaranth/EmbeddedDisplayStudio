/**
 * ShDialog.qml
 * Shadcn Modal Dialog component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    // Item already declares `visible` as a FINAL property, so it must be
    // assigned, not redeclared: redeclaring it aborts compilation of this file
    // and, because the type is listed in qmldir, breaks the whole Shadcn module
    // import for every consumer. Dialogs start hidden.
    visible: false
    
    /**
     * @property {string} title
     * Dialog title text.
     */
    property string title: ""
    
    /**
     * @property {string} description
     * Dialog description text.
     */
    property string description: ""
    
    /**
     * @property {list<Object>} contentData
     * Default property for children.
     */
    default property alias contentData: contentArea.data
    
    /**
     * @signal accepted
     * Emitted when user accepts.
     */
    signal accepted()
    
    /**
     * @signal rejected
     * Emitted when user dismisses/cancels.
     */
    signal rejected()

    anchors.fill: parent
    z: 999
    opacity: visible ? 1.0 : 0.0
    enabled: visible
    
    Behavior on opacity { NumberAnimation { duration: 150 } }
    
    MouseArea {
        id: overlay
        anchors.fill: parent
        
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.8)
        }
        
        onClicked: {
            root.visible = false;
            root.rejected();
        }
    }
    
    Rectangle {
        id: panel
        width: Math.min(parent.width - 40, 500)
        height: column.implicitHeight + Theme.spacing48
        anchors.centerIn: parent
        radius: Theme.radiusLg
        color: Theme.background
        border.color: Theme.border
        border.width: 1
        
        MouseArea {
            anchors.fill: parent
            onClicked: {} // Prevent click-through
        }
        
        Column {
            id: column
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.spacing24
            spacing: Theme.spacing8
            
            Text {
                text: root.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLg
                font.weight: Theme.fontSemibold
                color: Theme.foreground
                wrapMode: Text.WordWrap
                width: parent.width
            }
            
            Text {
                text: root.description
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                color: Theme.mutedForeground
                wrapMode: Text.WordWrap
                width: parent.width
                visible: root.description !== ""
            }
            
            Item {
                id: contentArea
                width: parent.width
                height: childrenRect.height
            }
        }
        
        Rectangle {
            width: 24; height: 24
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: Theme.spacing16
            color: "transparent"
            radius: Theme.radiusSm
            
            Text {
                anchors.centerIn: parent
                text: "X"
                color: Theme.mutedForeground
                font.pixelSize: Theme.fontSizeSm
            }
            
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    root.visible = false;
                    root.rejected();
                }
            }
        }
    }
}
