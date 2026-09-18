// native/hmi-gui/src/manifest.cpp -- STUB. Owner: W3. See manifest.h.
#include "manifest.h"

namespace hmi {

QString Manifest::name() const
{
    return valid ? data.value(QStringLiteral("name"), QStringLiteral("Unknown")).toString()
                 : QStringLiteral("Error");
}

QString Manifest::version() const
{
    return valid ? data.value(QStringLiteral("version"), QStringLiteral("0.0.0")).toString()
                 : QStringLiteral("0.0.0");
}

QString Manifest::entry() const { return valid ? data.value(QStringLiteral("entry")).toString() : QString(); }
int Manifest::screenWidth() const { return 1280; }        // TODO(W3)
int Manifest::screenHeight() const { return 800; }        // TODO(W3)
QString Manifest::theme() const { return QString(); }     // TODO(W3)
QStringList Manifest::tagsRequired() const { return {}; } // TODO(W3)
QVariantList Manifest::alarms() const { return {}; }      // TODO(W3)
QStringList Manifest::alarmTags() const { return {}; }    // TODO(W3)
QStringList Manifest::expectedTags() const { return {}; } // TODO(W3)

Manifest loadManifest(const QString &manifestPath)
{
    Manifest m;
    m.path = manifestPath;
    m.error = QStringLiteral("Manifest not found: ") + manifestPath;   // TODO(W3)
    return m;
}

QString resolveTheme(const Manifest &manifest, const QString &overrideTheme)
{
    Q_UNUSED(manifest);
    Q_UNUSED(overrideTheme);
    return QStringLiteral("dark");   // TODO(W3)
}

} // namespace hmi
