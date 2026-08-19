"""
ui/gallery.py
Layer: Shared design system
Purpose: QML gallery window that instantiates EVERY component in ui/qml/Shadcn.
Flags: --theme light|dark, --screenshot PATH, --exit-after MS.
Implements CONTRACT section 7.1.
"""

import sys
import argparse
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QGuiApplication, QImage, QColor
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from ui.python.shadcn import qml_import_path
from ui.icons.tabler_icons import TABLER_ICONS

def build_qml_source() -> str:
    """
    Builds the QML source string containing the gallery.
    
    Returns:
        str: The complete QML source code.
    """
    # List of QML strings, one for each icon, to be injected into the GridLayout
    icons_qml_parts = []
    for icon_name in TABLER_ICONS.keys():
        icons_qml_parts.append(
            f'ColumnLayout {{ spacing: 4; ShIcon {{ name: "{icon_name}"; Layout.alignment: Qt.AlignHCenter }} ShLabel {{ text: "{icon_name}"; font.pixelSize: 10; Layout.alignment: Qt.AlignHCenter }} }}'
        )
    # The final concatenated QML snippet containing all icon layouts
    icons_qml = "\n                        ".join(icons_qml_parts)
    
    return f"""
import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Layouts 1.15
import Shadcn 1.0

Window {{
    id: window
    width: 1400 // Width in px for the gallery window
    height: 1200 // Height in px for the gallery window
    visible: true
    title: "Shadcn QML Gallery"
    color: Theme.background
    
    // Switch theme on load
    // The visual theme of the gallery, e.g. "dark" or "light"
    property string themeMode: Theme.mode
    onThemeModeChanged: Theme.mode = themeMode

    Flickable {{
        anchors.fill: parent
        anchors.bottomMargin: 24
        contentWidth: layout.width
        contentHeight: layout.height
        clip: true
        
        Flow {{
            id: layout
            width: parent.width - 48
            spacing: 24 // Spacing in px
            anchors.margins: 24
            anchors.top: parent.top
            anchors.left: parent.left
            
            // Buttons
            // ShCard requires manual height calculation because it does not use a layout internally.
            // We calculate implicitHeight from the header and content, plus bottom margin padding.
            ShCard {{
                width: 400
                implicitHeight: btnHeader.height + btnContent.height + Theme.spacing24
                ShCardHeader {{ id: btnHeader; ShCardTitle {{ text: "Buttons" }} }}
                ShCardContent {{
                    id: btnContent
                    anchors.top: btnHeader.bottom
                    implicitHeight: btnLayout.implicitHeight
                    ColumnLayout {{
                        id: btnLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        RowLayout {{
                            ShButton {{ text: "Default"; variant: "default" }}
                            ShButton {{ text: "Secondary"; variant: "secondary" }}
                            ShButton {{ text: "Destructive"; variant: "destructive" }}
                        }}
                        RowLayout {{
                            ShButton {{ text: "Outline"; variant: "outline" }}
                            ShButton {{ text: "Ghost"; variant: "ghost" }}
                            ShButton {{ text: "Link"; variant: "link" }}
                        }}
                        RowLayout {{
                            ShButton {{ text: "sm"; size: "sm" }}
                            ShButton {{ text: "default"; size: "default" }}
                            ShButton {{ text: "lg"; size: "lg" }}
                            ShButton {{ size: "icon"; ShIcon {{ name: "plus"; anchors.centerIn: parent ? parent : undefined }} }}
                        }}
                        RowLayout {{
                            ShButton {{ text: "Disabled"; enabled: false }}
                        }}
                    }}
                }}
            }}
            
            // Inputs
            ShCard {{
                width: 400
                implicitHeight: inHeader.height + inContent.height + Theme.spacing24
                ShCardHeader {{ id: inHeader; ShCardTitle {{ text: "Inputs" }} }}
                ShCardContent {{
                    id: inContent
                    anchors.top: inHeader.bottom
                    implicitHeight: inLayout.implicitHeight
                    ColumnLayout {{
                        id: inLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        ShInput {{ placeholderText: "Empty input..." }}
                        ShInput {{ text: "Filled input" }}
                        ShInput {{ placeholderText: "Disabled input"; enabled: false }}
                    }}
                }}
            }}

            // Badges
            ShCard {{
                width: 400
                implicitHeight: bgHeader.height + bgContent.height + Theme.spacing24
                ShCardHeader {{ id: bgHeader; ShCardTitle {{ text: "Badges" }} }}
                ShCardContent {{
                    id: bgContent
                    anchors.top: bgHeader.bottom
                    implicitHeight: bgLayout.implicitHeight
                    ColumnLayout {{
                        id: bgLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        RowLayout {{
                            ShBadge {{ text: "Default"; variant: "default" }}
                            ShBadge {{ text: "Secondary"; variant: "secondary" }}
                            ShBadge {{ text: "Destructive"; variant: "destructive" }}
                        }}
                        RowLayout {{
                            ShBadge {{ text: "Outline"; variant: "outline" }}
                            ShBadge {{ text: "Success"; variant: "success" }}
                            ShBadge {{ text: "Warning"; variant: "warning" }}
                        }}
                    }}
                }}
            }}
            
            // Switch & Progress
            ShCard {{
                width: 400
                implicitHeight: swHeader.height + swContent.height + Theme.spacing24
                ShCardHeader {{ id: swHeader; ShCardTitle {{ text: "Switch & Progress" }} }}
                ShCardContent {{
                    id: swContent
                    anchors.top: swHeader.bottom
                    implicitHeight: swLayout.implicitHeight
                    ColumnLayout {{
                        id: swLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        RowLayout {{
                            ShSwitch {{ checked: false }}
                            ShSwitch {{ checked: true }}
                            ShSwitch {{ checked: true; enabled: false }}
                        }}
                        ShProgress {{ value: 0.25; Layout.fillWidth: true }}
                        ShProgress {{ value: 0.50; Layout.fillWidth: true }}
                        ShProgress {{ value: 0.75; Layout.fillWidth: true }}
                        ShProgress {{ indeterminate: true; Layout.fillWidth: true }}
                    }}
                }}
            }}
            
            // Separator & Alert
            ShCard {{
                width: 400
                implicitHeight: sepHeader.height + sepContent.height + Theme.spacing24
                ShCardHeader {{ id: sepHeader; ShCardTitle {{ text: "Separator & Alert" }} }}
                ShCardContent {{
                    id: sepContent
                    anchors.top: sepHeader.bottom
                    implicitHeight: sepLayout.implicitHeight
                    ColumnLayout {{
                        id: sepLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        ShSeparator {{ orientation: Qt.Horizontal; Layout.fillWidth: true }}
                        ShAlert {{ title: "Default Alert"; description: "This is a default alert." }}
                        ShAlert {{ title: "Destructive Alert"; description: "This is a destructive alert."; variant: "destructive" }}
                    }}
                }}
            }}
            
            // Tabs, Labels, Skeletons
            ShCard {{
                width: 400
                implicitHeight: tabHeader.height + tabContent.height + Theme.spacing24
                ShCardHeader {{ id: tabHeader; ShCardTitle {{ text: "Tabs, Labels, Skeletons" }} }}
                ShCardContent {{
                    id: tabContent
                    anchors.top: tabHeader.bottom
                    implicitHeight: tabLayout.implicitHeight
                    ColumnLayout {{
                        id: tabLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        ShTabs {{ model: ["Tab 1", "Tab 2", "Tab 3"]; currentIndex: 1 }}
                        ShLabel {{ text: "This is a standard label" }}
                        ShSkeleton {{ width: 100; height: 20 }}
                    }}
                }}
            }}

            // HMI Additions
            ShCard {{
                width: 400
                implicitHeight: hmiHeader.height + hmiContent.height + Theme.spacing24
                ShCardHeader {{ id: hmiHeader; ShCardTitle {{ text: "HMI Additions" }} }}
                ShCardContent {{
                    id: hmiContent
                    anchors.top: hmiHeader.bottom
                    implicitHeight: hmiLayout.implicitHeight
                    ColumnLayout {{
                        id: hmiLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        ShGauge {{ value: 42; minValue: 0; maxValue: 100; unit: "V"; label: "Voltage"; Layout.fillWidth: true }}
                        RowLayout {{
                            ShStatDot {{ state: "idle" }}
                            ShStatDot {{ state: "ok" }}
                            ShStatDot {{ state: "warn" }}
                            ShStatDot {{ state: "fault" }}
                        }}
                        ShValueTile {{ value: "42.0"; label: "Voltage"; unit: "V"; state: "ok"; Layout.fillWidth: true }}
                    }}
                }}
            }}
            
            // Dialog (inline for display)
            ShCard {{
                width: 400
                implicitHeight: dlgHeader.height + dlgContent.height + Theme.spacing24
                ShCardHeader {{ id: dlgHeader; ShCardTitle {{ text: "Dialog Component" }} }}
                ShCardContent {{
                    id: dlgContent
                    anchors.top: dlgHeader.bottom
                    implicitHeight: dlgLayout.implicitHeight
                    ColumnLayout {{
                        id: dlgLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        ShDialog {{
                            id: dummyDialog
                            title: "Test Dialog"
                            description: "This is a test dialog."
                        }}
                        ShButton {{
                            text: "Show Dialog"
                            onClicked: dummyDialog.visible = true
                        }}
                    }}
                }}
            }}

            // Icons
            ShCard {{
                width: parent.width
                implicitHeight: icoHeader.height + icoContent.height + Theme.spacing24
                ShCardHeader {{ id: icoHeader; ShCardTitle {{ text: "Icons" }} }}
                ShCardContent {{
                    id: icoContent
                    anchors.top: icoHeader.bottom
                    implicitHeight: icoLayout.implicitHeight
                    Flow {{
                        id: icoLayout
                        anchors.left: parent.left
                        anchors.right: parent.right
                        spacing: 12
                        {icons_qml}
                    }}
                }}
            }}
        }}
    }}
}}
"""

