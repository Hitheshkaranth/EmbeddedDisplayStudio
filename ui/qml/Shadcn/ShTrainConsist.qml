/**
 * ShTrainConsist.qml
 * Train Consist -- Rail widget. A top-down metro consist standing vertically:
 * the cars of ``cars`` stacked with small gaps, cab cars at both ends with a
 * rounded accent-trimmed nose, windscreen band and head/tail lights, two
 * columns of seats per car and a lock on the car behind the leading cab. Two
 * door bars stick out of each long side, coloured by ``doorsLeft`` /
 * ``doorsRight``: closed green (with a glow), open amber, disabled grey. A
 * bound door value may be a bool or number: true / 1 closed, false / 0 open.
 * Car names read bottom-to-top on the right; the two door captions on the
 * left, the part after the colon coloured by its door state.
 *
 * Twin of native/hmi-ui/src/widgets/w_shtrainconsist.c and
 * designer/canvas/rail/train_consist.py -- keep the geometry in step.
 */
import QtQuick

Item {
    id: root
    implicitWidth: 300
    implicitHeight: 880
    property string cars: 'MC1,M1,T1,T2,M2,MC2'
    property string doorsLeft: 'closed'
    property string doorsRight: 'disabled'
    property string leftLabel: 'DOORS L: CLOSED (SECURED)'
    property string rightLabel: 'DOORS R: DISABLED'
    property string accent: '#a855f7'

    // -- model ------------------------------------------------------------------
    function carList() {
        var out = []
        var parts = String(root.cars).split(",")
        for (var i = 0; i < parts.length && out.length < 16; ++i) {
            var s = parts[i].trim()
            if (s.length) out.push(s)
        }
        return out
    }
    function doorState(v) {
        var s = String(v).trim().toLowerCase()
        if (s === "closed" || s === "true" || s === "1") return "closed"
        if (s === "open" || s === "false" || s === "0") return "open"
        return "disabled"
    }
    function doorColour(v) {
        var s = doorState(v)
        return s === "closed" ? "#4ade80" : s === "open" ? "#f59e0b" : "#3f3f46"
    }
    function captionColour(v) {
        var s = doorState(v)
        return s === "closed" ? "#4ade80" : s === "open" ? "#f59e0b" : "#71717a"
    }
    function prefixOf(t) { var i = String(t).indexOf(":"); return i < 0 ? String(t) : String(t).slice(0, i + 1) }
    function statusOf(t) { var i = String(t).indexOf(":"); return i < 0 ? "" : String(t).slice(i + 1).trim() }

    // -- geometry (same numbers as the C face) ------------------------------------
    function ww() { return Math.max(1, root.width) }
    function hh() { return Math.max(1, root.height) }
    function n() { return root.carList().length }
    function bw() { return ww() * 0.30 }
    function bx() { return (ww() - bw()) / 2 }
    function trainTop() { return hh() * 0.015 }
    function gap() { return Math.max(2, hh() * 0.007) }
    function carH() { var k = n(); return k > 0 ? (hh() * 0.97 - gap() * (k - 1)) / k : hh() * 0.97 }
    function carY(i) { return trainTop() + i * (carH() + gap()) }
    function rN() { return Math.min(bw() * 0.42, carH() * 0.35) }
    function rs() { return Math.max(2, bw() * 0.07) }
    function outline() { return Math.max(1, Math.round(ww() * 0.005)) }
    function trim() { return Math.max(2, Math.round(ww() * 0.013)) }
    function doorW() { return Math.max(3, ww() * 0.027) }
    function doorH() { return carH() * 0.28 }
    // Passenger section of car i (below the leading nose, above the trailing
    // one), relative to the car's top.
    function secY(i) { return i === 0 ? rN() : 0 }
    function secH(i) { var h = carH(); if (i === 0) h -= rN(); if (i === n() - 1) h -= rN(); return h }
    function pitch(i) { return secH(i) * 0.76 / 3 }
    function carFont() { return Math.max(8, Math.round(Math.min(hh() * 0.025, ww() * 0.075))) }
    function capFont() { return Math.max(8, Math.round(Math.min(hh() * 0.0227, ww() * 0.067))) }
    function capLen(pre, post) {
        return pre.implicitWidth + (post.text.length ? capFont() * 0.3 + post.implicitWidth : 0)
    }

    // Doors (under the bodies, sticking out half their width): per car
    // left-upper, left-lower, right-upper, right-lower.
    Repeater {
        model: root.n() * 4
        delegate: Item {
            x: root.bx() + (index % 4 >= 2 ? root.bw() - root.doorW() * 0.45 : -root.doorW() * 0.55)
            y: root.carY(Math.floor(index / 4)) + root.secY(Math.floor(index / 4))
               + (root.secH(Math.floor(index / 4)) - 2 * root.doorH()) / 3 * (1 + index % 2)
               + (index % 2) * root.doorH()
            width: root.doorW(); height: root.doorH()
            Rectangle {   // the glow of a closed door
                visible: root.doorState(index % 4 >= 2 ? root.doorsRight : root.doorsLeft) === "closed"
                x: -root.doorW() * 0.6; y: -root.doorW() * 0.6
                width: parent.width + 1.2 * root.doorW(); height: parent.height + 1.2 * root.doorW()
                radius: Math.round(root.doorW())
                color: Qt.rgba(0.29, 0.871, 0.502, 0.22)
            }
            Rectangle {
                anchors.fill: parent
                radius: Math.round(Math.max(1, root.doorW() * 0.3))
                color: root.doorColour(index % 4 >= 2 ? root.doorsRight : root.doorsLeft)
            }
        }
    }

    // Bodies. A cab: the whole car rounded with the accent trim, the passenger
    // part laid over it with the plain outline, open towards the nose.
    Repeater {
        model: root.carList()
        delegate: Item {
            x: root.bx(); y: root.carY(index)
            width: root.bw(); height: root.carH()
            Rectangle {
                visible: index === 0 || index === root.n() - 1
                anchors.fill: parent
                radius: Math.round(root.rN())
                color: "#2a2a30"
                border.color: root.accent; border.width: root.trim()
            }
            Rectangle {
                y: index === 0 ? root.rN() : 0
                width: parent.width
                height: parent.height - (index === 0 ? root.rN() : 0) - (index === root.n() - 1 ? root.rN() : 0)
                radius: (index === 0 && index === root.n() - 1) ? 0 : Math.round(root.rs())
                color: "#2a2a30"
                border.color: "#3f3f46"; border.width: root.outline()
            }
            Rectangle {
                visible: index === 0
                x: root.outline(); y: root.rN()
                width: parent.width - 2 * root.outline(); height: root.outline() + 1
                color: "#2a2a30"
            }
            Rectangle {
                visible: index === root.n() - 1
                x: root.outline(); y: parent.height - root.rN() - root.outline() - 1
                width: parent.width - 2 * root.outline(); height: root.outline() + 1
                color: "#2a2a30"
            }
            // Windscreen bands.
            Rectangle {
                visible: index === 0
                x: parent.width * 0.16; y: root.rN() * 0.55
                width: parent.width * 0.68; height: Math.max(3, root.rN() * 0.32)
                radius: Math.round(height / 2); color: "#0c0c10"
            }
            Rectangle {
                visible: index === root.n() - 1
                x: parent.width * 0.16
                width: parent.width * 0.68; height: Math.max(3, root.rN() * 0.32)
                y: parent.height - root.rN() * 0.55 - height
                radius: Math.round(height / 2); color: "#0c0c10"
            }
        }
    }

    // Head lights (white) on the leading cab, tail lights (red) on the trailing one.
    Repeater {
        model: root.n() > 0 ? 4 : 0
        delegate: Rectangle {
            width: 2 * Math.max(1.5, root.bw() * 0.035); height: width; radius: width / 2
            x: root.bx() + root.bw() * (index % 2 ? 0.68 : 0.32) - width / 2
            y: (index < 2 ? root.carY(0) + root.rN() * 0.30
                          : root.carY(root.n() - 1) + root.carH() - root.rN() * 0.30) - height / 2
            color: index < 2 ? "#f4f4f5" : "#ef4444"
        }
    }

    // Seats: two columns of three per car.
    Repeater {
        model: root.n() * 6
        delegate: Rectangle {
            x: root.bx() + root.bw() * (index % 2 ? 0.62 : 0.14)
            width: root.bw() * 0.24
            height: root.pitch(Math.floor(index / 6)) * 0.62
            y: root.carY(Math.floor(index / 6)) + root.secY(Math.floor(index / 6))
               + root.secH(Math.floor(index / 6)) * 0.12
               + (Math.floor(index / 2) % 3) * root.pitch(Math.floor(index / 6))
               + (root.pitch(Math.floor(index / 6)) - height) / 2
            radius: Math.round(Math.max(1, width * 0.18))
            color: "#3a3a42"
        }
    }

    // The lock on the car behind the leading cab.
    ShIcon {
        visible: root.n() >= 3
        size: Math.round(Math.max(8, root.bw() * 0.24))
        name: "lock"
        color: "#d4d4d8"
        x: Math.round(root.bx() + root.bw() / 2 - size / 2)
        y: Math.round(root.carY(1) + root.secY(1) + root.secH(1) / 2 - size / 2)
    }

    // Car names, bottom-to-top, right of the train.
    Repeater {
        model: root.carList()
        delegate: Text {
            text: modelData
            color: "#a1a1aa"
            font.family: Theme.fontFamily
            font.pixelSize: root.carFont()
            font.weight: Theme.fontMedium
            rotation: -90
            x: Math.round(root.bx() + root.bw() + root.ww() * 0.12 - implicitWidth / 2)
            y: Math.round(root.carY(index) + root.carH() / 2 - implicitHeight / 2)
        }
    }

    // Door captions, bottom-to-top, left of the train (leftLabel over the
    // upper half, rightLabel the lower): the prefix at the bottom in white,
    // the status above it in its door colour.
    Text {
        id: preL
        text: root.prefixOf(root.leftLabel)
        color: "#fafafa"
        font.family: Theme.fontFamily; font.pixelSize: root.capFont(); font.weight: Theme.fontSemibold
        rotation: -90
        x: Math.round(root.bx() - root.ww() * 0.12 - implicitWidth / 2)
        y: Math.round(root.hh() * 0.25 + root.capLen(preL, postL) / 2 - implicitWidth / 2 - implicitHeight / 2)
    }
    Text {
        id: postL
        text: root.statusOf(root.leftLabel)
        visible: text.length > 0
        color: root.captionColour(root.doorsLeft)
        font.family: Theme.fontFamily; font.pixelSize: root.capFont(); font.weight: Theme.fontSemibold
        rotation: -90
        x: Math.round(root.bx() - root.ww() * 0.12 - implicitWidth / 2)
        y: Math.round(root.hh() * 0.25 - root.capLen(preL, postL) / 2 + implicitWidth / 2 - implicitHeight / 2)
    }
    Text {
        id: preR
        text: root.prefixOf(root.rightLabel)
        color: "#fafafa"
        font.family: Theme.fontFamily; font.pixelSize: root.capFont(); font.weight: Theme.fontSemibold
        rotation: -90
        x: Math.round(root.bx() - root.ww() * 0.12 - implicitWidth / 2)
        y: Math.round(root.hh() * 0.75 + root.capLen(preR, postR) / 2 - implicitWidth / 2 - implicitHeight / 2)
    }
    Text {
        id: postR
        text: root.statusOf(root.rightLabel)
        visible: text.length > 0
        color: root.captionColour(root.doorsRight)
        font.family: Theme.fontFamily; font.pixelSize: root.capFont(); font.weight: Theme.fontSemibold
        rotation: -90
        x: Math.round(root.bx() - root.ww() * 0.12 - implicitWidth / 2)
        y: Math.round(root.hh() * 0.75 - root.capLen(preR, postR) / 2 + implicitWidth / 2 - implicitHeight / 2)
    }
}
