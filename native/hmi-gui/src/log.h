// native/hmi-gui/src/log.h
// Layer: 2 (GUI Loader)
// Purpose: journald-friendly logging that matches the Python loader's output
// line for line, so `journalctl -u hmi-gui` greps keep working.
//
// Python format (logging.basicConfig in gui/hmi_loader/main.py):
//     LEVEL - hmi-gui - message
// QML engine messages were routed through qml_log_handler and appear as:
//     WARNING - hmi-gui - QML Warning: <message>
//
// Our own messages go through the `lcHmi` category (qCInfo(lcHmi) << ...);
// anything from another category (the QML engine, Qt itself) is treated as
// a QML/Qt message and gets the "QML <Type>: " prefix. Everything is written
// to stdout, unbuffered, the way the Python loader did.
//
// Level names and their Qt mapping:
//     DEBUG   -> QtDebugMsg        INFO -> QtInfoMsg
//     WARNING -> QtWarningMsg      ERROR -> QtCriticalMsg / QtFatalMsg
//
// Implementation in log.cpp.
#pragma once

#include <QLoggingCategory>
#include <QString>

Q_DECLARE_LOGGING_CATEGORY(lcHmi)

namespace hmi {

// Installs the message handler and the level filter. `level` is one of
// "DEBUG", "INFO", "WARNING", "ERROR" (the --log-level choices); anything
// else is treated as "INFO". Safe to call more than once.
void installLogging(const QString &level);

// The level installLogging() was last called with, upper-cased ("INFO" when
// it was never called). Exposed so a test can assert the filter took.
QString currentLogLevel();

} // namespace hmi
