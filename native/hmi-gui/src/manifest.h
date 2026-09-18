// native/hmi-gui/src/manifest.h
// Layer: 2 (GUI Loader)
// Purpose: the runtime subset of manifest validation (CONTRACT section 4).
//
// This is a port of validate_manifest() in gui/hmi_loader/main.py and
// alarm_tags() in schema/manifest.py -- ONLY those two. The Studio keeps the
// full Python validator (schema/manifest.py: runtime, qt_binding, deps); the
// loader only needs to decide whether it can load the entry point and what
// tags to seed. Error strings are part of the contract: Fallback.qml shows
// them and the conformance suite (tests/native/) matches on them.
//
// Owner: W3 (implementation in manifest.cpp). The public API below is frozen.
#pragma once

#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

namespace hmi {

struct Manifest {
    // False when validation failed; then `error` is set and `data` is empty,
    // exactly like the Python (manifest_dict, error_string) tuple.
    bool valid = false;
    QString error;
    QVariantMap data;

    // Absolute path of the manifest.json that was read (even when invalid).
    QString path;

    // Convenience accessors with the Python defaults. All return the
    // "invalid" defaults when !valid (name "Error", version "0.0.0",
    // screen 1280x800, empty lists) -- see Hmi in main.py.
    QString name() const;
    QString version() const;
    QString entry() const;         // "" when absent
    int screenWidth() const;       // 1280 default
    int screenHeight() const;      // 800 default
    QString theme() const;         // "light" | "dark" | "" (absent/invalid)
    QStringList tagsRequired() const;
    QVariantList alarms() const;   // manifest["alarms"] or []
    // Unique alarm tag names in manifest order (schema.manifest.alarm_tags).
    QStringList alarmTags() const;
    // tagsRequired() followed by any alarmTags() not already present: the
    // list main.py hands the TagEngine as expected_tags.
    QStringList expectedTags() const;
};

// Port of main.py validate_manifest(). Checks, in this order, with these
// exact messages (paths rendered as given / resolved, like Python's):
//   "Manifest not found: <path>"
//   "Manifest parse error: <reason>"
//   "Unsupported or missing schema version. Expected schema: 1."
//   "Invalid app name: '<name>'. Must match ^[a-z0-9][a-z0-9._-]{0,63}$"
//   "Missing 'entry' in manifest."
//   "Invalid entry path: '<entry>'. Cannot be absolute or contain '..'."
//   "Entry point not found: <dir>/<entry>"
// `schema` must be the JSON number 1 (not "1"); `name` must be a string.
Manifest loadManifest(const QString &manifestPath);

// Port of main.py resolve_theme(): `overrideTheme` ("light"/"dark") wins,
// else the manifest's `theme` when it is one of those, else "dark".
QString resolveTheme(const Manifest &manifest, const QString &overrideTheme);

} // namespace hmi
