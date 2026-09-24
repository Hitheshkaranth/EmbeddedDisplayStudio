// native/hmi-gui/tests/tst_alarms.cpp
// QTest case for AlarmEngine.
#include "alarmengine.h"

#include <QSignalSpy>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtTest>

// Shared test fixture with deterministic clock.
class ClockAlarm : public hmi::AlarmEngine {
public:
    explicit ClockAlarm(const QVariantList &defs, QObject *parent = nullptr)
        : hmi::AlarmEngine(defs, parent), m_tick(0), m_ts("2025-01-01T00:00:00") {}
    void tick() { m_ts = "2025-01-01T00:00:0" + QString::number(++m_tick); }
    void tick(int v) { m_ts = "2025-01-01T00:00:" + QString::number(v, 10, 2); }
protected:
    QString now() const override { return m_ts; }
private:
    int m_tick;
    QString m_ts;
};

// Helper: build a simple alarm def.
static QVariantMap makeAlarmDef(const QString &tag,
                                const QString &label = QString(),
                                const QString &unit = QString(),
                                const QVariantMap &crit = QVariantMap(),
                                const QVariantMap &warn = QVariantMap())
{
    QVariantMap d;
    d["tag"] = tag;
    if (!label.isNull()) d["label"] = label;
    if (!unit.isNull()) d["unit"] = unit;
    if (!crit.isEmpty()) d["critical"] = QVariant(crit);
    if (!warn.isEmpty()) d["warning"] = QVariant(warn);
    return d;
}

class TstAlarmEngine : public QObject {
    Q_OBJECT
private slots:
    void emptyDefinitionsHaveNoTags()
    {
        hmi::AlarmEngine e({});
        QVERIFY(!e.hasDefinitions());
        QCOMPARE(e.alarmCount(), 0);
    }

    // --- thresholdFired operators ---

    void opGt()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(5.0, ">", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(3.0, ">", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(2.0, ">", 3.0));
    }

    void opGte()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(3.0, ">=", 3.0));
        QVERIFY(hmi::AlarmEngine::thresholdFired(4.0, ">=", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(2.0, ">=", 3.0));
    }

    void opLt()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(2.0, "<", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(3.0, "<", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(4.0, "<", 3.0));
    }

    void opLte()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(3.0, "<=", 3.0));
        QVERIFY(hmi::AlarmEngine::thresholdFired(2.0, "<=", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(4.0, "<=", 3.0));
    }

    void opEq()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(3.0, "==", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(3.1, "==", 3.0));
    }

    void opNeq()
    {
        QVERIFY(hmi::AlarmEngine::thresholdFired(3.1, "!=", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(3.0, "!=", 3.0));
    }

    void unknownOpReturnsFalse()
    {
        QVERIFY(!hmi::AlarmEngine::thresholdFired(5.0, "<<<", 3.0));
        QVERIFY(!hmi::AlarmEngine::thresholdFired(5.0, "xyz", 3.0));
    }

    // --- alarm evaluation ---

    void criticalWinsOverWarning()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap{{"op", QString(">")}, {"value", 2.0}},
            QVariantMap{{"op", QString(">")}, {"value", 1.0}}));

        hmi::AlarmEngine e(defs);
        QVariantMap frame;
        frame["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame));

        QVariantList active = e.activeAlarms();
        QCOMPARE(active.size(), 1);
        QCOMPARE(active[0].toMap()["severity"].toString(), QString("critical"));
    }

    void warningWhenOnlyWarningFires()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap{{"op", QString(">")}, {"value", 5.0}},
            QVariantMap{{"op", QString(">")}, {"value", 2.0}}));

        hmi::AlarmEngine e(defs);
        QVariantMap frame;
        frame["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame));

        QVariantList active = e.activeAlarms();
        QCOMPARE(active.size(), 1);
        QCOMPARE(active[0].toMap()["severity"].toString(), QString("warning"));
    }

    void nullValueClearsActiveAlarm()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 2.0}}));

        hmi::AlarmEngine e(defs);

        QVariantMap frame1;
        frame1["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame1));
        QCOMPARE(e.alarmCount(), 1);

        // Absent tag -> invalid value -> clears.
        QVERIFY(e.evaluate(QVariantMap()));
        QCOMPARE(e.alarmCount(), 0);
    }

    void jsonNullFromWireIsInactive()
    {
        // A JSON null parsed by Qt is QVariant(nullptr): valid but null. It
        // must not be read as 0, or a "< 10" alarm fires on a failed read.
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Pot", "", QVariantMap(),
            QVariantMap{{"op", QString("<")}, {"value", 10.0}}));
        hmi::AlarmEngine e(defs);
        const QVariantMap frame = QJsonDocument::fromJson("{\"ai.pot\": null}").object().toVariantMap();
        QVERIFY(frame.value("ai.pot").isValid());
        QVERIFY(frame.value("ai.pot").isNull());
        QVERIFY(!e.evaluate(frame));
        QCOMPARE(e.alarmCount(), 0);
    }

    void thresholdValueMustBeNumeric()
    {
        // Python: isinstance(val, (int, float)) -- a bool or a string never fires.
        QVariantList defs;
        defs.append(makeAlarmDef("a", "", "", QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", true}}));
        defs.append(makeAlarmDef("b", "", "", QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", QString("0")}}));
        defs.append(makeAlarmDef("c", "", "", QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 0}}));
        hmi::AlarmEngine e(defs);
        QVERIFY(e.evaluate(QVariantMap{{"a", 5.0}, {"b", 5.0}, {"c", 5.0}}));
        QCOMPARE(e.alarmCount(), 1);
        QCOMPARE(e.activeAlarms().first().toMap().value("tag").toString(), QString("c"));
    }

    void sameSecondTiesKeepActivationOrder()
    {
        // Two alarms raised in one frame share a timestamp; Python keeps
        // definition order (dict insertion). A later activation with the same
        // timestamp sorts after them.
        QVariantList defs;
        for (const char *t : {"x", "y", "z"})
            defs.append(makeAlarmDef(t, "", "", QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 0}}));
        ClockAlarm e(defs);
        QVERIFY(e.evaluate(QVariantMap{{"z", 1}, {"x", 1}}));   // frame order irrelevant
        QVERIFY(e.evaluate(QVariantMap{{"z", 1}, {"x", 1}, {"y", 1}}));
        QStringList order;
        for (const QVariant &a : e.activeAlarms())
            order << a.toMap().value("tag").toString();
        QCOMPARE(order, (QStringList{"x", "z", "y"}));
    }

    void absentValueClearsActiveAlarm()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 2.0}}));

        hmi::AlarmEngine e(defs);

        QVariantMap frame1;
        frame1["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame1));
        QCOMPARE(e.alarmCount(), 1);

        // Explicitly null.
        QVariantMap frame2;
        frame2["ai.pot"] = QVariant();
        QVERIFY(e.evaluate(frame2));
        QCOMPARE(e.alarmCount(), 0);
    }

