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

    ShAttitude {
        id: attitude
        x: 0
        y: 0
        width: 1030
        height: 770
        pitch: 0.0
        roll: 0.0
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
        value: "130"
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
        label: "GROUND SPEED"
        value: "130"
        units: "KTS"
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
        label: "GROUND SPEED"
        value: "130"
        units: "KTS"
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
        value: 127.0
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
        heading: 359.0
        headingBug: 45.0
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
        value: 0.0
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
        lit: true
        opacity: 1.0
        visible: true
    }

    ShFlightDirector {
        id: flightdirector
        x: 0
        y: 0
        width: 180
        height: 120
        pitchCommand: 3.0
        rollCommand: -5.0
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
        turnRate: 0.0
        slip: 0.0
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
        value: 68.0
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
        leftValue: 64.0
        rightValue: 61.0
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
        label: "GROUND SPEED"
        value: "130"
        units: "KTS"
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
        label: "GROUND SPEED"
        value: "130"
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
        leftValue: 64.0
        rightValue: 61.0
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
        value: 68.0
        minimumValue: 0.0
        maximumValue: 100.0
        cautionValue: 80.0
        warningValue: 90.0
        label: "N1"
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
        label: "GROUND SPEED"
        value: "130"
        units: "KTS"
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
            value: 55.0
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
            value: 55.0
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
            id: enginegauge22
            x: 150
            y: 130
            width: 100
            height: 110
            value: 55.0
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
            id: enginegauge222
            x: 150
            y: 10
            width: 100
            height: 110
            value: 55.0
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
