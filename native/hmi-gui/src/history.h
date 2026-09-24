// native/hmi-gui/src/history.h
// Layer: 2 (GUI Loader)
// Purpose: per-tag ring buffers behind Bus.history() (CONTRACT C3).
// Port of the _history / history() parts of gui/hmi_loader/tagengine.py.
//
// Semantics:
//   * Only tracked tags are recorded; record() on an untracked tag is a no-op.
//   * A JSON null (invalid QVariant) is skipped: a failed hardware read leaves
//     no sample. bool is recorded as 0 / 1. Strings and anything non-numeric
//     are skipped.
//   * Each buffer holds at most `depth` samples; the oldest is dropped first.
//   * samples(tag, n) returns the last <= n samples, oldest first, as
//     QVariant(double) or QVariant(int/qint64) exactly as recorded (ints stay
//     ints so QML sees 3, not 3.0). Unknown tag -> empty list. n <= 0 -> empty.
//   * Tag names are always the dotted wire form; the TagEngine resolves
//     underscored aliases before calling in here.
//
// No QObject: this is a plain value class so it is trivially unit-testable.
//
// Implementation in history.cpp.
#pragma once

#include <QHash>
#include <QString>
#include <QStringList>
#include <QVariant>
#include <QVariantList>
#include <deque>

namespace hmi {

class History {
public:
    // depth < 1 is clamped to 1 (Python: max(1, history_depth)).
    explicit History(int depth = 600);

    int depth() const;

    // Creates an empty buffer for `tag` if none exists.
    void track(const QString &tag);
    bool isTracked(const QString &tag) const;
    QStringList trackedTags() const;   // any order

    // Appends one sample per the rules above. Returns true when a sample was
    // actually stored.
    bool record(const QString &tag, const QVariant &value);

    // Records every tracked tag that appears in `frameTags` (one telemetry
    // frame). Tags absent from the frame get nothing.
    void recordFrame(const QVariantMap &frameTags);

    QVariantList samples(const QString &tag, int n = 100) const;
    int count(const QString &tag) const;   // 0 for unknown

private:
    int m_depth;
    QHash<QString, std::deque<QVariant>> m_buffers;
};

} // namespace hmi
