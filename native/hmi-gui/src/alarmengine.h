// native/hmi-gui/src/alarmengine.h
// Layer: 2 (GUI Loader)
// Purpose: manifest-driven alarm evaluation on every telemetry frame
// (CONTRACT C2 + C3). Port of _evaluate_alarms / get_active_alarms /
// acknowledge in gui/hmi_loader/tagengine.py -- read lines 478-660 of that
// file; they are the specification and this class must match them exactly.
//
// Alarm definitions come straight from manifest["alarms"] as a QVariantList
// of QVariantMap:
//   {"tag": "ai.pot", "label": "Input Voltage", "unit": "V",
//    "warning":  {"op": ">", "value": 2.5},
//    "critical": {"op": ">", "value": 3.0}}
// Entries that are not maps, or whose "tag" is not a string, are ignored.
// `op` is one of > >= < <= == != ; any other op never fires.
//
// Active alarm item (QVariantMap; the exact keys QML's ShAlarmTable reads):
//   tag, label (defaults to tag), severity ("critical"|"warning"),
//   value (the raw frame value, type preserved), message ("<label> <value:%g><unit>"),
//   timestamp ("YYYY-MM-DDTHH:MM:SS", local time, set on activation only),
//   acknowledged (bool, false on activation).
//
// Rules (frozen):
//   * critical is checked first; warning only if critical did not fire.
//   * A null frame value (invalid QVariant) or a tag absent from the frame
//     makes that alarm inactive on this frame (it clears if it was active).
//   * An alarm that stays active keeps its timestamp and acknowledged flag;
//     a severity change updates severity/value/message and counts as a change.
//   * activeAlarmsChanged() is emitted only when something changed
//     (activation, clear, severity change, acknowledge) -- never per frame.
//   * activeAlarms() is sorted critical first, then within each severity
//     newest timestamp first (string compare on the timestamp).
//   * acknowledge() on an unknown tag does nothing and emits nothing.
//
// Owner: W2 (implementation in alarmengine.cpp). The public API below is
// frozen; the private section may be extended by W2.
#pragma once

#include <QHash>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>

namespace hmi {

class AlarmEngine : public QObject {
    Q_OBJECT
public:
    explicit AlarmEngine(const QVariantList &alarmDefs, QObject *parent = nullptr);

    // Unique alarm tags in definition order (dotted wire names).
    QStringList alarmTags() const;
    bool hasDefinitions() const;

    // Evaluates every definition against one frame's tags (dotted names ->
    // values). Returns true and emits activeAlarmsChanged() when the active
    // set changed. A frame that changes nothing returns false.
    bool evaluate(const QVariantMap &frameTags);

    QVariantList activeAlarms() const;   // sorted as documented above
    int alarmCount() const;

    // `tag` is a dotted wire name (the TagEngine resolves aliases first).
    // Returns true when an active alarm was marked acknowledged.
    bool acknowledge(const QString &tag);

    // Exposed for unit tests: the single-threshold comparison.
    static bool thresholdFired(double value, const QString &op, double threshold);

signals:
    void activeAlarmsChanged();

protected:
    // Local time as "YYYY-MM-DDTHH:MM:SS". Virtual so a test can pin it.
    virtual QString now() const;

private:
    QVariantList m_defs;
    QHash<QString, QVariantMap> m_active;
    // Activation order, the tie-breaker Python gets for free from dict
    // insertion order: alarms raised in the same second sort by when they
    // were raised (and, within one frame, by definition order).
    QHash<QString, qint64> m_order;
    qint64 m_seq = 0;
};

} // namespace hmi
