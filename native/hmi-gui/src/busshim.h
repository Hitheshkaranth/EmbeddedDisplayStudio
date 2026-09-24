// native/hmi-gui/src/busshim.h
// Layer: 2 (GUI Loader)
// Purpose: installs `Tags`, `BusImpl` and `Bus` on a QML context.
// Port of BUS_QML + expose_to_qml() at the bottom of gui/hmi_loader/tagengine.py.
//
// Why a QML shim exists at all: a binding such as `value: Bus.value("ai.pot",
// 0)` is only re-evaluated when something it read THROUGH THE QML ENGINE
// changes. A C++ slot reads nothing the engine can see. So `Bus` is a small
// QML object whose value() indexes `Tags` inside the caller's own binding,
// and whose every other member forwards to `BusImpl` (the TagEngine).
// kBusQml must stay byte-for-byte equivalent in behaviour to BUS_QML.
//
// Implementation in busshim.cpp.
#pragma once

#include <QObject>

class QQmlContext;
class QQmlEngine;

namespace hmi {

class TagEngine;

// The shim source (a QtObject; see BUS_QML in tagengine.py).
extern const char *const kBusQml;

// Sets three context properties: Tags = tagEngine->tagMap(), BusImpl =
// tagEngine, Bus = the shim created from kBusQml in `context`. Returns the
// object bound as Bus. If the shim fails to build the error is logged and
// Bus falls back to the engine itself (commands still work; Bus.value()
// bindings stop re-evaluating). The shim is parented to tagEngine.
QObject *exposeToQml(QQmlEngine *engine, QQmlContext *context, TagEngine *tagEngine);

} // namespace hmi
