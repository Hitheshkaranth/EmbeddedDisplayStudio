// native/hmi-gui/src/hmi.cpp -- STUB. Owner: W3. See hmi.h.
#include "hmi.h"

namespace hmi {

Hmi::Hmi(const Manifest &manifest, const QString &appsDir, const QString &readyFile, QObject *parent)
    : QObject(parent), m_manifest(manifest), m_appsDir(appsDir), m_readyFile(readyFile)
{
    // TODO(W3): resolve m_entryUrl from appsDir / manifest.entry() when valid.
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

void Hmi::markReady() { /* TODO(W3) */ }
void Hmi::restart() { /* TODO(W3) */ }
void Hmi::log(const QString &msg) { Q_UNUSED(msg); /* TODO(W3) */ }

} // namespace hmi
