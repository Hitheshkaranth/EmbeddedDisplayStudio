// native/hmi-gui/src/manifest.cpp
// Layer: 2 (GUI Loader)
// Owner: W3. See manifest.h for the contract.
#include "manifest.h"

#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonObject>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QRegularExpression>
#include <QVariant>

namespace hmi {

// ---------------------------------------------------------------------------
// Accessors
// ---------------------------------------------------------------------------

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

QString Manifest::entry() const
{
    return valid ? data.value(QStringLiteral("entry")).toString() : QString();
}

int Manifest::screenWidth() const
{
    if (!valid) return 1280;
    QVariant screen = data.value(QStringLiteral("screen"));
    if (screen.canConvert(QVariant::Map)) {
        QVariantMap sm = screen.toMap();
        if (sm.contains(QStringLiteral("width")) && sm[QStringLiteral("width")].toInt() == sm[QStringLiteral("width")].toUInt()) {
            return sm[QStringLiteral("width")].toInt();
        }
    }
    return 1280;
}

int Manifest::screenHeight() const
{
    if (!valid) return 800;
    QVariant screen = data.value(QStringLiteral("screen"));
    if (screen.canConvert(QVariant::Map)) {
        QVariantMap sm = screen.toMap();
        if (sm.contains(QStringLiteral("height")) && sm[QStringLiteral("height")].toInt() == sm[QStringLiteral("height")].toUInt()) {
            return sm[QStringLiteral("height")].toInt();
        }
    }
    return 800;
}

QString Manifest::theme() const
{
    if (!valid) return QString();
    QString t = data.value(QStringLiteral("theme")).toString();
    if (t == "light" || t == "dark") return t;
    return QString();
}

QStringList Manifest::tagsRequired() const
{
    if (!valid) return {};
    QVariantList list = data.value(QStringLiteral("tags_required")).toList();
    QStringList result;
    for (const QVariant &v : list) {
        if (v.canConvert(QVariant::String))
            result.append(v.toString());
    }
    return result;
}

QVariantList Manifest::alarms() const
{
    if (!valid) return {};
    return data.value(QStringLiteral("alarms")).toList();
}

QStringList Manifest::alarmTags() const
{
    if (!valid) return {};
    QVariantList list = data.value(QStringLiteral("alarms")).toList();
    QStringList result;
    QSet<QString> seen;
    for (const QVariant &v : list) {
        if (!v.canConvert(QVariant::Map)) continue;
        QVariantMap am = v.toMap();
        QString tag = am.value(QStringLiteral("tag")).toString();
        if (!tag.isEmpty() && !seen.contains(tag)) {
            seen.insert(tag);
            result.append(tag);
        }
    }
    return result;
}

QStringList Manifest::expectedTags() const
{
    QStringList result = tagsRequired();
    QStringList atags = alarmTags();
    for (const QString &t : atags) {
        if (!result.contains(t))
            result.append(t);
    }
    return result;
}

// ---------------------------------------------------------------------------
// resolveTheme
// ---------------------------------------------------------------------------

QString resolveTheme(const Manifest &manifest, const QString &overrideTheme)
{
    if (overrideTheme == "light" || overrideTheme == "dark")
        return overrideTheme;
    QString mt = manifest.theme();
    return mt.isEmpty() ? QStringLiteral("dark") : mt;
}

// ---------------------------------------------------------------------------
// loadManifest
// ---------------------------------------------------------------------------

Manifest loadManifest(const QString &manifestPath)
{
    Manifest m;
    m.path = manifestPath;

    QFile file(manifestPath);
    if (!file.exists()) {
        m.valid = false;
        m.error = QStringLiteral("Manifest not found: ") + manifestPath;
        m.data = QVariantMap();
        return m;
    }

    if (!file.open(QIODevice::ReadOnly)) {
        m.valid = false;
        m.error = QStringLiteral("Manifest parse error: Cannot open file");
        m.data = QVariantMap();
        return m;
    }

    QJsonParseError parseError;
    QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &parseError);
    file.close();

    if (parseError.error != QJsonParseError::NoError) {
        m.valid = false;
        m.error = QStringLiteral("Manifest parse error: ") + parseError.errorString();
        m.data = QVariantMap();
        return m;
    }

    if (!doc.isObject()) {
        m.valid = false;
        m.error = QStringLiteral("Manifest parse error: Expected a JSON object");
        m.data = QVariantMap();
        return m;
    }

    QJsonObject obj = doc.object();

    // schema must be the JSON number 1 (not "1" or any other value)
    if (!obj.contains("schema") || !obj["schema"].isDouble() || obj["schema"].toDouble() != 1.0) {
        m.valid = false;
        m.error = QStringLiteral("Unsupported or missing schema version. Expected schema: 1.");
        m.data = QVariantMap();
        return m;
    }

    // name must be a string matching the pattern
    if (!obj.contains("name") || !obj["name"].isString()) {
        QString name = obj.contains("name") ? obj["name"].toString() : QString();
        m.valid = false;
        m.error = QString("Invalid app name: '%1'. Must match ^[a-z0-9][a-z0-9._-]{0,63}$").arg(name);
        m.data = QVariantMap();
        return m;
    }

    QString nameStr = obj["name"].toString();
    QRegularExpression nameRe(QStringLiteral("^[a-z0-9][a-z0-9._-]{0,63}$"));
    if (!nameRe.match(nameStr).hasMatch()) {
        m.valid = false;
        m.error = QString("Invalid app name: '%1'. Must match ^[a-z0-9][a-z0-9._-]{0,63}$").arg(nameStr);
        m.data = QVariantMap();
        return m;
    }

    // entry
    QString entry;
    if (obj.contains("entry") && obj["entry"].isString()) {
        entry = obj["entry"].toString();
    }
    if (entry.isEmpty()) {
        m.valid = false;
        m.error = QStringLiteral("Missing 'entry' in manifest.");
        m.data = QVariantMap();
        return m;
    }

    if (entry.contains("..") || QDir::isAbsolutePath(entry)) {
        m.valid = false;
        m.error = QString("Invalid entry path: '%1'. Cannot be absolute or contain '..'.").arg(entry);
        m.data = QVariantMap();
        return m;
    }

    // Entry point must exist
    QString entryPath = QFileInfo(manifestPath).dir().filePath(entry);
    if (!QFileInfo::exists(entryPath)) {
        m.valid = false;
        m.error = QString("Entry point not found: %1").arg(entryPath);
        m.data = QVariantMap();
        return m;
    }

    // Success — store the whole object as data
    QVariantMap data;
    for (auto it = obj.begin(); it != obj.end(); ++it) {
        data.insert(it.key(), QVariant(it.value()));
    }

    m.valid = true;
    m.error = QString();
    m.data = data;
    return m;
}

} // namespace hmi