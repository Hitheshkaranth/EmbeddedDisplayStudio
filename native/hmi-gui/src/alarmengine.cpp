// native/hmi-gui/src/alarmengine.cpp -- STUB. Owner: W2. See alarmengine.h.
#include "alarmengine.h"

#include <QDateTime>

namespace hmi {

AlarmEngine::AlarmEngine(const QVariantList &alarmDefs, QObject *parent)
    : QObject(parent), m_defs(alarmDefs) {}

QStringList AlarmEngine::alarmTags() const { return {}; }   // TODO(W2)
bool AlarmEngine::hasDefinitions() const { return !m_defs.isEmpty(); }

bool AlarmEngine::evaluate(const QVariantMap &frameTags)
{
    Q_UNUSED(frameTags);
    return false;   // TODO(W2)
}

QVariantList AlarmEngine::activeAlarms() const { return {}; }   // TODO(W2)
int AlarmEngine::alarmCount() const { return m_active.size(); }

bool AlarmEngine::acknowledge(const QString &tag)
{
    Q_UNUSED(tag);
    return false;   // TODO(W2)
}

bool AlarmEngine::thresholdFired(double value, const QString &op, double threshold)
{
    Q_UNUSED(value);
    Q_UNUSED(op);
    Q_UNUSED(threshold);
    return false;   // TODO(W2)
}

QString AlarmEngine::now() const
{
    return QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-ddTHH:mm:ss"));
}

} // namespace hmi
