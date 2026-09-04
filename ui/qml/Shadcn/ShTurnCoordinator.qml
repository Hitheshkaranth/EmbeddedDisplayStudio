import QtQuick 2.15

Item {
    id: root
    property real turnRate: 0
    property real slip: 0
    property real standardRate: 3
    property real slipLimit: 1
    implicitWidth: 180
    implicitHeight: 110

    Rectangle { anchors.fill: parent; color: Theme.efisPanel; radius: Theme.radiusSm }
    Canvas {
        id: face; anchors.fill: parent
        onPaint: {
            var c=getContext("2d"); c.reset(); var cx=width/2, cy=height*.43, r=Math.min(width*.38,height*.38);
            c.strokeStyle=Theme.efisLine; c.lineWidth=2;
            c.beginPath(); c.arc(cx,cy,r,Math.PI,2*Math.PI); c.stroke();
            for (var i=-2;i<=2;i++) { var x=cx+i*r/2; c.beginPath(); c.moveTo(x,cy-r); c.lineTo(x,cy-r+8); c.stroke(); }
        }
        Component.onCompleted: requestPaint(); onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
    }
    Item {
        width: parent.width*.42; height: 26; anchors.horizontalCenter: parent.horizontalCenter
        y: parent.height*.43-13
        rotation: Math.max(-2,Math.min(2,root.turnRate/root.standardRate))*20
        Rectangle { width: parent.width; height: 3; color: Theme.efisAircraft; anchors.centerIn: parent }
        Rectangle { width: 3; height: 16; color: Theme.efisAircraft; anchors.centerIn: parent }
    }
    Rectangle {
        width: parent.width*.56; height: 16; radius: 8; color: "transparent"
        border.color: Theme.efisLine; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
        Rectangle {
            width: 12; height: 12; radius: 6; color: Theme.efisLine; anchors.verticalCenter: parent.verticalCenter
            x: (parent.width-width)/2 + Math.max(-1,Math.min(1,root.slip/root.slipLimit))*(parent.width-width)*.42
        }
    }
}
