// native/hmi-gui/tests/tst_alarms.cpp
// QTest case for AlarmEngine. The first test is a sanity check that proves the
// harness runs; the owner replaces the TODO with the real cases.
#include "alarmengine.h"

#include <QtTest>

class TstAlarmEngine : public QObject {
    Q_OBJECT
private slots:
    void emptyDefinitionsHaveNoTags()
    {
        hmi::AlarmEngine e({});
        QVERIFY(!e.hasDefinitions());
        QCOMPARE(e.alarmCount(), 0);
    }
    // TODO(W2): thresholdFired ops, critical-before-warning, null clears,
    // persistence keeps timestamp/acknowledged, escalation updates message,
    // sorting, acknowledge, changed-only signalling.
};

QTEST_GUILESS_MAIN(TstAlarmEngine)
#include "tst_alarms.moc"
