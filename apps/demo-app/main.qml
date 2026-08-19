/**
 * apps/demo-app/main.qml
 * Layer: 2 (GUI Loader Demo App)
 * Purpose: A reference customer application demonstrating integration with the Tag Engine
 * and the Shadcn UI kit. Used as a test fixture for the deployment pipeline.
 */

import QtQuick 2.15
import QtQuick.Layouts 1.15
import Shadcn 1.0

Rectangle {
    id: appRoot
    color: Theme.background
    width: 1280
    height: 800

    // Helper to safely get tag values with fallback
    // Since Tags is a QQmlPropertyMap, Tags.value(...) in QML conflicts with property reading,
    // so we use the built-in map indexing `Tags["key"]` or `Tags.key`
    function getTag(name, fallback) {
        // Replace dots with underscores to read from QQmlPropertyMap
        let alias = name.replace(/\./g, '_');
        let v = Tags[alias];
        return (v !== undefined && v !== null) ? v : fallback;
    }

    // Main layout
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 48 // Use Shadcn spacing scale
        spacing: 32

        // Header
        RowLayout {
            Layout.fillWidth: true
            
            ColumnLayout {
                spacing: 4
                ShLabel {
                    text: "Machine Dashboard"
                    font.pixelSize: 30 // 3xl
                    font.weight: Font.DemiBold
                }
                ShLabel {
                    text: "Demonstrating BYOA HMI Integration"
                    color: Theme.mutedForeground
                }
            }

            Item { Layout.fillWidth: true } // Spacer

            // Link state badge
            ShBadge {
                text: Tags.online ? "System Online" : "System Offline"
                variant: Tags.online ? "success" : "destructive"
            }
        }

        ShSeparator {
            Layout.fillWidth: true
            orientation: Qt.Horizontal
        }

        // Dashboard Content
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 32

            // Left column - Process Values
            ColumnLayout {
                Layout.fillHeight: true
                Layout.preferredWidth: 400
                spacing: 24

                ShCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ShCardHeader {
                        id: leftHeader
                        ShCardTitle { text: "Analog Sensors" }
                        ShCardDescription { text: "Real-time potentiometer reading" }
                    }

                    ShCardContent {
                        // ShCard is a plain Rectangle, so we must manually flow its Header and Content.
                        // We anchor Content below Header and let it fill the remaining card height.
                        anchors.top: leftHeader.bottom
                        anchors.bottom: parent.bottom
                        
                        ColumnLayout {
                            // Fills the ShCardContent area, avoiding 'width: parent.width' bindings.
                            anchors.fill: parent
                            spacing: 24

                            // Use getTag() to safely retrieve the tag with a fallback
                            ShGauge {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                // Safely retrieve ai.pot, fallback to 0.0 if not present
                                value: getTag("ai.pot", 0.0)
                                minValue: 0.0
                                maxValue: 3.3
                                unit: "V"
                                label: "Input Voltage"
                                thresholdWarning: 2.5
                                thresholdFault: 3.0
                            }
                            
                            ShValueTile {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 120
                                // Format the number safely
                                value: {
                                    let v = getTag("ai.pot", null);
                                    return v !== null ? Number(v).toFixed(2) : "--";
                                }
                                label: "Raw Voltage"
                                unit: "V"
                                state: {
                                    let v = getTag("ai.pot", 0.0);
                                    if (v > 3.0) return "fault";
                                    if (v > 2.5) return "warn";
                                    return "ok";
                                }
                            }
                        }
                    }
                }
            }

            // Right column - Controls and Safety
            ColumnLayout {
                Layout.fillHeight: true
                Layout.preferredWidth: 400
                spacing: 24

                ShCard {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ShCardHeader {
                        id: rightHeader
                        ShCardTitle { text: "Safety & Control" }
                        ShCardDescription { text: "Digital I/O interactions" }
                    }

                    ShCardContent {
                        // Position below header and fill the remaining card height
                        anchors.top: rightHeader.bottom
                        anchors.bottom: parent.bottom
                        
                        ColumnLayout {
                            // Fills the ShCardContent safely
                            anchors.fill: parent
                            spacing: 16

                            // E-Stop status
                            RowLayout {
                                Layout.fillWidth: true
                                ShLabel {
                                    text: "Emergency Stop"
                                    Layout.fillWidth: true
                                }
                                ShStatDot {
                                    // Default to false (safe) if tag is missing
                                    state: getTag("di.estop", false) ? "fault" : "ok"
                                }
                                ShLabel {
                                    text: getTag("di.estop", false) ? "ENGAGED" : "CLEAR"
                                    color: getTag("di.estop", false) ? Theme.destructive : Theme.success
                                    font.weight: Font.DemiBold
                                }
                            }
                            
                            ShSeparator { Layout.fillWidth: true; orientation: Qt.Horizontal }

                            // Relay control
                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 4
                                    ShLabel {
                                        text: "Main Relay"
                                    }
                                    ShLabel {
                                        text: "Controls do.relay1"
                                        color: Theme.mutedForeground
                                        font.pixelSize: 12 // xs
                                    }
                                }
                                
                                ShSwitch {
                                    // Safe read of the current state
                                    checked: getTag("do.relay1", false)
                                    // Commands go through Bus, never by assigning
                                    // to Tags: PySide6 cannot intercept writes to
                                    // a QQmlPropertyMap, so an assignment would
                                    // update the UI locally and never reach the
                                    // hardware. See tagengine.py's module note.
                                    onToggled: {
                                        Bus.write("do.relay1", checked);
                                    }
                                }
                            }
                            
                            ShSeparator { Layout.fillWidth: true; orientation: Qt.Horizontal }
                            
                            // Pulse button
                            RowLayout {
                                Layout.fillWidth: true
                                ShLabel {
                                    text: "Pulse Relay (500ms)"
                                    Layout.fillWidth: true
                                }
                                ShButton {
                                    text: "Pulse"
                                    variant: "outline"
                                    onClicked: {
                                        Bus.pulse("do.relay1", 500);
                                    }
                                }
                            }
                            
                            Item { Layout.fillHeight: true } // spacer to push controls up
                        }
                    }
                }
            }
            
            Item { Layout.fillWidth: true } // Right spacer
        }
    }
}
