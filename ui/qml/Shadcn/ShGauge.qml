/**
 * ShGauge.qml
 * Analog radial arc gauge for HMI.
 * Implements CONTRACT section 7.1.
 */
import QtQuick 2.15
import QtQuick.Shapes 1.15

Item {
    id: root
    
    /** @property {real} value Current numeric process value */
    property real value: 0
    /** @property {real} minValue Minimum value of the gauge range */
    property real minValue: 0
    /** @property {real} maxValue Maximum value of the gauge range */
    property real maxValue: 100
    /** @property {string} unit Engineering unit label (e.g. '°C') */
    property string unit: ""
    /** @property {string} label Gauge title/description */
    property string label: ""
    /** @property {real} thresholdWarning Value at which the gauge indicates a warning */
    property real thresholdWarning: 75
    /** @property {real} thresholdFault Value at which the gauge indicates a fault */
    property real thresholdFault: 90
    
    implicitWidth: 120
    implicitHeight: 120
    
    /** 
     * @property {real} _clampedValue 
     * Internal property to ensure the sweep stays within the track.
     * Maps null/NaN/out-of-range to the minimum to safely animate.
     */
    property real _clampedValue: {
        if (typeof root.value !== "number" || isNaN(root.value)) return root.minValue;
        return Math.max(root.minValue, Math.min(root.maxValue, root.value));
    }
    
    /**
     * @property {real} _animatedValue
     * Smoothly sweeps the value arc instead of jumping.
     */
    property real _animatedValue: root._clampedValue
    Behavior on _animatedValue { 
        NumberAnimation { duration: Theme.colorTransition; easing.type: Easing.OutQuad } 
    }
    
    /**
     * @property {color} _valueColor
     * Determines the current semantic colour of the value arc based on thresholds.
     */
    property color _valueColor: {
        if (typeof root.value !== "number" || isNaN(root.value) || root.value < root.minValue || root.value > root.maxValue) return Theme.muted;
        if (root.value >= root.thresholdFault) return Theme.destructive;
        if (root.value >= root.thresholdWarning) return Theme.warning;
        return Theme.success;
    }
    Behavior on _valueColor { ColorAnimation { duration: Theme.colorTransition } }
    
    /**
     * @property {real} dim
     * Single dimension to enforce a 1:1 aspect ratio lock (circular shape),
     * regardless of how the layout stretches the parent Item.
     */
    property real dim: Math.min(width, height)
    
    Item {
        width: root.dim
        height: root.dim
        anchors.centerIn: parent
        
        Shape {
            anchors.fill: parent
            // Enable antialiasing natively
            antialiasing: true
            
            // Background track arc
            ShapePath {
                strokeColor: Theme.muted
                // Ensure stroke is at least 2px but scales with dimension
                strokeWidth: Math.max(2, root.dim * 0.1)
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                
                PathAngleArc {
                    centerX: root.dim / 2
                    centerY: root.dim / 2
                    // Radius subtracts half the stroke width to stay within bounds
                    radiusX: Math.max(0.1, root.dim / 2 - Math.max(2, root.dim * 0.1) / 2)
                    radiusY: Math.max(0.1, root.dim / 2 - Math.max(2, root.dim * 0.1) / 2)
                    // 135 degrees is the lower-left quadrant; providing a 270 sweep 
                    // creates a symmetric gauge that rests at the bottom and reads naturally.
                    startAngle: 135
                    sweepAngle: 270
                }
            }
            
            // Value indicator arc
            ShapePath {
                strokeColor: root._valueColor
                strokeWidth: Math.max(2, root.dim * 0.1)
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                
                PathAngleArc {
                    centerX: root.dim / 2
                    centerY: root.dim / 2
                    radiusX: Math.max(0.1, root.dim / 2 - Math.max(2, root.dim * 0.1) / 2)
                    radiusY: Math.max(0.1, root.dim / 2 - Math.max(2, root.dim * 0.1) / 2)
                    startAngle: 135
                    // Calculate sweep angle proportionally to animated value
                    sweepAngle: {
                        var range = root.maxValue - root.minValue;
                        if (range <= 0) return 0; // Guard against division by zero
                        var progress = (root._animatedValue - root.minValue) / range;
                        return 270 * progress;
                    }
                }
            }
        }
        
        Column {
            anchors.centerIn: parent
            // Prevent text from overlapping the arc by constraining its width
            width: parent.width * 0.7
            spacing: 2
            
            Text {
                width: parent.width
                text: root.label
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeXs
                color: Theme.mutedForeground
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
            
            Text {
                width: parent.width
                text: {
                    // Invalid, null or out-of-range value must render as "--"
                    if (typeof root.value !== "number" || isNaN(root.value)) return "--";
                    if (root.value < root.minValue || root.value > root.maxValue) return "--";
                    return Number(root.value).toFixed(1);
                }
                font.family: Theme.fontFamily
                // Scale text smoothly with the gauge dimension
                font.pixelSize: Math.max(Theme.fontSizeXs, root.dim * 0.18)
                font.weight: Theme.fontSemibold
                color: Theme.foreground
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
            
            Text {
                width: parent.width
                text: root.unit
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeXs
                color: Theme.mutedForeground
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
            }
        }
    }
}
