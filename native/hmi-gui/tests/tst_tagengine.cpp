// native/hmi-gui/tests/tst_tagengine.cpp
// QTest case for TagEngine. The first test is a sanity check that proves the
// harness runs; the owner replaces the TODO with the real cases.
#include "tagengine.h"

#include <QtTest>

class TstTagEngine : public QObject {
    Q_OBJECT
private slots:
    void wireNamePassThrough()
    {
        hmi::TagEngine::Options o;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("ai.pot")}, {}, o);
        QCOMPARE(e.toWireName(QStringLiteral("ai.pot")), QStringLiteral("ai.pot"));
        QCOMPARE(e.toWireName(QStringLiteral("unknown_alias")), QStringLiteral("unknown_alias"));
    }
    // TODO(W1): seeding, alias table, telemetry -> map/alias/online/history,
    // watchdog offline, subscribe cadence, command JSON shapes and ids, acks,
    // oversized/garbage datagrams counted, value() fallback, list_tags,
    // write-through via Tags assignment.
};

QTEST_GUILESS_MAIN(TstTagEngine)
#include "tst_tagengine.moc"
