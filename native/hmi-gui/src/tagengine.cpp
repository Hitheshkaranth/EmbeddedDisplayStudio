// native/hmi-gui/src/tagengine.cpp -- STUB. Owner: W1. See tagengine.h and
// gui/hmi_loader/tagengine.py (the specification).
#include "tagengine.h"

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
    Q_UNUSED(expectedTags);
    // TODO(W1): seed map + aliases, track history, bind socket, start timers,
    // send the first subscribe.
    connect(m_alarms, &AlarmEngine::activeAlarmsChanged, this, &TagEngine::activeAlarmsChanged);
    connect(m_map, &TagMap::qmlWrite, this, &TagEngine::onQmlWrite);
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

void TagEngine::write(const QString &tag, const QVariant &value)
{
    Q_UNUSED(tag);
    Q_UNUSED(value);   // TODO(W1)
}

void TagEngine::pulse(const QString &tag, int ms)
{
    Q_UNUSED(tag);
    Q_UNUSED(ms);   // TODO(W1)
}

void TagEngine::uart_tx(const QString &data) { Q_UNUSED(data); }   // TODO(W1)
void TagEngine::ping() {}                                            // TODO(W1)

QVariant TagEngine::value(const QString &name, const QVariant &fallback)
{
    Q_UNUSED(name);
    return fallback;   // TODO(W1)
}

QVariantList TagEngine::list_tags() { return {}; }   // TODO(W1)
void TagEngine::unsubscribe() {}                     // TODO(W1)

QVariantList TagEngine::history(const QString &tag, int n)
{
    return m_history.samples(toWireName(tag), n);
}

void TagEngine::acknowledge(const QString &tag)
{
    m_alarms->acknowledge(toWireName(tag));
}

void TagEngine::readPendingDatagrams() {}   // TODO(W1)
void TagEngine::onWatchdogTimeout() { setOnline(false); }
void TagEngine::subscribeToDaemon() {}      // TODO(W1)

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

void TagEngine::handleTelemetry(const QVariantMap &msg) { Q_UNUSED(msg); }   // TODO(W1)
void TagEngine::handleAck(const QVariantMap &msg) { Q_UNUSED(msg); }         // TODO(W1)
QString TagEngine::nextId() { return QStringLiteral("gui-%1").arg(++m_cmdSeq); }
void TagEngine::sendCommand(const QVariantMap &cmd) { Q_UNUSED(cmd); }       // TODO(W1)

} // namespace hmi
