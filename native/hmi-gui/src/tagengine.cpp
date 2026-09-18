// native/hmi-gui/src/tagengine.cpp -- implementation. Owner: W1. See tagengine.h and
// gui/hmi_loader/tagengine.py (the specification).
#include "tagengine.h"

#include <QCoreApplication>
#include <QEventLoop>
#include <QJsonDocument>
#include <QTimer>

#include "log.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>

namespace hmi {

TagEngine::TagEngine(const QStringList &expectedTags, const QVariantList &alarmDefs,
                     const Options &options, QObject *parent)
    : QObject(parent),
      m_map(new TagMap(this)),
      m_history(options.historyDepth),
      m_alarms(new AlarmEngine(alarmDefs, this)),
      m_socket(new QUdpSocket(this)),
      m_watchdog(new QTimer(this)),
      m_subTimer(new QTimer(this)),
      m_daemonAddr(options.daemonHost),
      m_daemonPort(options.daemonPort)
{
    // Seed both spellings of every expected tag so no binding starts out
    // referencing a non-existent property.
    for (const QString &tag : expectedTags) {
        QString alias = tag;
        alias.replace(QLatin1Char('.'), QLatin1Char('_'));
        m_aliasToTag[alias] = tag;
        m_map->insert(tag, QVariant());
        m_map->insert(alias, QVariant());
    }

    // Mirror the link state into the map.
    m_map->insert(QStringLiteral("online"), false);

    // Collect alarm tags from definitions and seed them.
    QStringList alarmTags = m_alarms->alarmTags();
    for (const QString &tag : alarmTags) {
        QString alias = QString(tag).replace(QLatin1Char('.'), QLatin1Char('_'));
        if (!m_aliasToTag.contains(alias)) {
            m_aliasToTag[alias] = tag;
        }
    }

    // Build the complete list of recorded tags = expected + alarm tags.
    QStringList recordedTags = expectedTags + alarmTags;

    // Initialize ring buffers for all recorded tags.
    for (const QString &tag : recordedTags) {
        m_history.track(tag);
    }

    // Bind the UDP socket.
    if (!m_socket->bind(QHostAddress("127.0.0.1"), options.rxPort)) {
        QString firstError = m_socket->errorString();
        if (options.allowAnyPort && m_socket->bind(QHostAddress("127.0.0.1"), 0)) {
            qCWarning(lcHmi).noquote() << "Telemetry port" << options.rxPort << "is taken ("
                              << firstError << "); listening on" << m_socket->localPort()
                              << "instead";
        } else {
            qCCritical(lcHmi).noquote() << "Could not bind telemetry port" << options.rxPort
                             << "(" << firstError << "); UI will run offline";
        }
    }
    m_rxPort = m_socket->localPort();

    // Connect signals.
    connect(m_socket, &QUdpSocket::readyRead, this, &TagEngine::readPendingDatagrams);

    // Forward the alarm engine's change signal (Bus.alarmCount / activeAlarms
    // bind to it) and route QML assignments (Tags.do_relay1 = true) into
    // write-through commands.
    connect(m_alarms, &AlarmEngine::activeAlarmsChanged, this, &TagEngine::activeAlarmsChanged);
    connect(m_map, &TagMap::qmlWrite, this, &TagEngine::onQmlWrite);

    // Watchdog timer: 2500 ms -> onWatchdogTimeout.
    m_watchdog->setInterval(kWatchdogIntervalMs);
    connect(m_watchdog, &QTimer::timeout, this, &TagEngine::onWatchdogTimeout);
    m_watchdog->start();

    // Subscribe timer: 2000 ms -> subscribeToDaemon.
    m_subTimer->setInterval(kSubscribeIntervalMs);
    connect(m_subTimer, &QTimer::timeout, this, &TagEngine::subscribeToDaemon);
    m_subTimer->start();

    // Send the first subscribe immediately.
    subscribeToDaemon();
}

TagMap *TagEngine::tagMap() const { return m_map; }
quint16 TagEngine::rxPort() const { return m_rxPort; }
bool TagEngine::online() const { return m_online; }
int TagEngine::rxErrors() const { return m_rxErrors; }
int TagEngine::historyVersion() const { return m_historyVersion; }
QVariantList TagEngine::activeAlarms() const { return m_alarms->activeAlarms(); }
int TagEngine::alarmCount() const { return m_alarms->alarmCount(); }
History &TagEngine::historyBuffer() { return m_history; }
AlarmEngine &TagEngine::alarmEngine() { return *m_alarms; }

QString TagEngine::toWireName(const QString &name) const
{
    if (name.contains(QLatin1Char('.')))
        return name;
    return m_aliasToTag.value(name, name);
}

// ---------------------------------------------------------------- ingress

void TagEngine::readPendingDatagrams()
{
    while (m_socket->hasPendingDatagrams()) {
        qint64 size = m_socket->pendingDatagramSize();

        if (size > kMaxDatagramBytes) {
            // Oversized: read and discard, count error.
            QByteArray datagram(size, 0);
            m_socket->readDatagram(datagram.data(), datagram.size());
            countRxError();
            continue;
        }

        QByteArray datagram(size, 0);
        m_socket->readDatagram(datagram.data(), datagram.size());

        QJsonParseError err;
        QJsonDocument doc = QJsonDocument::fromJson(datagram, &err);

        if (err.error != QJsonParseError::NoError) {
            countRxError();
            continue;
        }

        if (!doc.isObject()) {
            countRxError();
            continue;
        }

        QJsonObject obj = doc.object();
        QString kind = obj.value(QStringLiteral("t")).toString();

        if (kind == QStringLiteral("tags")) {
            handleTelemetry(obj.toVariantMap());
        } else if (kind == QStringLiteral("ack")) {
            handleAck(obj.toVariantMap());
        } else {
            countRxError();
        }
    }
}

void TagEngine::handleTelemetry(const QVariantMap &msg)
{
    QVariant tagsVar = msg.value(QStringLiteral("tags"));

    if (!tagsVar.canConvert<QVariantMap>()) {
        countRxError();
        return;
    }

    QVariantMap tags = tagsVar.toMap();

    setOnline(true);
    m_watchdog->start();

    for (auto it = tags.constBegin(); it != tags.constEnd(); ++it) {
        QString tag = it.key();
        QVariant value = it.value();

        // Learn alias for undeclared tags (setdefault semantics).
        QString alias = tag;
        alias.replace(QLatin1Char('.'), QLatin1Char('_'));
        if (!m_aliasToTag.contains(alias)) {
            m_aliasToTag[alias] = tag;
        }

        // Only write when the value actually moved.
        // Comparing invalid to invalid yields equality (both are null).
        if (m_map->value(tag) != value) {
            m_map->insert(tag, value);
            m_map->insert(alias, value);
        }
    }

    // Record history for tracked tags.
    // History and alarms see the frame after the map, so a control binding
    // that fires on insert reads the previous frame's history (same as Python).
    m_history.recordFrame(tags);
    m_alarms->evaluate(tags);

    // Bump history version.
    ++m_historyVersion;
    emit historyVersionChanged();
}

void TagEngine::handleAck(const QVariantMap &msg)
{
    QString id = msg.value(QStringLiteral("id")).toString();
    if (id.isEmpty()) {
        id = "";
    }
    bool ok = msg.value(QStringLiteral("ok")).toBool();
    QString err = msg.value(QStringLiteral("err")).toString();
    QVariant tagsVar = msg.value(QStringLiteral("tags"));
    QVariantList tagsList;
    if (tagsVar.canConvert<QVariantList>()) {
        tagsList = tagsVar.toList();
    }

    // Fire pending correlation handlers before the general signal.
    AckHandler handler = m_pendingAcks.take(id);
    if (handler) {
        handler(id, ok, err, tagsList);
    }

    emit ackReceived(id, ok, err);
}

void TagEngine::onWatchdogTimeout()
{
    setOnline(false);
}

// ---------------------------------------------------------------- egress

void TagEngine::subscribeToDaemon()
{
    sendCommand({{QLatin1String("cmd"), QStringLiteral("subscribe")},
                 {QLatin1String("ttl"), kSubscribeTtlS}});
}

void TagEngine::sendCommand(const QVariantMap &cmd)
{
    QJsonObject obj;
    for (auto it = cmd.constBegin(); it != cmd.constEnd(); ++it) {
        QJsonValue val = QJsonValue::fromVariant(it.value());
        obj.insert(it.key(), val);
    }
    QByteArray bytes = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    m_socket->writeDatagram(bytes, m_daemonAddr, m_daemonPort);
}

void TagEngine::write(const QString &tag, const QVariant &value)
{
    sendCommand({{QLatin1String("id"), nextId()},
                 {QLatin1String("cmd"), QStringLiteral("set")},
                 {QLatin1String("tag"), toWireName(tag)},
                 {QLatin1String("value"), value}});
}

void TagEngine::pulse(const QString &tag, int ms)
{
    sendCommand({{QLatin1String("id"), nextId()},
                 {QLatin1String("cmd"), QStringLiteral("pulse")},
                 {QLatin1String("tag"), toWireName(tag)},
                 {QLatin1String("ms"), ms}});
}

void TagEngine::uart_tx(const QString &data)
{
    sendCommand({{QLatin1String("id"), nextId()},
                 {QLatin1String("cmd"), QStringLiteral("uart_tx")},
                 {QLatin1String("data"), data}});
}

void TagEngine::ping()
{
    sendCommand({{QLatin1String("cmd"), QStringLiteral("ping")},
                 {QLatin1String("id"), QStringLiteral("qml-ping")}});
}

QVariant TagEngine::value(const QString &name, const QVariant &fallback)
{
    QVariant val = m_map->value(name);
    if (val.isNull()) {
        QString alt = name;
        alt.replace(QLatin1Char('.'), QLatin1Char('_'));
        val = m_map->value(alt);
    }
    if (val.isNull()) {
        return fallback;
    }
    return val;
}

QVariantList TagEngine::list_tags()
{
    QEventLoop loop;
    QVariantList result;

    auto handler = [this, &result, &loop](const QString &, bool ok, const QString &,
                                          const QVariantList &tags) {
        if (ok) {
            result = tags;
        }
        loop.quit();
    };

    QString cid = nextId();
    m_pendingAcks[cid] = handler;
    sendCommand({{QLatin1String("cmd"), QStringLiteral("list")},
                 {QLatin1String("id"), cid}});

    QTimer::singleShot(kBlockingReplyTimeoutMs, &loop, &QEventLoop::quit);
    loop.exec();

    m_pendingAcks.remove(cid);
    emit listReceived(result);
    return result;
}

void TagEngine::unsubscribe()
{
    QEventLoop loop;

    auto handler = [this, &loop](const QString &, bool ok, const QString &,
                                 const QVariantList &) {
        if (ok) {
            emit unsubscribed();
        }
        loop.quit();
    };

    QString cid = nextId();
    m_pendingAcks[cid] = handler;
    sendCommand({{QLatin1String("cmd"), QStringLiteral("unsubscribe")},
                 {QLatin1String("id"), cid}});

    QTimer::singleShot(kBlockingReplyTimeoutMs, &loop, &QEventLoop::quit);
    loop.exec();

    m_pendingAcks.remove(cid);
}

QString TagEngine::nextId()
{
    ++m_cmdSeq;
    return QStringLiteral("gui-%1").arg(m_cmdSeq);
}

// ---------------------------------------------------------------- public slots
// These are already declared in the header.

QVariantList TagEngine::history(const QString &tag, int n)
{
    return m_history.samples(toWireName(tag), n);
}

void TagEngine::acknowledge(const QString &tag)
{
    m_alarms->acknowledge(toWireName(tag));
}

void TagEngine::onQmlWrite(const QString &key, const QVariant &value)
{
    if (key == QLatin1String("online"))
        return;
    write(key, value);
}

void TagEngine::setOnline(bool state)
{
    if (m_online == state)
        return;
    m_online = state;
    m_map->insert(QStringLiteral("online"), state);
    emit onlineChanged();
}

void TagEngine::countRxError()
{
    ++m_rxErrors;
    emit rxErrorsChanged();
}

} // namespace hmi