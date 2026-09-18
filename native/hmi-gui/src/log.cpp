// native/hmi-gui/src/log.cpp -- STUB. Owner: W3. See log.h for the contract.
#include "log.h"

#include <QtGlobal>

Q_LOGGING_CATEGORY(lcHmi, "hmi-gui")

namespace hmi {

namespace {
QString g_level = QStringLiteral("INFO");
}

void installLogging(const QString &level)
{
    // TODO(W3): qInstallMessageHandler formatting "LEVEL - hmi-gui - msg",
    // QML/Qt messages prefixed "QML <Type>: ", level filter, stdout unbuffered.
    g_level = level.toUpper();
}

QString currentLogLevel()
{
    return g_level;
}

} // namespace hmi
