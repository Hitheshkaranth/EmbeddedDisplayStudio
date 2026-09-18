// native/hmi-gui/tests/tst_history.cpp
// QTest case for History. Owner: W2.
#include "history.h"

#include <QMetaType>
#include <QtTest>

class TstHistory : public QObject {
    Q_OBJECT
private slots:
    void depthIsClampedToOne()
    {
        hmi::History h(0);
        QCOMPARE(h.depth(), 1);
        QCOMPARE(hmi::History(600).depth(), 600);
        QCOMPARE(hmi::History(-5).depth(), 1);
    }

    void untrackedIgnored()
    {
        hmi::History h(10);
        h.track("a");
        // "b" is never tracked.
        QVERIFY(!h.isTracked("b"));
        // record on untracked returns false, does nothing.
        QVERIFY(!h.record("b", QVariant(42)));
        QCOMPARE(h.count("b"), 0);
    }

    void nullSkipped()
    {
        hmi::History h(10);
        h.track("x");
        QVariant nullVal; // invalid = JSON null
        QVERIFY(!h.record("x", nullVal));
        QCOMPARE(h.count("x"), 0);
    }

    void boolAsInt()
    {
        hmi::History h(10);
        h.track("flag");
        QVariant trueVal(true);
        QVERIFY(h.record("flag", trueVal));
        QVariant falseVal(false);
        QVERIFY(h.record("flag", falseVal));
        QCOMPARE(h.count("flag"), 2);

        // Verify stored values are int, not bool.
        QVariantList s = h.samples("flag", 100);
        QCOMPARE(s.size(), 2);
        QCOMPARE(s[0].userType(), QMetaType::Int);
        QCOMPARE(s[0].toInt(), 1);
        QCOMPARE(s[1].userType(), QMetaType::Int);
        QCOMPARE(s[1].toInt(), 0);
    }

    void doubleStaysDouble()
    {
        hmi::History h(10);
        h.track("val");
        QVERIFY(h.record("val", QVariant(3.14)));
        QCOMPARE(h.count("val"), 1);
        QVariantList s = h.samples("val", 100);
        QCOMPARE(s.size(), 1);
        QCOMPARE(s[0].userType(), QMetaType::Double);
        QCOMPARE(s[0].toDouble(), 3.14);
    }

    void stringSkipped()
    {
        hmi::History h(10);
        h.track("s");
        QVERIFY(!h.record("s", QVariant(QString("hello"))));
        QCOMPARE(h.count("s"), 0);
    }

    void overflowDropsOldest()
    {
        hmi::History h(3);
        h.track("n");
        h.record("n", QVariant(1));
        h.record("n", QVariant(2));
        h.record("n", QVariant(3));
        h.record("n", QVariant(4));
        h.record("n", QVariant(5));
        QCOMPARE(h.count("n"), 3);
        QVariantList s = h.samples("n", 100);
        QCOMPARE(s.size(), 3);
        QCOMPARE(s[0].toInt(), 3);
        QCOMPARE(s[1].toInt(), 4);
        QCOMPARE(s[2].toInt(), 5);
    }

    void samplesSmallerThanSize()
    {
        hmi::History h(10);
        h.track("x");
        for (int i = 1; i <= 5; ++i)
            h.record("x", QVariant(i));
        // Ask for 2 -> last 2 oldest-first: [4, 5]
        QVariantList s = h.samples("x", 2);
        QCOMPARE(s.size(), 2);
        QCOMPARE(s[0].toInt(), 4);
        QCOMPARE(s[1].toInt(), 5);
    }

    void samplesLargerThanSize()
    {
        hmi::History h(10);
        h.track("x");
        h.record("x", QVariant(42));
        // Ask for 100 but only 1 -> returns 1
        QVariantList s = h.samples("x", 100);
        QCOMPARE(s.size(), 1);
        QCOMPARE(s[0].toInt(), 42);
    }

    void samplesZeroReturnsEmpty()
    {
        hmi::History h(10);
        h.track("x");
        h.record("x", QVariant(42));
        QCOMPARE(h.samples("x", 0).size(), 0);
        QCOMPARE(h.samples("x", -1).size(), 0);
    }

    void recordFrameRecordsOnlyTracked()
    {
        hmi::History h(10);
        h.track("a");
        h.track("b");
        // "c" is tracked but not present in frame, "d" is not tracked at all.
        QVariantMap frame;
        frame["a"] = QVariant(10);
        frame["d"] = QVariant(99); // untracked
        h.recordFrame(frame);
        QCOMPARE(h.count("a"), 1);
        QCOMPARE(h.count("b"), 0);
        QCOMPARE(h.count("d"), 0);
        QVariantList s = h.samples("a", 100);
        QCOMPARE(s.size(), 1);
        QCOMPARE(s[0].toInt(), 10);
    }

    void countForUnknownTag()
    {
        hmi::History h(10);
        h.track("a");
        QCOMPARE(h.count("nope"), 0);
    }
};

QTEST_GUILESS_MAIN(TstHistory)
#include "tst_history.moc"