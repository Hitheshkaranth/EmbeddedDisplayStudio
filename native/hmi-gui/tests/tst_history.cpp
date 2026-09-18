// native/hmi-gui/tests/tst_history.cpp
// QTest case for History. The first test is a sanity check that proves the
// harness runs; the owner replaces the TODO with the real cases.
#include "history.h"

#include <QtTest>

class TstHistory : public QObject {
    Q_OBJECT
private slots:
    void depthIsClampedToOne()
    {
        hmi::History h(0);
        QCOMPARE(h.depth(), 1);
        QCOMPARE(hmi::History(600).depth(), 600);
    }
    // TODO(W2): record/skip-null/bool-as-int/ring-overflow/samples-oldest-first/recordFrame.
};

QTEST_GUILESS_MAIN(TstHistory)
#include "tst_history.moc"
