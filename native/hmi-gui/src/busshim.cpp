// native/hmi-gui/src/busshim.cpp -- STUB. Owner: W3. See busshim.h.
#include "busshim.h"
#include "tagengine.h"

#include <QQmlContext>
#include <QQmlEngine>

namespace hmi {

// TODO(W3): copy BUS_QML from gui/hmi_loader/tagengine.py verbatim
// (mind the JS regex: /\./g needs one backslash in a C++ raw string).
const char *const kBusQml = "import QtQuick 2.15\nQtObject {}\n";

QObject *exposeToQml(QQmlEngine *engine, QQmlContext *context, TagEngine *tagEngine)
{
    Q_UNUSED(engine);
    context->setContextProperty(QStringLiteral("Tags"), tagEngine->tagMap());
    context->setContextProperty(QStringLiteral("BusImpl"), tagEngine);
    context->setContextProperty(QStringLiteral("Bus"), tagEngine);   // TODO(W3): the shim
    return tagEngine;
}

} // namespace hmi
