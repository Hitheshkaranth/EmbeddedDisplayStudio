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
                        ColumnLayout {
                            width: parent.width
                            spacing: 24

                            // Bus.value() returns the fallback for a tag that is missing,
                            // null, or not published yet -- see CONTRACT 2.5.
                            ShGauge {
                                Layout.fillWidth: true
                                // ShCard sizes to its content, so the gauge
                                // states the height it wants rather than
                                // stretching into leftover card space.
                                Layout.preferredHeight: 260
                                // Safely retrieve ai.pot, fallback to 0.0 if not present
                                value: Bus.value("ai.pot", 0.0)
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
                                    let v = Bus.value("ai.pot", null);
                                    return v !== null ? Number(v).toFixed(2) : "--";
                                }
                                label: "Raw Voltage"
                                unit: "V"
                                state: {
                                    let v = Bus.value("ai.pot", 0.0);
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
                        ColumnLayout {
                            width: parent.width
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
                                    state: Bus.value("di.estop", false) ? "fault" : "ok"
                                }
                                ShLabel {
                                    text: Bus.value("di.estop", false) ? "ENGAGED" : "CLEAR"
                                    color: Bus.value("di.estop", false) ? Theme.destructive : Theme.success
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
                                    checked: Bus.value("do.relay1", false)
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
