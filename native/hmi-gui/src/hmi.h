// native/hmi-gui/src/hmi.h
// Layer: 2 (GUI Loader)
// Purpose: the `Hmi` context property -- app metadata and system operations
// for Shell.qml / Fallback.qml. Port of class Hmi in gui/hmi_loader/main.py.
//
// QML surface (frozen; Shell.qml and Fallback.qml bind to it):
//     Hmi.appName, Hmi.appVersion, Hmi.appEntryUrl, Hmi.screenWidth,
//     Hmi.screenHeight        constant
//     Hmi.lastError           notify lastErrorChanged
//     Hmi.markReady()         touches the ready file (CONTRACT section 6)
//     Hmi.restart()           exits the process with status 1 (systemd restarts)
//     Hmi.log(msg)            "INFO - hmi-gui - App Log: <msg>"
//
// Owner: W3 (implementation in hmi.cpp). The public API below is frozen.
#pragma once

#include "manifest.h"

#include <QObject>
#include <QString>
#include <QUrl>

namespace hmi {

class Hmi : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString appName READ appName CONSTANT)
    Q_PROPERTY(QString appVersion READ appVersion CONSTANT)
    Q_PROPERTY(QUrl appEntryUrl READ appEntryUrl CONSTANT)
    Q_PROPERTY(int screenWidth READ screenWidth CONSTANT)
    Q_PROPERTY(int screenHeight READ screenHeight CONSTANT)
    Q_PROPERTY(QString lastError READ lastError WRITE setLastError NOTIFY lastErrorChanged)

public:
    // `appsDir` is the bundle directory (parent of manifest.json);
    // `readyFile` the --ready-file path. When the manifest is invalid
    // appEntryUrl() is an empty QUrl and the caller sets lastError.
    Hmi(const Manifest &manifest, const QString &appsDir, const QString &readyFile,
        QObject *parent = nullptr);

    QString appName() const;      // manifest name, "Error" when invalid
    QString appVersion() const;   // manifest version, "0.0.0" when invalid
    QUrl appEntryUrl() const;     // file:// URL of <appsDir>/<entry>, resolved
    int screenWidth() const;
    int screenHeight() const;
    QString lastError() const;
    void setLastError(const QString &error);   // emits only on change

public slots:
    // Creates the parent directory if needed, then touches the file. Errors
    // are logged, never thrown: the UI must stay up (CONTRACT section 7).
    void markReady();
    // Logs "Restart requested by QML." and exits with status 1.
    void restart();
    // Logs "App Log: <msg>" at INFO.
    void log(const QString &msg);

signals:
    void lastErrorChanged();

private:
    Manifest m_manifest;
    QString m_appsDir;
    QString m_readyFile;
    QString m_lastError;
    QUrl m_entryUrl;
};

} // namespace hmi