void simpleActivationWorks()
    {
        // Minimal test: one alarm def, value exceeds threshold.
        QVariantList defs;
        {
            QVariantMap def;
            def["tag"] = "ai.pot";
            def["label"] = "Input Voltage";
            def["unit"] = "V";
            QVariantMap w;
            w["op"] = QString(">");
            w["value"] = 2.0;
            def["warning"] = QVariant(w);
            defs.append(def);
        }
        hmi::AlarmEngine e(defs);
        QVariantMap frame;
        frame["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame));
        QCOMPARE(e.alarmCount(), 1);
        QCOMPARE(e.activeAlarms().size(), 1);
    }

    void persistenceKeepsTimestampAndAcknowledged()
    {
        // Use the same construction pattern as the passing escalation test.
        ClockAlarm e({makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap(),
            QVariantMap{{"op", QString(">")}, {"value", 2.0}})});
        e.tick();

        QVariantMap frame1;
        frame1["ai.pot"] = 3.0;
        // First frame activates -> changed must be true.
        QVERIFY2(e.evaluate(frame1), "First evaluation must activate the alarm");
        QCOMPARE(e.alarmCount(), 1);

        QVariantList active = e.activeAlarms();
        QCOMPARE(active[0].toMap()["timestamp"].toString(), QString("2025-01-01T00:00:01"));
        QCOMPARE(active[0].toMap()["acknowledged"].toBool(), false);

        // Acknowledge it.
        QSignalSpy spy(&e, &hmi::AlarmEngine::activeAlarmsChanged);
        QVERIFY(e.acknowledge("ai.pot"));
        QCOMPARE(spy.count(), 1);

        // Next frame: alarm persists unchanged.
        e.tick();
        // No change -> evaluate returns false, signal not emitted.
        QVERIFY(!e.evaluate(frame1));
        // But alarm still active, timestamp and ack preserved.
        QCOMPARE(e.alarmCount(), 1);
        QVariantList active2 = e.activeAlarms();
        QCOMPARE(active2[0].toMap()["timestamp"].toString(), QString("2025-01-01T00:00:01"));
        QCOMPARE(active2[0].toMap()["acknowledged"].toBool(), true);
    }

    void escalationWarningToCritical()
    {
        ClockAlarm e({makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap{{"op", QString(">")}, {"value", 4.0}},
            QVariantMap{{"op", QString(">")}, {"value", 2.0}})});

        e.tick();

        // Frame: warning fires (value=3.0).
        QVariantMap frame1;
        frame1["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame1));
        QVariantList active = e.activeAlarms();
        QCOMPARE(active[0].toMap()["severity"].toString(), QString("warning"));
        QString ts1 = active[0].toMap()["timestamp"].toString();
        QCOMPARE(active[0].toMap()["message"].toString(), QString("Input Voltage 3V"));

        // Frame: escalation (value=5.0) -> critical.
        e.tick();
        QVariantMap frame2;
        frame2["ai.pot"] = 5.0;
        QVERIFY(e.evaluate(frame2));
        active = e.activeAlarms();
        QCOMPARE(active[0].toMap()["severity"].toString(), QString("critical"));
        QCOMPARE(active[0].toMap()["timestamp"].toString(), ts1);
        QCOMPARE(active[0].toMap()["message"].toString(), QString("Input Voltage 5V"));
    }

    void frameNoChangeReturnsFalse()
    {
        ClockAlarm e({makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 2.0}})});

        e.tick();

        QVariantMap frame;
        frame["ai.pot"] = 3.0;
        QVERIFY(e.evaluate(frame)); // first -> activated, changed=true

        QSignalSpy spy(&e, &hmi::AlarmEngine::activeAlarmsChanged);
        e.tick();
        QVERIFY(!e.evaluate(frame));
        QCOMPARE(spy.count(), 0);
    }

    void percentGFormatting()
    {
        // 3.0 -> "3"
        {
            QVariantList defs;
            defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
                QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 2.0}}));
            hmi::AlarmEngine e(defs);
            QVariantMap frame;
            frame["ai.pot"] = 3.0;
            e.evaluate(frame);
            QCOMPARE(e.activeAlarms()[0].toMap()["message"].toString(),
                     QString("Input Voltage 3V"));
        }

        // 2.5 -> "2.5"
        {
            QVariantList defs;
            defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
                QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 2.0}}));
            hmi::AlarmEngine e(defs);
            QVariantMap frame;
            frame["ai.pot"] = 2.5;
            e.evaluate(frame);
            QCOMPARE(e.activeAlarms()[0].toMap()["message"].toString(),
                     QString("Input Voltage 2.5V"));
        }
    }

    void percentGFormattingSmall()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.pot", "Input Voltage", "V",
            QVariantMap(), QVariantMap{{"op", QString(">")}, {"value", 0.0}}));

        hmi::AlarmEngine e(defs);
        QVariantMap frame;
        frame["ai.pot"] = 0.00001;
        e.evaluate(frame);
        QString msg = e.activeAlarms()[0].toMap()["message"].toString();
        QVERIFY(msg.contains("1e"));
    }

    void sortingTwoCriticalsAndOneWarning()
    {
        ClockAlarm e({
            makeAlarmDef("ai.a", "A", "V",
                QVariantMap{{"op", QString(">")}, {"value", 0}}),
            makeAlarmDef("ai.b", "B", "V",
                QVariantMap{{"op", QString(">")}, {"value", 0}}),
            makeAlarmDef("ai.c", "C", "V",
                QVariantMap(),
                QVariantMap{{"op", QString(">")}, {"value", 0}}),
        });

        QVariantMap frame;
        frame["ai.a"] = 1.0; e.tick(1);
        e.evaluate(frame);
        frame["ai.b"] = 1.0; e.tick(2);
        e.evaluate(frame);
        frame["ai.c"] = 1.0; e.tick(3);
        e.evaluate(frame);

        QVariantList active = e.activeAlarms();
        QCOMPARE(active.size(), 3);
        // critical first (newest first), then warning.
        QCOMPARE(active[0].toMap()["tag"].toString(), QString("ai.b"));
        QCOMPARE(active[1].toMap()["tag"].toString(), QString("ai.a"));
        QCOMPARE(active[2].toMap()["tag"].toString(), QString("ai.c"));
    }

    void acknowledgeUnknownTagReturnsFalse()
    {
        hmi::AlarmEngine e({});

        QSignalSpy spy(&e, &hmi::AlarmEngine::activeAlarmsChanged);
        QVERIFY(!e.acknowledge("nope"));
        QCOMPARE(spy.count(), 0);
    }

    void alarmTagsDedupesAndIgnoresMalformed()
    {
        QVariantList defs;
        defs.append(makeAlarmDef("ai.a"));
        defs.append(makeAlarmDef("ai.a")); // dup
        defs.append(QVariant(42));          // not a map
        {
            QVariantMap d; d["label"] = "no tag";
            defs.append(d); // no string tag
        }
        defs.append(makeAlarmDef("ai.b"));

        hmi::AlarmEngine e(defs);
        QStringList tags = e.alarmTags();
        QCOMPARE(tags.size(), 2);
        QCOMPARE(tags[0], QString("ai.a"));
        QCOMPARE(tags[1], QString("ai.b"));
    }

    void valueKeepsOriginalType()
    {
        hmi::AlarmEngine e({makeAlarmDef("di.estop", "E-Stop", QString(),
            QVariantMap{{"op", QString("==")}, {"value", 1}})});

        QVariantMap frame;
        frame["di.estop"] = QVariant(true);
        e.evaluate(frame);

        QVariantList active = e.activeAlarms();
        QCOMPARE(active.size(), 1);
        QCOMPARE(active[0].toMap()["value"].userType(), QMetaType::Bool);
        QVERIFY(active[0].toMap()["value"].toBool());
    }
};

QTEST_GUILESS_MAIN(TstAlarmEngine)
#include "tst_alarms.moc"