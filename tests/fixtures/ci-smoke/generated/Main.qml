// Generated from .edsui; edit the source model, not this file.
import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Shadcn 1.0

Rectangle {
    id: root
    width: 1024
    height: 768
    color: "#101418"

    // ── Simulation clock injected by qml_generator (sim.* property values) ──
    property real _t: 0.0
    property real _ts: 0.0

    Timer {
        id: _simClock
        interval: 50
        repeat: true
        running: true
        onTriggered: { root._t += 0.05; root._ts += 0.01 }
    }

    // Fast sweep – attitude, speeds, heading, VSI, engines …
    function osc(lo, hi, phase) {
        return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(root._t + phase))
    }

    // Slow sweep – altitude, fuel quantity, baro, OAT (5x slower period).
    function osc_slow(lo, hi, phase) {
        return lo + (hi - lo) * (0.5 + 0.5 * Math.sin(root._ts + phase))
    }
    // ────────────────────────────────────────────────────────────────────────

    ShAttitude {
        id: attitude
        x: 0
        y: 0
        width: 1030
        height: 770
        pitch: osc(-20.0, 20.0, 0.0)
        roll: osc(-30.0, 30.0, 1.1)
        pixelsPerDegree: 4.0
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield
        x: 120
        y: 710
        width: 150
        height: 46
        label: "GROUND SPEED"
        value: Math.round(osc(80.0, 180.0, 0.3))
        units: "KTS"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    Image {
        id: image
        x: 10
        y: 690
        width: 90
        height: 70
        source: "../assets/flyvi_transparent_black_to_white.png"
        fillMode: Image.PreserveAspectFit
        smooth: true
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield2
        x: 880
        y: 10
        width: 150
        height: 46
        label: "ALTITUDE"
        value: Math.round(osc_slow(1000.0, 5000.0, 0.3))
        units: "FT"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield22
        x: 830
        y: 710
        width: 150
        height: 46
        label: "HEADING"
        value: Math.round(osc_slow(0.0, 359.0, 0.6))
        units: "DEG"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    Image {
        id: image2
        x: 940
        y: 690
        width: 80
        height: 70
        source: "../assets/EmbeddedDisplay_Studio Logo.png"
        fillMode: Image.PreserveAspectFit
        smooth: true
        opacity: 1.0
        visible: true
    }

    ShTape {
        id: tape
        x: 320
        y: 170
        width: 100
        height: 430
        value: osc(60.0, 200.0, 0.4)
        minimumValue: 0.0
        maximumValue: 250.0
        step: 10.0
        span: 60.0
        label: "IAS"
        units: "KTS"
        side: "left"
        opacity: 1.0
        visible: true
    }

    ShCompass {
        id: compass
        x: 10
        y: 480
        width: 180
        height: 180
        heading: Math.round(osc_slow(0.0, 359.0, 0.6))
        headingBug: osc_slow(0.0, 359.0, 0.9)
        course: -1.0
        opacity: 1.0
        visible: true
    }

    ShVSI {
        id: vsi
        x: 590
        y: 240
        width: 60
        height: 300
        value: osc(-1500.0, 1500.0, 1.2)
        range: 2000.0
        units: "FPM"
        opacity: 1.0
        visible: true
    }

    ShAnnunciator {
        id: annunciator
        x: 430
        y: 540
        width: 140
        height: 38
        text: "LOW FUEL"
        severity: "caution"
        lit: (Math.sin(root._t + 2.5) > 0)
        opacity: 1.0
        visible: true
    }

    ShFlightDirector {
        id: flightdirector
        x: 0
        y: 0
        width: 180
        height: 120
        pitchCommand: osc(-10.0, 10.0, 0.2)
        rollCommand: osc(-15.0, 15.0, 0.8)
        pitchLimit: 15.0
        rollLimit: 30.0
        active: true
        mode: "FD"
        opacity: 1.0
        visible: true
    }

    ShTurnCoordinator {
        id: turncoordinator
        x: 810
        y: 300
        width: 180
        height: 110
        turnRate: osc_slow(-3.0, 3.0, 0.3)
        slip: osc(-1.0, 1.0, 1.7)
        standardRate: 3.0
        slipLimit: 1.0
        opacity: 1.0
        visible: true
    }

    ShEngineBar {
        id: enginebar
        x: 10
        y: 130
        width: 76
        height: 190
        value: osc(50.0, 95.0, 0.0)
        minimumValue: 0.0
        maximumValue: 100.0
        cautionValue: 80.0
        warningValue: 90.0
        label: "N1"
        units: "%"
        opacity: 1.0
        visible: true
    }

    ShFuelQuantity {
        id: fuelquantity
        x: 840
        y: 70
        width: 190
        height: 130
        leftValue: osc_slow(10.0, 90.0, 0.0)
        rightValue: osc_slow(10.0, 90.0, 0.4)
        capacity: 100.0
        lowLevel: 15.0
        units: "KG"
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield3
        x: 450
        y: 490
        width: 150
        height: 46
        label: "OAT"
        value: Math.round(osc_slow(-20.0, 40.0, 2.0))
        units: "C"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield4
        x: 450
        y: 230
        width: 150
        height: 46
        label: "WIND"
        value: Math.round(osc(0.0, 50.0, 1.3))
        units: "KTS"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    ShFuelQuantity {
        id: fuelquantity2
        x: 220
        y: 630
        width: 190
        height: 130
        leftValue: osc_slow(5.0, 80.0, 1.0)
        rightValue: osc_slow(5.0, 80.0, 1.6)
        capacity: 100.0
        lowLevel: 15.0
        units: "KG"
        opacity: 1.0
        visible: true
    }

    ShEngineBar {
        id: enginebar3
        x: 90
        y: 130
        width: 76
        height: 190
        value: osc(50.0, 95.0, 0.7)
        minimumValue: 0.0
        maximumValue: 100.0
        cautionValue: 80.0
        warningValue: 90.0
        label: "N2"
        units: "%"
        opacity: 1.0
        visible: true
    }

    ShDataField {
        id: datafield42
        x: 190
        y: 10
        width: 150
        height: 46
        label: "BARO"
        value: Math.round(osc_slow(29.5, 30.5, 0.9))
        units: "inHg"
        severity: "advisory"
        stacked: true
        opacity: 1.0
        visible: true
    }

    ShCard {
        id: card
        x: 750
        y: 430
        width: 270
        height: 250
        color: "#18181b"
        border.color: "#27272a"
        border.width: 1
        radius: 10
        opacity: 1.0
        visible: true

        ShEngineGauge {
            id: enginegauge
            x: 20
            y: 10
            width: 100
            height: 110
            value: osc(20.0, 80.0, 0.0)
            minimumValue: 0.0
            maximumValue: 100.0
            greenLow: 20.0
            greenHigh: 70.0
            cautionHigh: 85.0
            label: "OIL PRESS"
            units: "PSI"
            opacity: 1.0
            visible: true
        }

        ShEngineGauge {
            id: enginegauge2
            x: 20
            y: 130
            width: 100
            height: 110
            value: osc(30.0, 90.0, 0.5)
            minimumValue: 0.0
            maximumValue: 100.0
            greenLow: 20.0
            greenHigh: 70.0
            cautionHigh: 85.0
            label: "OIL TEMP"
            units: "C"
            opacity: 1.0
            visible: true
        }

        ShEngineGauge {
            id: enginegauge22
            x: 150
            y: 130
            width: 100
            height: 110
            value: osc(30.0, 90.0, 1.0)
            minimumValue: 0.0
            maximumValue: 100.0
            greenLow: 20.0
            greenHigh: 70.0
            cautionHigh: 85.0
            label: "OIL TEMP"
            units: "C"
            opacity: 1.0
            visible: true
        }

        ShEngineGauge {
            id: enginegauge222
            x: 150
            y: 10
            width: 100
            height: 110
            value: osc(20.0, 80.0, 1.5)
            minimumValue: 0.0
            maximumValue: 100.0
            greenLow: 20.0
            greenHigh: 70.0
            cautionHigh: 85.0
            label: "OIL PRESS"
            units: "PSI"
            opacity: 1.0
            visible: true
        }
    }

    Text {
        id: text
        x: 440
        y: 120
        width: 140
        height: 32
        text: "Flyvi Tech Pvt Ltd"
        font.pixelSize: 18
        font.bold: false
        color: "#f4f4f5"
        horizontalAlignment: Text.AlignLeft
        verticalAlignment: Text.AlignTop
        wrapMode: Text.NoWrap
        opacity: 1.0
        visible: true
    }
}
