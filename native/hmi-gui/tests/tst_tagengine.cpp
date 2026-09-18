// native/hmi-gui/tests/tst_tagengine.cpp
// QTest cases for TagEngine covering seeding, telemetry, commands, acks, and
// write-through via QML.
#include "tagengine.h"

#include <QtTest>
#include <QJsonDocument>
#include <QQmlEngine>
#include <QQmlComponent>
#include <QQmlContext>
#include <QUdpSocket>

static QByteArray receiveOneDatagram(QUdpSocket &sock, int timeoutMs = 1000)
{
    if (sock.waitForReadyRead(timeoutMs)) {
        QByteArray datagram;
        datagram.resize(sock.pendingDatagramSize());
        sock.readDatagram(datagram.data(), datagram.size());
        return datagram;
    }
    return {};
}

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

    // 1. seeding: Tags["ai.pot"], Tags["ai_pot"] exist and are invalid;
    //    online is false; toWireName("ai_pot") == "ai.pot".
    void test_seeding()
    {
        hmi::TagEngine::Options o;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("ai.pot"), QStringLiteral("di.estop")}, {}, o);

        // Both spellings present and invalid (QVariant() == null).
        QVERIFY(e.tagMap()->value(QStringLiteral("ai.pot")).isNull());
        QVERIFY(e.tagMap()->value(QStringLiteral("ai_pot")).isNull());
        QVERIFY(e.tagMap()->value(QStringLiteral("di.estop")).isNull());
        QVERIFY(e.tagMap()->value(QStringLiteral("di_estop")).isNull());

        // online is false.
        QVERIFY(e.tagMap()->value(QStringLiteral("online")).toBool() == false);
        QCOMPARE(e.online(), false);

        // toWireName resolves underscored to dotted.
        QCOMPARE(e.toWireName(QStringLiteral("ai_pot")), QStringLiteral("ai.pot"));
        QCOMPARE(e.toWireName(QStringLiteral("di_estop")), QStringLiteral("di.estop"));
    }

    // 2. first datagram the daemon receives is {"cmd":"subscribe","ttl":5}.
    void test_subscribe_sent()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({}, {}, o);

        // The engine sent subscribe -> daemonPort.
        QByteArray datagram = receiveOneDatagram(daemonSock);
        QVERIFY(datagram.size() > 0);
        QJsonParseError err;
        QJsonDocument doc = QJsonDocument::fromJson(datagram, &err);
        QCOMPARE(err.error, QJsonParseError::NoError);
        QVERIFY(doc.isObject());
        QCOMPARE(doc.object().value("cmd").toString(), QStringLiteral("subscribe"));
        QCOMPARE(doc.object().value("ttl").toInt(), 5);
    }

    // 3. a tags frame sets both spellings, online true, onlineChanged once.
    //    a second identical frame emits no valueChanged on the map.
    void test_telemetry_sets_map_and_online()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("ai.pot")}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());

        // Drain the subscribe datagram.
        receiveOneDatagram(daemonSock);

        // Send a tags frame.
        QString frame = "{\"t\":\"tags\",\"seq\":1,\"ts\":1000,\"src\":\"hmi-hwd\",\"tags\":{\"ai.pot\":2.1,\"di.estop\":true}}";

        QSignalSpy onlineChangedSpy(&e, &hmi::TagEngine::onlineChanged);

        // Send the datagram to the engine's ACTUAL rx port.
        QUdpSocket sender;
        sender.bind();
        sender.writeDatagram(frame.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);

        QTest::qWait(200);

        // online should be true now.
        QCOMPARE(e.online(), true);
        QCOMPARE(onlineChangedSpy.count(), 1);

        // Both spellings set.
        QCOMPARE(e.tagMap()->value(QStringLiteral("ai.pot")).toDouble(), 2.1);
        QCOMPARE(e.tagMap()->value(QStringLiteral("ai_pot")).toDouble(), 2.1);
        QCOMPARE(e.tagMap()->value(QStringLiteral("di.estop")).toBool(), true);
        QCOMPARE(e.tagMap()->value(QStringLiteral("di_estop")).toBool(), true);

        // Second identical frame: no onlineChanged.
        onlineChangedSpy.clear();

        sender.writeDatagram(frame.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);

        // onlineChanged should NOT fire again since online was already true.
        QCOMPARE(onlineChangedSpy.count(), 0);

        // Values should still be the same.
        QCOMPARE(e.tagMap()->value(QStringLiteral("ai.pot")).toDouble(), 2.1);
    }

    // 4. undeclared tag in a frame becomes readable and toWireName learns it.
    void test_undeclared_tag_learning()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({}, {}, o); // no expected tags

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        // Send an undeclared tag.
        QString frame = "{\"t\":\"tags\",\"tags\":{\"my.new.tag\":42.5}}";

        QUdpSocket sender;
        sender.bind();
        sender.writeDatagram(frame.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);

        // The tag should be in the map under both spellings.
        QVERIFY(e.tagMap()->value(QStringLiteral("my.new.tag")).isValid());
        QCOMPARE(e.tagMap()->value(QStringLiteral("my.new.tag")).toDouble(), 42.5);
        QVERIFY(e.tagMap()->value(QStringLiteral("my_new_tag")).isValid());
        QCOMPARE(e.tagMap()->value(QStringLiteral("my_new_tag")).toDouble(), 42.5);

        // toWireName should resolve the alias.
        QCOMPARE(e.toWireName(QStringLiteral("my_new_tag")), QStringLiteral("my.new.tag"));
    }

    // 5. null value in a frame -> both keys invalid; value("x", 7) returns 7.
    void test_null_value_fallback()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("x")}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        // Send a frame with null for x and a valid value for x_2.
        QString frame = "{\"t\":\"tags\",\"tags\":{\"x\":null,\"x_2\":3.14}}";

        QUdpSocket sender;
        sender.bind();
        sender.writeDatagram(frame.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);

        // x should be invalid (null).
        QVERIFY(e.tagMap()->value(QStringLiteral("x")).isNull());
        // x_2 should be valid (learned as undeclared tag).
        QVERIFY(e.tagMap()->value(QStringLiteral("x_2")).isValid());
        QCOMPARE(e.tagMap()->value(QStringLiteral("x_2")).toDouble(), 3.14);

        // value("x", 7) returns 7.
        QCOMPARE(e.value(QStringLiteral("x"), QVariant(7)).toInt(), 7);
        // But value("x_2", 7) returns the actual value.
        QCOMPARE(e.value(QStringLiteral("x_2"), QVariant(7)).toDouble(), 3.14);
    }

    // 6. watchdog: after a frame, online becomes false within ~3 s.
    void test_watchdog_offline()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("x")}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        // Send a frame to set online=true.
        QString frame = "{\"t\":\"tags\",\"tags\":{\"x\":1}}";
        QUdpSocket sender;
        sender.bind();
        sender.writeDatagram(frame.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);

        QCOMPARE(e.online(), true);

        // Wait for watchdog to fire (2.5s + margin).
        QTRY_VERIFY_WITH_TIMEOUT(!e.online(), 4000);
    }

    // 7. rx error counting: oversized, non-JSON, JSON array, {"t":"nope"},
    //    {"t":"tags","tags":5} -> rxErrors increments once each.
    void test_rx_error_counting()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("x")}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        QUdpSocket sender;
        sender.bind();
        QCOMPARE(e.rxErrors(), 0);

        // 7a: oversized (9000 bytes).
        QByteArray oversized(9000, 'x');
        sender.writeDatagram(oversized, QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(50);
        QCOMPARE(e.rxErrors(), 1);

        // 7b: non-JSON (plain text).
        sender.writeDatagram("hello world", QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(50);
        QCOMPARE(e.rxErrors(), 2);

        // 7c: JSON array (not object).
        sender.writeDatagram("[1,2,3]", QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(50);
        QCOMPARE(e.rxErrors(), 3);

        // 7d: unknown type "nope".
        sender.writeDatagram("{\"t\":\"nope\"}", QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(50);
        QCOMPARE(e.rxErrors(), 4);

        // 7e: {"t":"tags","tags":5} -> tags is not a map.
        sender.writeDatagram("{\"t\":\"tags\",\"tags\":5}", QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(50);
        QCOMPARE(e.rxErrors(), 5);

        // Engine still usable after errors: send a valid frame.
        sender.writeDatagram("{\"t\":\"tags\",\"tags\":{\"x\":1}}", QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);
        QCOMPARE(e.online(), true);
        QCOMPARE(e.tagMap()->value(QStringLiteral("x")).toInt(), 1);
    }

    // 8. write, pulse, uart_tx, ping: id counters and command shapes.
    void test_command_shapes_and_ids()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        // Seed "do.relay1" so the alias "do_relay1" -> "do.relay1" is known.
        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        o.rxPort = 0;
        hmi::TagEngine e({QStringLiteral("do.relay1"), QStringLiteral("a")}, {}, o);

        // Drain the subscribe datagram.
        receiveOneDatagram(daemonSock);

        // 8a: write("do_relay1", true) -> {"id":"gui-1","cmd":"set","tag":"do.relay1","value":true}
        e.write(QStringLiteral("do_relay1"), QVariant(true));
        QTest::qWait(50);
        QByteArray d1 = receiveOneDatagram(daemonSock);
        QVERIFY(!d1.isEmpty());
        QJsonObject jo1 = QJsonDocument::fromJson(d1).object();
        QCOMPARE(jo1.value("id").toString(), QStringLiteral("gui-1"));
        QCOMPARE(jo1.value("cmd").toString(), QStringLiteral("set"));
        QCOMPARE(jo1.value("tag").toString(), QStringLiteral("do.relay1"));
        QCOMPARE(jo1.value("value").toBool(), true);

        // 8b: pulse("do_relay1", 250) -> gui-2
        e.pulse(QStringLiteral("do_relay1"), 250);
        QTest::qWait(50);
        QByteArray d2 = receiveOneDatagram(daemonSock);
        QJsonObject jo2 = QJsonDocument::fromJson(d2).object();
        QCOMPARE(jo2.value("id").toString(), QStringLiteral("gui-2"));
        QCOMPARE(jo2.value("cmd").toString(), QStringLiteral("pulse"));
        QCOMPARE(jo2.value("ms").toInt(), 250);

        // 8c: uart_tx("hello\n") -> gui-3
        e.uart_tx(QStringLiteral("hello\n"));
        QTest::qWait(50);
        QByteArray d3 = receiveOneDatagram(daemonSock);
        QJsonObject jo3 = QJsonDocument::fromJson(d3).object();
        QCOMPARE(jo3.value("id").toString(), QStringLiteral("gui-3"));
        QCOMPARE(jo3.value("cmd").toString(), QStringLiteral("uart_tx"));
        QCOMPARE(jo3.value("data").toString(), QStringLiteral("hello\n"));

        // 8d: ping has id "qml-ping" and does NOT advance the counter.
        e.ping();
        QTest::qWait(50);
        QByteArray dp = receiveOneDatagram(daemonSock);
        QJsonObject jop = QJsonDocument::fromJson(dp).object();
        QCOMPARE(jop.value("cmd").toString(), QStringLiteral("ping"));
        QCOMPARE(jop.value("id").toString(), QStringLiteral("qml-ping"));

        // Next command should still be gui-4.
        e.write(QStringLiteral("a"), 1);
        QTest::qWait(50);
        QByteArray d4 = receiveOneDatagram(daemonSock);
        QJsonObject jo4 = QJsonDocument::fromJson(d4).object();
        QCOMPARE(jo4.value("id").toString(), QStringLiteral("gui-4"));
    }

    // 9. ack routing: send {"t":"ack","id":"gui-1","ok":false,"err":"not_writable"}
    //    -> ackReceived spy has exactly those arguments.
    void test_ack_routing()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        QSignalSpy ackSpy(&e, &hmi::TagEngine::ackReceived);

        // Send an ack frame.
        QString ack = "{\"t\":\"ack\",\"id\":\"gui-1\",\"ok\":false,\"err\":\"not_writable\"}";
        QUdpSocket sender;
        sender.bind();
        sender.writeDatagram(ack.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        QTest::qWait(200);

        QCOMPARE(ackSpy.size(), 1);
        QList<QVariant> args = ackSpy[0];
        QCOMPARE(args[0].toString(), QStringLiteral("gui-1"));
        QCOMPARE(args[1].toBool(), false);
        QCOMPARE(args[2].toString(), QStringLiteral("not_writable"));
    }

    // 10. list_tags(): daemon answers with tags -> returns list and listReceived fired.
    //     With no answer returns empty within ~2 s.
    void test_list_tags()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({}, {}, o);

        quint16 engineRxPort = static_cast<quint16>(e.rxPort());
        receiveOneDatagram(daemonSock);

        QSignalSpy listSpy(&e, &hmi::TagEngine::listReceived);

        // Send a list command and simulate daemon ack.
        QTimer::singleShot(50, [&]() {
            // The engine sends {"cmd":"list","id":"gui-N"}. We respond.
            QByteArray datagram;
            datagram.resize(daemonSock.pendingDatagramSize());
            daemonSock.readDatagram(datagram.data(), datagram.size());

            QJsonDocument doc = QJsonDocument::fromJson(datagram);
            QString cmdId = doc.object().value("id").toString();

            QString reply = "{\"t\":\"ack\",\"id\":\"" + cmdId.toUtf8() +
                            "\",\"ok\":true,\"tags\":[\"a\",\"b\",\"c\"]}";
            QUdpSocket sender;
            sender.bind();
            sender.writeDatagram(reply.toUtf8(), QHostAddress("127.0.0.1"), engineRxPort);
        });

        QVariantList result = e.list_tags();
        QTest::qWait(500);

        QCOMPARE(result.size(), 3);
        QCOMPARE(result[0].toString(), QStringLiteral("a"));
        QCOMPARE(result[1].toString(), QStringLiteral("b"));
        QCOMPARE(result[2].toString(), QStringLiteral("c"));
        QCOMPARE(listSpy.size(), 1);
    }

    void test_list_tags_timeout()
    {
        QUdpSocket daemonSock;
        daemonSock.bind(QHostAddress("127.0.0.1"), 0);
        quint16 daemonPort = static_cast<quint16>(daemonSock.localPort());

        hmi::TagEngine::Options o;
        o.daemonPort = daemonPort;
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({}, {}, o);

        receiveOneDatagram(daemonSock);

        // Don't respond to the list command - it should timeout.
        QVariantList result = e.list_tags();
        QTest::qWait(3000);

        // Should return empty on timeout.
        QVERIFY(result.isEmpty());
    }

    // 11. write-through: calling write() from C++ (simulating what QML does via
    // Bus.write()) fires qmlWrite via TagMap::onQmlWrite, the daemon receives
    // the set command, and the map itself is NOT optimistically updated.
    //
    // NOTE: In Qt 6, QQmlPropertyMap inherits QHash::insert() directly, so
    // subclassing and overriding updateValue() has no C++-side effect. The
    // write-through path used in production is Bus.write() / TagEngine::write()
    // which calls sendCommand directly — verified in test_command_shapes_and_ids.
    // This test confirms the write() slot itself does NOT modify the tag map.
    void test_write_through_qml()
    {
        // The README's promise: assigning an underscored alias from QML sends a
        // `set` command. QQmlPropertyMap::updateValue() is the hook Qt gives
        // for exactly this; TagMap emits qmlWrite() from it.
        QUdpSocket daemonSock;
        QVERIFY(daemonSock.bind(QHostAddress("127.0.0.1"), 0));
        hmi::TagEngine::Options o;
        o.daemonPort = static_cast<quint16>(daemonSock.localPort());
        o.rxPort = 0;
        o.allowAnyPort = true;
        hmi::TagEngine e({QStringLiteral("do.relay1")}, {}, o);
        receiveOneDatagram(daemonSock);   // drain the subscribe

        QQmlEngine qml;
        qml.rootContext()->setContextProperty(QStringLiteral("Tags"), e.tagMap());
        QQmlComponent component(&qml);
        component.setData("import QtQuick 2.15\nQtObject { Component.onCompleted: Tags.do_relay1 = true }\n",
                          QUrl());
        QObject *obj = component.create();
        QVERIFY2(obj != nullptr, qPrintable(component.errorString()));

        QByteArray datagram = receiveOneDatagram(daemonSock);
        QVERIFY2(!datagram.isEmpty(), "no set command reached the daemon");
        const QJsonObject jo = QJsonDocument::fromJson(datagram).object();
        QCOMPARE(jo.value("cmd").toString(), QStringLiteral("set"));
        QCOMPARE(jo.value("tag").toString(), QStringLiteral("do.relay1"));
        QCOMPARE(jo.value("value").toBool(), true);
        QVERIFY(jo.value("id").toString().startsWith(QStringLiteral("gui-")));

        // No optimistic update: the map still shows the (absent) read-back.
        QVERIFY(!e.tagMap()->value(QStringLiteral("do_relay1")).toBool());
        delete obj;
    }
};

QTEST_GUILESS_MAIN(TstTagEngine)
#include "tst_tagengine.moc"