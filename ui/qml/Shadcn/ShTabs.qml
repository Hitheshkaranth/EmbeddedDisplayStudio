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
    
    Column {
        anchors.fill: parent
        spacing: Theme.spacing8
        
        Rectangle {
            id: tabList
            width: parent.width
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
                        width: tabList.width / root.model.length - (Theme.spacing4 * 2) / root.model.length
                        height: parent.height
                        
                        Rectangle {
                            anchors.fill: parent
                            radius: Theme.radiusMd
                            color: root.currentIndex === index ? Theme.background : "transparent"
                            
                            Text {
                                anchors.centerIn: parent
                                text: modelData
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSm
                                font.weight: Theme.fontMedium
                                color: root.currentIndex === index ? Theme.foreground : Theme.mutedForeground
                            }
                            
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    root.currentIndex = index;
                                    root.tabChanged(index);
                                }
                            }
                        }
                    }
                }
            }
        }
        
        Item {
            id: contentArea
            width: parent.width
            height: parent.height - tabList.height - parent.spacing
        }
    }
}
