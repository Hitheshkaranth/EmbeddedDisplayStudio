/**
 * gui/shell/Fallback.qml
 * Layer: 2 (GUI Loader)
 * Purpose: Safe fallback screen shown when the app bundle fails to load or validate.
 * Prevents a black screen on failure (CONTRACT 7) and provides clear diagnostics.
 */

import QtQuick 2.15
import QtQuick.Layouts 1.15
import Shadcn 1.0

Rectangle {
    id: fallbackScreen
    color: Theme.background
    
    // Explicit sizing helps if not anchoring, though usually loaded by Loader
    anchors.fill: parent

    ShCard {
        // Named so tests/test_shell_render.py can assert this screen is
        // actually laid out; CONTRACT section 7 requires it to stay legible.
        objectName: "fallbackCard"
        width: 500
        anchors.centerIn: parent

        ShCardHeader {
            objectName: "fallbackHeader"
            ShCardTitle { 
                text: "Application Load Failed" 
            }
            ShCardDescription { 
                text: "The requested HMI application bundle could not be started." 
            }
        }

        ShCardContent {
            objectName: "fallbackContent"
            ColumnLayout {
                width: parent.width
                spacing: 16

                ShAlert {
                    objectName: "fallbackAlert"
                    Layout.fillWidth: true
                    title: "Validation Error"
                    description: Hmi.lastError
                    variant: "destructive"
                }

                ShSeparator {
                    Layout.fillWidth: true
                    orientation: Qt.Horizontal
                }

                GridLayout {
                    columns: 2
                    rowSpacing: 12
                    columnSpacing: 16
                    Layout.fillWidth: true

                    ShLabel {
                        text: "App Name:"
                        color: Theme.mutedForeground
                    }
                    ShLabel {
                        text: Hmi.appName
                        Layout.fillWidth: true
                    }

                    ShLabel {
                        text: "App Version:"
                        color: Theme.mutedForeground
                    }
                    ShLabel {
                        text: Hmi.appVersion
                        Layout.fillWidth: true
                    }

                    ShLabel {
                        text: "Bundle Path:"
                        color: Theme.mutedForeground
                    }
                    ShLabel {
                        // Displaying the expected entry path
                        text: Hmi.appEntryUrl.toString() !== "" ? Hmi.appEntryUrl.toString() : "Not available"
                        Layout.fillWidth: true
                        // Ensure long paths wrap if needed
                        wrapMode: Text.Wrap
                    }

                    ShLabel {
                        text: "Loader Version:"
                        color: Theme.mutedForeground
                    }
                    ShLabel {
                        text: "1.0.0" // Hardcoded loader version
                        Layout.fillWidth: true
                    }
                }

                ShSeparator {
                    Layout.fillWidth: true
                    orientation: Qt.Horizontal
                }

                RowLayout {
                    Layout.fillWidth: true
                    ShLabel {
                        text: "Hint: Use the deployer tool to push a new release."
                        color: Theme.mutedForeground
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
