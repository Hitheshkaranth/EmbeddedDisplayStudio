// native/hmi-gui/src/alarmengine.cpp
// Owner: W2. Port of _evaluate_alarms / get_active_alarms / acknowledge
// from tagengine.py lines 503-657.
#include "alarmengine.h"

#include <QDateTime>
#include <QRegularExpression>
#include <algorithm>
#include <cstdlib>

namespace hmi {

namespace {
// Python's isinstance(val, (int, float)): a real number, not a bool or a
// numeric-looking string.
bool isNumber(const QVariant &v)
{
    switch (v.userType()) {
    case QMetaType::Int: case QMetaType::UInt: case QMetaType::LongLong:
    case QMetaType::ULongLong: case QMetaType::Double: case QMetaType::Float:
        return true;
    default:
        return false;
    }
}
} // namespace

AlarmEngine::AlarmEngine(const QVariantList &alarmDefs, QObject *parent)
    : QObject(parent), m_defs(alarmDefs) {}

bool AlarmEngine::hasDefinitions() const { return !m_defs.isEmpty(); }

QStringList AlarmEngine::alarmTags() const
{
    QStringList result;
    for (const QVariant &av : m_defs) {
        if (!av.canConvert<QVariantMap>())
            continue;
        QVariantMap m = av.toMap();
        if (!m.contains("tag") || !m["tag"].canConvert<QString>())
            continue;
        QString tag = m["tag"].toString();
        if (!result.contains(tag))
            result.append(tag);
    }
    return result;
}

bool AlarmEngine::evaluate(const QVariantMap &frameTags)
{
    if (m_defs.isEmpty())
        return false;

    // Step 1: Build current_values for each valid definition's tag.
    QHash<QString, QVariant> currentValues;
    for (const QVariant &av : m_defs) {
        if (!av.canConvert<QVariantMap>())
            continue;
        QVariantMap m = av.toMap();
        if (!m.contains("tag") || !m["tag"].canConvert<QString>())
            continue;
        QString tag = m["tag"].toString();
        currentValues[tag] = frameTags.value(tag); // invalid if absent
    }

    // Step 2 & 3: Evaluate thresholds, build newly_active.
    QHash<QString, QVariantMap> newlyActive;
    bool changed = false;

    for (const QVariant &av : m_defs) {
        if (!av.canConvert<QVariantMap>())
            continue;
        QVariantMap m = av.toMap();
        if (!m.contains("tag") || !m["tag"].canConvert<QString>())
            continue;
        QString tag = m["tag"].toString();
        QVariant value = currentValues.value(tag);

        // null value (invalid QVariant) -> alarm inactive, skip.
        // A JSON null arrives as QVariant(nullptr), which is valid but null:
        // a failed hardware read makes the alarm inactive, like Python's None.
        if (!value.isValid() || value.isNull())
            continue;

        // Determine severity: critical first, then warning.
        QString severity;

        // Check critical.
        if (m.contains("critical")) {
            QVariantMap crit = m["critical"].toMap();
            if (crit.contains("op") && crit.contains("value")
                && crit["op"].canConvert<QString>()
                && isNumber(crit["value"]))
            {
                QString op = crit["op"].toString();
                double thr = crit["value"].toDouble();
                if (thresholdFired(value.toDouble(), op, thr)) {
                    severity = "critical";
                }
            }
        }

        // Check warning if critical didn't fire.
        if (severity.isNull() && m.contains("warning")) {
            QVariantMap warn = m["warning"].toMap();
            if (warn.contains("op") && warn.contains("value")
                && warn["op"].canConvert<QString>()
                && isNumber(warn["value"]))
            {
                QString op = warn["op"].toString();
                double thr = warn["value"].toDouble();
                if (thresholdFired(value.toDouble(), op, thr)) {
                    severity = "warning";
                }
            }
        }

        if (severity.isNull())
            continue;

        // Build alarm item.
        QString label = m.contains("label") ? m["label"].toString() : tag;
        QString unit = m.contains("unit") ? m["unit"].toString() : QString();
        QString message = QString("%1 %2%3")
            .arg(label)
            .arg(QString::asprintf("%g", value.toDouble()))
            .arg(unit);

        QVariantMap existing = m_active.value(tag);
        if (existing.contains("tag")) {
            // Already active.
            if (existing["severity"] != severity) {
                existing["severity"] = severity;
                existing["value"] = value;
                existing["message"] = message;
                changed = true;
            }
            newlyActive[tag] = existing;
        } else {
            // New alarm.
            QVariantMap item;
            item["tag"] = tag;
            item["label"] = label;
            item["severity"] = severity;
            item["value"] = value;
            item["message"] = message;
            item["timestamp"] = now();
            item["acknowledged"] = false;
            newlyActive[tag] = item;
            m_order[tag] = ++m_seq;
            changed = true;
        }
    }

    // Step 4: Any previously active tag not fired this frame -> remove.
    for (const QString &tag : m_active.keys()) {
        if (!newlyActive.contains(tag)) {
            m_active.remove(tag);
            m_order.remove(tag);
            changed = true;
        }
    }

    // Step 5: Replace/merge.
    for (auto it = newlyActive.begin(); it != newlyActive.end(); ++it)
        m_active.insert(it.key(), it.value());

    // Emit only when changed.
    if (changed)
        emit activeAlarmsChanged();

    return changed;
}

QVariantList AlarmEngine::activeAlarms() const
{
    QVariantList alarms;
    for (const QVariantMap &a : m_active.values())
        alarms.append(a);

    // Stable sort: critical first, then warning. Within each severity,
    // newest timestamp first (string compare).
    // Use a stable sort so equal timestamps preserve insertion order.
    std::stable_sort(alarms.begin(), alarms.end(),
        [this](const QVariant &a, const QVariant &b) {
            QString sevA = a.toMap().value("severity").toString();
            QString sevB = b.toMap().value("severity").toString();
            if (sevA != sevB) {
                return sevA == "critical"; // critical before warning
            }
            // Within same severity, newest first (descending timestamp).
            const QString tsA = a.toMap().value("timestamp").toString();
            const QString tsB = b.toMap().value("timestamp").toString();
            if (tsA != tsB)
                return tsA > tsB;   // newest first
            return m_order.value(a.toMap().value("tag").toString())
                 < m_order.value(b.toMap().value("tag").toString());
        });

    return alarms;
}

int AlarmEngine::alarmCount() const { return m_active.size(); }

bool AlarmEngine::acknowledge(const QString &tag)
{
    QVariantMap alarm = m_active.value(tag);
    if (!alarm.contains("tag"))
        return false;
    alarm["acknowledged"] = true;
    m_active[tag] = alarm;
    emit activeAlarmsChanged();
    return true;
}

bool AlarmEngine::thresholdFired(double value, const QString &op, double threshold)
{
    if (op == ">")
        return value > threshold;
    if (op == ">=")
        return value >= threshold;
    if (op == "<")
        return value < threshold;
    if (op == "<=")
        return value <= threshold;
    if (op == "==")
        return value == threshold;
    if (op == "!=")
        return value != threshold;
    return false;
}

QString AlarmEngine::now() const
{
    return QDateTime::currentDateTime().toString(QStringLiteral("yyyy-MM-ddTHH:mm:ss"));
}

} // namespace hmi