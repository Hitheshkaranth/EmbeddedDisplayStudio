/**
 * tests/native/fixtures/probe-app/main.qml
 * Layer: Test (loader conformance)
 *
 * A bundle that narrates what it observes through Hmi.log(), so a black-box
 * test can drive any loader implementation (the Python one or the native
 * binary) as a subprocess and read the QML-visible state off stdout.
 *
 * Every line has the form "App Log: PROBE <key>=<value>"; the harness in
 * tests/native/loader_harness.py parses the part after "PROBE ".
 *
 * Commands are triggered by tag values so the test stays in control:
 *   ctl.write  = N   -> Bus.write("do.relay1", true)        (once per new N)
 *   ctl.pulse  = N   -> Bus.pulse("do.relay1", 250)
 *   ctl.assign = N   -> Tags.do_relay1 = true  (write-through; native only)
 *   ctl.ack    = N   -> Bus.acknowledge("ai.pot")
 *   ctl.uart   = N   -> Bus.uart_tx("hello\n")
 *   ctl.ping   = N   -> Bus.ping()
 *   ctl.list   = N   -> Bus.list_tags()  -> PROBE list=<comma-joined>
 *   ctl.hist   = N   -> PROBE hist=<comma-joined last 5 of ai.pot>
 */
import QtQuick 2.15
import Shadcn 1.0

Rectangle {
    id: root
    width: 640
    height: 480
    color: Theme.background

    // -- observed state, each logged when it changes -----------------------
    property var pot: Bus.value("ai.pot", -1)
    onPotChanged: Hmi.log("PROBE ai.pot=" + pot)

    property var potAlias: Bus.value("ai_pot", -1)
    onPotAliasChanged: Hmi.log("PROBE ai_pot=" + potAlias)

    property var viaTags: Tags.ai_pot
    onViaTagsChanged: Hmi.log("PROBE Tags.ai_pot=" + viaTags)

    property var estop: Bus.value("di.estop", "unset")
    onEstopChanged: Hmi.log("PROBE di.estop=" + estop)

    property var missing: Bus.value("ai.nope", "fallback")

    property bool online: Bus.online
    onOnlineChanged: Hmi.log("PROBE online=" + online)

    property int alarms: Bus.alarmCount
    onAlarmsChanged: Hmi.log("PROBE alarmCount=" + alarms)

    // The list changes on acknowledge too, when the count does not.
    property var alarmList: Bus.activeAlarms
    onAlarmListChanged: Hmi.log("PROBE alarms=" + alarmList.length + " top="
                                + (alarmList.length > 0 ? alarmList[0].severity + ":" + alarmList[0].message
                                                          + ":" + alarmList[0].acknowledged
                                                        : "none"))

    property int historyVersion: Bus.historyVersion

    // Shell.qml assigns Theme.mode in its own Component.onCompleted, which runs
    // after this file's, so the theme is observed as a change, not at start.
    Connections {
        target: Theme
        function onModeChanged() { Hmi.log("PROBE theme=" + Theme.mode) }
    }

    property int acks: 0
    Connections {
        target: Bus
        function onAckReceived(id, ok, err) {
            root.acks += 1
            Hmi.log("PROBE ack id=" + id + " ok=" + ok + " err=" + err)
        }
    }

    // -- control channel ------------------------------------------------------
    property var ctlWrite: Bus.value("ctl.write", 0)
    onCtlWriteChanged: if (ctlWrite > 0) Bus.write("do.relay1", true)

    property var ctlPulse: Bus.value("ctl.pulse", 0)
    onCtlPulseChanged: if (ctlPulse > 0) Bus.pulse("do.relay1", 250)

    property var ctlAssign: Bus.value("ctl.assign", 0)
    onCtlAssignChanged: if (ctlAssign > 0) Tags.do_relay1 = true

    property var ctlAck: Bus.value("ctl.ack", 0)
    onCtlAckChanged: if (ctlAck > 0) Bus.acknowledge("ai.pot")

    property var ctlUart: Bus.value("ctl.uart", 0)
    onCtlUartChanged: if (ctlUart > 0) Bus.uart_tx("hello\n")

    property var ctlPing: Bus.value("ctl.ping", 0)
    onCtlPingChanged: if (ctlPing > 0) Bus.ping()

    // list_tags() blocks for its reply. Called straight from a telemetry-driven
    // binding it would run inside the socket's readyRead handler, where Qt
    // cannot deliver the reply (readyRead is not re-entrant) -- in either
    // loader. A real app calls it from a click; the probe defers one turn.
    property var ctlList: Bus.value("ctl.list", 0)
    onCtlListChanged: if (ctlList > 0) listTimer.start()
    Timer {
        id: listTimer
        interval: 20
        onTriggered: Hmi.log("PROBE list=" + Bus.list_tags().join(","))
    }

    property var ctlHist: Bus.value("ctl.hist", 0)
    onCtlHistChanged: if (ctlHist > 0) Hmi.log("PROBE hist=" + Bus.history("ai.pot", 5).join(","))

    Component.onCompleted: {
        Hmi.log("PROBE ready app=" + Hmi.appName + "/" + Hmi.appVersion
                + " screen=" + Hmi.screenWidth + "x" + Hmi.screenHeight
                + " missing=" + missing
                + " online=" + Bus.online
                + " rxErrors=" + Bus.rxErrors)
    }
}
