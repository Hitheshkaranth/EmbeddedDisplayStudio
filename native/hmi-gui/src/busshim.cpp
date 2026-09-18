// native/hmi-gui/src/busshim.cpp
// Layer: 2 (GUI Loader)
// Owner: W3. See busshim.h for the contract.
#include "busshim.h"
#include "log.h"
#include "tagengine.h"

#include <QQmlComponent>
#include <QQmlContext>
#include <QQmlEngine>

namespace hmi {

// Port of BUS_QML from gui/hmi_loader/tagengine.py verbatim.
const char *const kBusQml = R"qml(
import QtQuick 2.15

QtObject {
    id: bus

    // Live state, forwarded as bindable properties.
    readonly property bool online: BusImpl.online
    readonly property int rxErrors: BusImpl.rxErrors
    readonly property int historyVersion: BusImpl.historyVersion
    readonly property var activeAlarms: BusImpl.activeAlarms
    readonly property int alarmCount: BusImpl.alarmCount

    // Signals an app may connect to, re-emitted from the engine.
    signal ackReceived(string id, bool ok, string err)
    signal listReceived(var tags)
    signal unsubscribed()
    property var _forward: Connections {
        target: BusImpl
        function onAckReceived(id, ok, err) { bus.ackReceived(id, ok, err) }
        function onListReceived(tags) { bus.listReceived(tags) }
        function onUnsubscribed() { bus.unsubscribed() }
    }

    // A tag read that the binding calling it depends on. Dotted and
    // underscored names both work (CONTRACT 2.5); a missing or null tag
    // yields the fallback, never an error.
    function value(name, fallback) {
        var v = Tags[name]
        if (v === undefined || v === null) v = Tags[name.replace(/\./g, "_")]
        if (v === undefined || v === null) return fallback === undefined ? null : fallback
        return v
    }

    function write(tag, value) { BusImpl.write(tag, value) }
    function pulse(tag, ms) { BusImpl.pulse(tag, ms) }
    function uart_tx(data) { BusImpl.uart_tx(data) }
    function ping() { BusImpl.ping() }
    function list_tags() { return BusImpl.list_tags() }
    function unsubscribe() { BusImpl.unsubscribe() }
    function history(tag, n) { return BusImpl.history(tag, n === undefined ? 100 : n) }
    function acknowledge(tag) { BusImpl.acknowledge(tag) }
}
)qml";

QObject *exposeToQml(QQmlEngine *engine, QQmlContext *context, TagEngine *tagEngine)
{
    context->setContextProperty(QStringLiteral("Tags"), tagEngine->tagMap());
    context->setContextProperty(QStringLiteral("BusImpl"), tagEngine);

    QQmlComponent component(engine);
    component.setData(QByteArray(kBusQml), QUrl());
    QObject *bus = component.create(context);

    if (bus == nullptr) {
        QString errors;
        for (const QQmlError &e : component.errors())
            errors += (errors.isEmpty() ? QString() : QStringLiteral("; ")) + e.toString();
        qCCritical(lcHmi).noquote()
            << "Bus shim failed to build; bindings on Bus.value() will not update:" << errors;
        bus = tagEngine;
    } else {
        bus->setParent(tagEngine);
    }
    context->setContextProperty("Bus", bus);
    return bus;
}

} // namespace hmi