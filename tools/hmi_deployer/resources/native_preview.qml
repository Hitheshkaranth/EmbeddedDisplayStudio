/**
 * native_preview.qml
 * Layer: 3 (Host Deployer)
 * Purpose: what the bezel shows for a runtime="python" bundle while its
 * preview starts, and instead of it when the preview cannot run.
 *
 * A Qt Widgets application is normally rendered live here: native_preview.py
 * runs it unmodified in a child process at the target resolution and streams
 * frames into the bezel, and the first frame replaces this card. This is what
 * remains on screen when that is not possible -- a PySide2 bundle on a machine
 * with no PySide2 interpreter, or an application that never opens a window.
 * The reason is written to the console panel; this card says what is loaded so
 * the screen is never simply blank.
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
            title: "Starting the preview"
            description: "This application is being rendered off-screen at the "
                       + "target resolution; the first frame replaces this "
                       + "card. If it stays, the console below says why - "
                       + "usually a PySide2 bundle with no PySide2 interpreter "
                       + "on this machine, which still deploys and runs on the "
                       + "panel's own Qt5 runtime."
        }
    }
}
