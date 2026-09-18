// native/hmi-gui/src/tagmap.cpp -- STUB. Owner: W1. See tagmap.h.
#include "tagmap.h"

namespace hmi {

TagMap::TagMap(QObject *parent) : QQmlPropertyMap(this, parent) {}

QVariant TagMap::updateValue(const QString &key, const QVariant &input)
{
    emit qmlWrite(key, input);
    return value(key);
}

} // namespace hmi
