/**
 * Theme.qml
 * Singleton for the Shadcn UI theme tokens.
 * Implements CONTRACT section 7.1.
 */
pragma Singleton
import QtQuick 2.15

QtObject {
    id: root

    /**
     * @property {string} mode
     * The color mode of the application ('light' or 'dark'). Defaults to 'light'.
     */
    property string mode: "light"

    /** @property {color} background */
    readonly property color background: mode === "light" ? "#ffffff" : "#09090b"
    /** @property {color} foreground */
    readonly property color foreground: mode === "light" ? "#020817" : "#ecedee"
    /** @property {color} card */
    readonly property color card: mode === "light" ? "#ffffff" : "#18181b"
    /** @property {color} cardForeground */
    readonly property color cardForeground: mode === "light" ? "#020817" : "#ecedee"
    /** @property {color} popover */
    readonly property color popover: mode === "light" ? "#ffffff" : "#18181b"
    /** @property {color} popoverForeground */
    readonly property color popoverForeground: mode === "light" ? "#020817" : "#ecedee"
    /** @property {color} primary */
    readonly property color primary: mode === "light" ? "#0f172a" : "#006fee"
    /** @property {color} primaryForeground */
    readonly property color primaryForeground: mode === "light" ? "#f8fafc" : "#ffffff"
    /** @property {color} secondary */
    readonly property color secondary: mode === "light" ? "#f1f5f9" : "#27272a"
    /** @property {color} secondaryForeground */
    readonly property color secondaryForeground: mode === "light" ? "#0f172a" : "#ecedee"
    /** @property {color} muted */
    readonly property color muted: mode === "light" ? "#f1f5f9" : "#27272a"
    /** @property {color} mutedForeground */
    readonly property color mutedForeground: mode === "light" ? "#64748b" : "#a1a1aa"
    /** @property {color} accent */
    readonly property color accent: mode === "light" ? "#f1f5f9" : "#3f3f46"
    /** @property {color} accentForeground */
    readonly property color accentForeground: mode === "light" ? "#0f172a" : "#ffffff"
    /** @property {color} destructive */
    readonly property color destructive: mode === "light" ? "#ef4444" : "#f31260"
    /** @property {color} destructiveForeground */
    readonly property color destructiveForeground: mode === "light" ? "#f8fafc" : "#ffffff"
    /** @property {color} border */
    readonly property color border: mode === "light" ? "#e2e8f0" : "#00000000"
    /** @property {color} input */
    readonly property color input: mode === "light" ? "#e2e8f0" : "#27272a"
    /** @property {color} ring */
    readonly property color ring: mode === "light" ? "#020817" : "#006fee"
    /** @property {color} success */
    readonly property color success: mode === "light" ? "#22c55e" : "#17c964"
    /** @property {color} successForeground */
    readonly property color successForeground: mode === "light" ? "#f8fafc" : "#f8fafc"
    /** @property {color} warning */
    readonly property color warning: mode === "light" ? "#f59e0b" : "#f5a524"
    /** @property {color} warningForeground */
    readonly property color warningForeground: mode === "light" ? "#f8fafc" : "#f8fafc"
    /** @property {color} info */
    readonly property color info: mode === "light" ? "#3b82f6" : "#006fee"
    /** @property {color} infoForeground */
    readonly property color infoForeground: mode === "light" ? "#f8fafc" : "#f8fafc"

    /** @property {real} radiusSm */
    readonly property real radiusSm: 4
    /** @property {real} radiusMd */
    readonly property real radiusMd: 12
    /** @property {real} radiusLg */
    readonly property real radiusLg: 16
    /** @property {real} radiusXl */
    readonly property real radiusXl: 20
    /** @property {real} radiusFull */
    readonly property real radiusFull: 9999

    /** @property {real} spacing4 */
    readonly property real spacing4: 4
    /** @property {real} spacing8 */
    readonly property real spacing8: 8
    /** @property {real} spacing12 */
    readonly property real spacing12: 12
    /** @property {real} spacing16 */
    readonly property real spacing16: 16
    /** @property {real} spacing24 */
    readonly property real spacing24: 24
    /** @property {real} spacing32 */
    readonly property real spacing32: 32
    /** @property {real} spacing48 */
    readonly property real spacing48: 48

    /** @property {string} fontFamily */
    readonly property string fontFamily: "Inter,Noto Sans,DejaVu Sans,sans-serif"
    /** @property {int} fontSizeXs */
    readonly property int fontSizeXs: 12
    /** @property {int} fontSizeSm */
    readonly property int fontSizeSm: 14
    /** @property {int} fontSizeBase */
    readonly property int fontSizeBase: 16
    /** @property {int} fontSizeLg */
    readonly property int fontSizeLg: 18
    /** @property {int} fontSizeXl */
    readonly property int fontSizeXl: 20
    /** @property {int} fontSizeXxl */
    readonly property int fontSizeXxl: 24
    /** @property {int} fontSizeXxxl */
    readonly property int fontSizeXxxl: 30

    /** @property {int} fontNormal */
    readonly property int fontNormal: 400
    /** @property {int} fontMedium */
    readonly property int fontMedium: 500
    /** @property {int} fontSemibold */
    readonly property int fontSemibold: 600
    /** @property {real} headingLetterSpacing */
    readonly property real headingLetterSpacing: -0.4

    /** @property {string} shadowSm */
    readonly property string shadowSm: "0 1px 2px 0 rgb(0 0 0 / 0.05)"
    /** @property {string} shadowMd */
    readonly property string shadowMd: "0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)"
    /** @property {string} shadowLg */
    readonly property string shadowLg: "0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)"

    /** @property {int} colorTransition */
    readonly property int colorTransition: 150
}
