/**
 * ShTabs.qml
 * Shadcn Tabs component.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15

Item {
    id: root
    
    /**
     * @property {var} model
     * Array of string titles for the tabs.
     */
    property var model: []
    
    /**
     * @property {int} currentIndex
     * Index of the currently selected tab. Defaults to 0.
     */
    property int currentIndex: 0
    
    /**
     * @property {list<Object>} contentData
     * Default property for tab contents.
     */
    default property alias contentData: contentArea.data
    
    /**
     * @signal tabChanged
     * Emitted when the tab changes, provides the index.
     */
    signal tabChanged(int index)

    implicitWidth: 400
    implicitHeight: 300
    
    Rectangle {
            id: tabList
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 36
            radius: Theme.radiusLg
            color: Theme.muted
            
            Row {
                anchors.fill: parent
                anchors.margins: Theme.spacing4
                spacing: 0
                
                Repeater {
                    model: root.model
                    delegate: Item {
                        width: root.model.length > 0
                            ? (tabList.width - Theme.spacing8) / root.model.length : 0
                        height: parent.height
                        activeFocusOnTab: true
                        
                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusMd
                            color: root.currentIndex === index ? Theme.background : "transparent"
                            
                            Text {
                                anchors.centerIn: parent
                                width: Math.max(0, parent.width - Theme.spacing8)
                                horizontalAlignment: Text.AlignHCenter
                                elide: Text.ElideRight
                                text: modelData
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSm
                                font.weight: Theme.fontMedium
                                color: root.currentIndex === index ? Theme.foreground : Theme.mutedForeground
                            }
                            
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    parent.parent.forceActiveFocus();
                                    root.currentIndex = index;
                                    root.tabChanged(index);
                                }
                            }
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -1
                            color: "transparent"
                            border.color: Theme.ring
                            border.width: 2
                            radius: Theme.radiusMd
                            visible: parent.activeFocus
                        }

                        Keys.onSpacePressed: activate()
                        Keys.onReturnPressed: activate()
                        Keys.onLeftPressed: moveFocus(-1)
                        Keys.onRightPressed: moveFocus(1)

                        function activate() {
                            root.currentIndex = index
                            root.tabChanged(index)
                        }
                        function moveFocus(delta) {
                            if (root.model.length === 0) return
                            var next = (index + delta + root.model.length) % root.model.length
                            root.currentIndex = next
                            root.tabChanged(next)
                            var nextItem = parent.children[next]
                            if (nextItem) nextItem.forceActiveFocus()
                        }
                    }
                }
            }
        }
        
    Item {
            id: contentArea
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: tabList.bottom
            anchors.topMargin: Theme.spacing8
            anchors.bottom: parent.bottom
    }
}
