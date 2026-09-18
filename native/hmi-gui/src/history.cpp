// native/hmi-gui/src/history.cpp
// Owner: W2. Implementation per history.h and tagengine.py lines 391-404.
#include "history.h"

#include <QMetaType>

namespace hmi {

History::History(int depth) : m_depth(depth < 1 ? 1 : depth) {}

int History::depth() const { return m_depth; }

void History::track(const QString &tag)
{
    if (!m_buffers.contains(tag))
        m_buffers.insert(tag, {});
}

bool History::isTracked(const QString &tag) const { return m_buffers.contains(tag); }

QStringList History::trackedTags() const { return m_buffers.keys(); }

bool History::record(const QString &tag, const QVariant &value)
{
    // Untracked tag -> skip.
    if (!isTracked(tag))
        return false;

    // Invalid QVariant (JSON null) -> skip.
    if (!value.isValid())
        return false;

    // Non-numeric types (string, list, map) -> skip.
    // bool -> store as int 0/1.
    if (value.userType() == QMetaType::Bool) {
        int v = value.toBool() ? 1 : 0;
        m_buffers[tag].push_back(QVariant(v));
        while ((int)m_buffers[tag].size() > m_depth)
            m_buffers[tag].pop_front();
        return true;
    }

    // Accept integer types.
    int ut = value.userType();
    if (ut == QMetaType::Int || ut == QMetaType::LongLong ||
        ut == QMetaType::UInt || ut == QMetaType::ULongLong)
    {
        m_buffers[tag].push_back(value);
        while ((int)m_buffers[tag].size() > m_depth)
            m_buffers[tag].pop_front();
        return true;
    }

    // Accept float types.
    if (ut == QMetaType::Double || ut == QMetaType::Float) {
        m_buffers[tag].push_back(value);
        while ((int)m_buffers[tag].size() > m_depth)
            m_buffers[tag].pop_front();
        return true;
    }

    // Everything else (string, list, map, etc.) -> skip.
    return false;
}

void History::recordFrame(const QVariantMap &frameTags)
{
    for (const QString &tag : m_buffers.keys()) {
        if (frameTags.contains(tag)) {
            record(tag, frameTags.value(tag));
        }
    }
}

QVariantList History::samples(const QString &tag, int n) const
{
    if (n <= 0)
        return {};

    auto it = m_buffers.find(tag);
    if (it == m_buffers.end())
        return {};

    const auto &buf = it.value();
    int sz = (int)buf.size();
    if (sz == 0)
        return {};

    int start = 0;
    if (sz > n)
        start = sz - n;

    QVariantList result;
    for (int i = start; i < sz; ++i)
        result.append(buf[i]);
    return result;
}

int History::count(const QString &tag) const
{
    auto it = m_buffers.find(tag);
    if (it == m_buffers.end())
        return 0;
    return (int)it.value().size();
}

} // namespace hmi