def main() -> None:
    """
    Main entry point for the gallery.
    Parses arguments, setups up QGuiApplication, loads QML, takes screenshot, and exits.
    
    Exits:
        0 on success, -1 on QML load failure.
    """
    parser = argparse.ArgumentParser(description="Shadcn QML Gallery")
    parser.add_argument("--theme", choices=["light", "dark"], default="dark", help="Theme to render")
    parser.add_argument("--screenshot", type=str, help="Path to save screenshot")
    parser.add_argument("--exit-after", type=int, default=0, help="Milliseconds to wait before exiting")
    args = parser.parse_args()

    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    engine.addImportPath(qml_import_path())
    
    qml_src = build_qml_source()
    engine.loadData(qml_src.encode('utf-8'))
    
    if not engine.rootObjects():
        sys.exit(-1)
        
    root_window = engine.rootObjects()[0]
    root_window.setProperty("themeMode", args.theme)
    
    def on_timeout() -> None:
        """
        Timer callback to take screenshot and exit.
        """
        if args.screenshot:
            img = root_window.grabWindow()
            img.save(args.screenshot)
            print(f"Screenshot saved to {args.screenshot}")
        app.quit()
        
    if args.exit_after > 0:
        QTimer.singleShot(args.exit_after, on_timeout)
        
    sys.exit(app.exec())

if __name__ == "__main__":
    main()