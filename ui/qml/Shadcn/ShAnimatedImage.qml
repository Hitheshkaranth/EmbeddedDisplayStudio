/**
 * ShAnimatedImage.qml
 * Animated image -- Basic kit widget: a moving picture (an animated GIF the
 * user supplies, e.g. a wireframe truck that turns) played by QtQuick's
 * AnimatedImage.
 *
 *   source    the .gif, relative to the file that sets it (the generator
 *             writes "../assets/truck.gif" from the design's "assets/truck.gif")
 *   playing   true plays, false holds the current frame (bindable)
 *   speed     playback speed in percent; 100 = the timing the file states
 *   fillMode  Image.PreserveAspectFit / PreserveAspectCrop / Stretch
 *
 * With no source, or one that cannot be read, a neutral placeholder is drawn
 * instead: a muted card with a framed "play" glyph and "GIF" under it. The
 * same placeholder is drawn by native/hmi-ui/src/widgets/w_shanimatedimage.c
 * and by the Designer canvas (designer/canvas/widget_previews.py), so all
 * three agree on what an empty widget looks like.
 */
import QtQuick 2.15

Item {
    id: root
    implicitWidth: 240
    implicitHeight: 160

    property url source: ""
    property bool playing: true
    property int speed: 100
    property int fillMode: Image.PreserveAspectFit

    // Qt 6 resolves a relative url where it is used, not where it was set:
    // the inner AnimatedImage would look for "../assets/truck.gif" next to
    // this file. Resolve it against the file that set it (root's context is
    // the page that instantiated this component), as a plain Image would.
    readonly property url _resolved: String(root.source) === "" ? "" : Qt.resolvedUrl(root.source, root)
    readonly property bool _shown: String(root.source) !== ""
                                   && movie.status !== AnimatedImage.Error
                                   && movie.status !== AnimatedImage.Null

    AnimatedImage {
        id: movie
        anchors.fill: parent
        source: root._resolved
        fillMode: root.fillMode === Image.PreserveAspectCrop || root.fillMode === Image.Stretch
                  ? root.fillMode : Image.PreserveAspectFit
        // Paused, not stopped: a stopped AnimatedImage rewinds to frame 0,
        // the panel's lv_gif_pause holds the frame on screen.
        playing: movie.status === AnimatedImage.Ready
        paused: !root.playing
        speed: Math.max(1, root.speed) / 100.0
        clip: true
        smooth: true
        visible: root._shown
    }

    // -- the placeholder (no source, or an unreadable one) ------------------
    Item {
        id: placeholder
        anchors.fill: parent
        visible: !root._shown

        readonly property real _s: Math.min(Math.max(1, root.width), Math.max(1, root.height))
        readonly property int _glyph: Math.max(12, Math.min(64, Math.round(_s * 0.30)))
        readonly property int _glyphW: Math.round(_glyph * 1.35)
        readonly property int _textPx: Math.max(10, Math.min(18, Math.round(_s * 0.11)))
        readonly property int _gap: Math.round(_glyph * 0.18)
        readonly property int _top: Math.round((root.height - (_glyph + _gap + _textPx)) / 2)

        Rectangle {
            anchors.fill: parent
            radius: 6
            color: Theme.muted
            border.color: Theme.border
            border.width: 1
        }

        // A picture frame with a play triangle: "a moving picture goes here".
        Rectangle {
            id: frame
            x: Math.round((root.width - placeholder._glyphW) / 2)
            y: placeholder._top
            width: placeholder._glyphW
            height: placeholder._glyph
            radius: 3
            color: "transparent"
            border.color: Theme.mutedForeground
            border.width: 2
        }

        Canvas {
            id: play
            anchors.fill: frame
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var th = height * 0.45, tw = th * 0.85;
                var cx = width / 2, cy = height / 2;
                ctx.fillStyle = Theme.mutedForeground;
                ctx.beginPath();
                ctx.moveTo(cx - tw / 3, cy - th / 2);
                ctx.lineTo(cx - tw / 3, cy + th / 2);
                ctx.lineTo(cx + 2 * tw / 3, cy);
                ctx.closePath();
                ctx.fill();
            }
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            Connections {
                target: Theme
                function onModeChanged() { play.requestPaint(); }
            }
        }

        Text {
            x: 0
            width: root.width
            y: placeholder._top + placeholder._glyph + placeholder._gap
            height: placeholder._textPx
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            text: "GIF"
            color: Theme.mutedForeground
            font.family: Theme.fontFamily
            font.pixelSize: placeholder._textPx
            font.weight: Font.DemiBold
        }
    }
}
