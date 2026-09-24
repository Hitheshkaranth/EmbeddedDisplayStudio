// native/hmi-gui/src/tagmap.h
// Layer: 2 (GUI Loader)
// Purpose: the `Tags` context property -- a QQmlPropertyMap with write-through.
//
// gui/README.md promises that assigning an underscored alias from QML
// (`Tags.do_relay1 = true`) sends a `set` command to the daemon. Under
// PySide6 that could not be implemented (see the PLATFORM NOTE at the top of
// gui/hmi_loader/tagengine.py); in C++ overriding updateValue() is the
// idiomatic way and it works. This subclass does exactly that and nothing
// else: it emits qmlWrite() and returns the value ALREADY in the map, so the
// map is not optimistically updated -- the UI always shows the hardware's
// read-back, the same rule TagEngine::write() follows.
//
// Keys: every tag under both spellings ("ai.pot" and "ai_pot"), plus
// "online" (bool). QML can only read the dotted form via Tags["ai.pot"];
// the alias is what bindings use.
//
// Implementation in tagmap.cpp.
#pragma once

#include <QQmlPropertyMap>
#include <QString>
#include <QVariant>

namespace hmi {

class TagMap : public QQmlPropertyMap {
    Q_OBJECT
public:
    explicit TagMap(QObject *parent = nullptr);

signals:
    // A QML assignment happened. `key` is whatever spelling QML used.
    void qmlWrite(const QString &key, const QVariant &value);

protected:
    // Emits qmlWrite(key, input) and returns value(key) unchanged.
    QVariant updateValue(const QString &key, const QVariant &input) override;
};

} // namespace hmi
