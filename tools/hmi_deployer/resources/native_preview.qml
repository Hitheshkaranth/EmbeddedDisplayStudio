/**
 * native_preview.qml
 * Layer: 3 (Host Deployer)
 * Purpose: what the bezel shows for a bundle whose runtime is "python".
 *
 * A Qt Widgets application creates its own QApplication and its own top-level
 * window; it cannot be rendered inside this tool's QQuickWidget the way a QML
 * entry can. Rather than showing an empty screen and letting the user wonder
 * whether the import failed, the panel states plainly what kind of app is
 * loaded and where it will run.
 *
 * Context properties supplied by DevicePanel: appName, appEntry, appVersion.
 */
import QtQuick
import Shadcn 1.0

Rectangle {
    id: root
    color: Theme.background

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 96, 620)
        spacing: Theme.spacing16

        ShIcon {
            name: "device-desktop"
            size: 40
            color: Theme.mutedForeground
            anchors.horizontalCenter: parent.horizontalCenter
        }

        ShLabel {
            text: appName
            font.pixelSize: Theme.fontSizeXxl
            font.weight: Font.DemiBold
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
        }

        ShLabel {
            text: "Native Python application - entry " + appEntry
            color: Theme.mutedForeground
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
        }

        ShAlert {
            width: parent.width
            title: "Preview runs on the device"
            description: "A Qt Widgets app owns its own window and cannot be "
                       + "composited into this preview. Deploy it to see it on "
                       + "the panel; the bezel above still shows the target "
                       + "geometry it will run at."
        }
    }
}
