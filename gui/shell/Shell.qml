/**
 * gui/shell/Shell.qml
 * Layer: 2 (GUI Loader)
 * Purpose: Main window for the HMI loader.
 * Loads the customer app QML, handles load states (success/error),
 * and provides a global "link lost" banner when the hardware daemon is unreachable.
 * Implements CONTRACT Section 7 (Reliability rules).
 */

import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Layouts 1.15
import Shadcn 1.0

Window {
    id: root
    visible: true
    width: Hmi.screenWidth
    height: Hmi.screenHeight
    title: "HMI Loader"
    
    // Set fullscreen unless windowed mode was requested via CLI
    visibility: isWindowed ? Window.Windowed : Window.FullScreen

    // Set the theme on startup based on CLI arg (default dark)
    Component.onCompleted: {
        Theme.mode = initialTheme;
    }

    // Base background colour
    color: Theme.background

    // The main app loader
    Loader {
        id: appLoader
        anchors.fill: parent
        
        // If there's a validation error, Hmi.lastError is set and appEntryUrl might be empty
        source: Hmi.lastError === "" ? Hmi.appEntryUrl : ""
        
        onStatusChanged: {
            if (status === Loader.Ready) {
                // Tell the deployment pipeline we successfully loaded (Layer 3 atomic swap logic)
                Hmi.markReady();
            }
        }
    }

    // Fallback UI shown when the app fails to load or manifest validation fails
    Loader {
        id: fallbackLoader
        anchors.fill: parent
        active: appLoader.status === Loader.Error || appLoader.status === Loader.Null
        source: "Fallback.qml"
    }

    // Link lost banner, shown only when TagEngine loses connection to daemon
    // Placed at the top, z-indexed above the app so it's always visible but unobtrusive
    Rectangle {
        id: linkBanner
        width: 320
        height: bannerAlert.height
        anchors.top: parent.top
        anchors.topMargin: 24
        anchors.horizontalCenter: parent.horizontalCenter
        color: "transparent"
        z: 100
        
        // Only show if we've lost connection (and presumably the app is trying to run)
        visible: !Tags.online
        
        ShAlert {
            id: bannerAlert
            width: parent.width
            variant: "destructive"
            title: "Hardware Link Lost"
            description: "Telemetry stream stopped. Check daemon status."
        }
    }
}
