// native/hmi-gui/src/hmi.cpp
// Layer: 2 (GUI Loader)
// Owner: W3. See hmi.h for the contract.
#include "hmi.h"

#include "log.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>

namespace hmi {

Hmi::Hmi(const Manifest &manifest, const QString &appsDir, const QString &readyFile,
         QObject *parent)
    : QObject(parent), m_manifest(manifest), m_appsDir(appsDir), m_readyFile(readyFile)
{
    if (m_manifest.valid) {
        m_entryUrl = QUrl::fromLocalFile(
            QFileInfo(appsDir + "/" + m_manifest.entry()).absoluteFilePath());
    }
}

QString Hmi::appName() const { return m_manifest.name(); }
QString Hmi::appVersion() const { return m_manifest.version(); }
QUrl Hmi::appEntryUrl() const { return m_entryUrl; }
int Hmi::screenWidth() const { return m_manifest.screenWidth(); }
int Hmi::screenHeight() const { return m_manifest.screenHeight(); }
QString Hmi::lastError() const { return m_lastError; }

void Hmi::setLastError(const QString &error)
{
    if (m_lastError == error)
        return;
    m_lastError = error;
    emit lastErrorChanged();
}

void Hmi::markReady()
{
    QDir().mkpath(QFileInfo(m_readyFile).absolutePath());
    QFile file(m_readyFile);
    if (file.open(QIODevice::WriteOnly | QIODevice::Append)) {
        file.close();
        qCInfo(lcHmi) << "Marked ready at" << m_readyFile;
    } else {
        qCCritical(lcHmi) << "Failed to touch ready file" << m_readyFile
                          << ":" << file.errorString();
    }
}

void Hmi::restart()
{
    qCInfo(lcHmi) << "Restart requested by QML.";
    QCoreApplication::exit(1);
}

void Hmi::log(const QString &msg)
{
    qCInfo(lcHmi) << "App Log:" << msg;
}

} // namespace hmi