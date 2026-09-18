// native/hmi-gui/src/history.cpp -- STUB. Owner: W2. See history.h.
#include "history.h"

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
    Q_UNUSED(tag);
    Q_UNUSED(value);
    return false;   // TODO(W2)
}

void History::recordFrame(const QVariantMap &frameTags)
{
    Q_UNUSED(frameTags);   // TODO(W2)
}

QVariantList History::samples(const QString &tag, int n) const
{
    Q_UNUSED(tag);
    Q_UNUSED(n);
    return {};   // TODO(W2)
}

int History::count(const QString &tag) const
{
    Q_UNUSED(tag);
    return 0;   // TODO(W2)
}

} // namespace hmi
