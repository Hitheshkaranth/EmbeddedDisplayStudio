// native/hmi-gui/src/log.cpp
// Layer: 2 (GUI Loader)
// Owner: W3. See log.h for the contract.
#include "log.h"

#include <QLoggingCategory>
#include <QDateTime>
#include <QTextStream>
#include <cstdio>

Q_LOGGING_CATEGORY(lcHmi, "hmi-gui")

namespace hmi {

namespace {

enum Level {
    LevelDebug = 0,
    LevelInfo = 1,
    LevelWarning = 2,
    LevelError = 3,
    LevelFatal = 4
};

Level parseLevel(const QString &level)
{
    if (level == "DEBUG") return LevelDebug;
    if (level == "INFO") return LevelInfo;
    if (level == "WARNING") return LevelWarning;
    if (level == "ERROR") return LevelError;
    return LevelInfo; // unknown → INFO
}

Level msgTypeToLevel(QtMsgType type)
{
    switch (type) {
    case QtDebugMsg: return LevelDebug;
    case QtInfoMsg: return LevelInfo;
    case QtWarningMsg: return LevelWarning;
    case QtCriticalMsg: return LevelError;
    case QtFatalMsg: return LevelFatal;
    }
    return LevelInfo;
}

QString levelName(QtMsgType type)
{
    switch (type) {
    case QtDebugMsg: return "DEBUG";
    case QtInfoMsg: return "INFO";
    case QtWarningMsg: return "WARNING";
    case QtCriticalMsg: return "ERROR";
    case QtFatalMsg: return "CRITICAL";
    }
    return "INFO";
}

QString qmlPrefix(QtMsgType type)
{
    switch (type) {
    case QtDebugMsg: return "QML Debug: ";
    case QtInfoMsg: return "QML Info: ";
    case QtWarningMsg: return "QML Warning: ";
    case QtCriticalMsg: return "QML Critical: ";
    case QtFatalMsg: return "QML Fatal: ";
    }
    return QString();
}

Level g_minLevel = LevelInfo;
QtMessageHandler g_oldHandler = nullptr;

void ourMessageHandler(QtMsgType type, const QMessageLogContext &context, const QString &msg)
{
    // Fatal is never dropped and must abort
    if (type == QtFatalMsg) {
        QTextStream out(stdout);
        out << "CRITICAL - hmi-gui - " << msg << "\n";
        fflush(stdout);
        if (g_oldHandler)
            g_oldHandler(type, {}, msg);
        else
            abort();
        abort();
        return;
    }

    Level lvl = msgTypeToLevel(type);
    // Debug: trace all messages
    if (lvl < g_minLevel)
        return;

    // Callers log QStrings with .noquote(); the text is passed through as is,
    // so an app message that legitimately contains quotes is not mangled.
    QString lvlStr = levelName(type);
    const QString &message = msg;
    QString text;
    if (qstrcmp("hmi-gui", context.category) == 0) {
        text = QString("%1 - hmi-gui - %2").arg(lvlStr, message);
    } else {
        text = QString("%1 - hmi-gui - %2%3").arg(lvlStr, qmlPrefix(type), message);
    }
    QTextStream out(stdout);
    out << text << "\n";
    fflush(stdout);
}

} // namespace

void installLogging(const QString &level)
{
    g_minLevel = parseLevel(level.toUpper());
    if (level.toUpper() == "DEBUG")
        QLoggingCategory::setFilterRules("hmi-gui.debug=true");
    else
        QLoggingCategory::setFilterRules("hmi-gui.debug=false");
    // Capture the previous handler once; a second installLogging() must not
    // make the fatal path call ourselves recursively.
    QtMessageHandler previous = qInstallMessageHandler(ourMessageHandler);
    if (previous != ourMessageHandler)
        g_oldHandler = previous;
}

QString currentLogLevel()
{
    switch (g_minLevel) {
    case LevelDebug: return "DEBUG";
    case LevelInfo: return "INFO";
    case LevelWarning: return "WARNING";
    case LevelError: return "ERROR";
    case LevelFatal: return "CRITICAL";
    }
    return "INFO";
}

} // namespace hmi