// native/hmi-gui/src/tagengine.h
// Layer: 2 (GUI Loader)
// Purpose: TagEngine -- CONTRACT section 2 (wire protocol and naming).
// Port of class TagEngine in gui/hmi_loader/tagengine.py, which is the
// specification for every method below. It is a pure UDP client: no hardware
// access of any kind (CONTRACT section 1).
//
// QML sees this object as `BusImpl`; `Bus` is the QML shim in busshim.h that
// forwards to it; `Tags` is tagMap(). Slot and property names are frozen
// because BUS_QML and existing apps call them by name.
//
// Wire protocol summary (CONTRACT 2):
//   in  {"t":"tags","seq":N,"ts":T,"src":"hmi-hwd","tags":{"ai.pot":2.1,...}}
//   in  {"t":"ack","id":"gui-3","ok":true,"err":"","tags":[...]}   (tags: list only)
//   out {"cmd":"subscribe","ttl":5}                                   every 2 s
//   out {"id":"gui-N","cmd":"set","tag":"do.relay1","value":true}
//   out {"id":"gui-N","cmd":"pulse","tag":"do.relay1","ms":250}
//   out {"id":"gui-N","cmd":"uart_tx","data":"..."}
//   out {"cmd":"ping","id":"qml-ping"}
//   out {"cmd":"list","id":"gui-N"}   /   {"cmd":"unsubscribe","id":"gui-N"}
// Correlation ids are "gui-<n>" from a counter starting at 1. Datagrams over
// kMaxDatagramBytes are drained and counted as rx errors, never parsed.
//
// Owner: W1 (implementation in tagengine.cpp). Public / slots / signals are
// frozen; W1 may extend the private section.
#pragma once

#include "alarmengine.h"
#include "history.h"
#include "tagmap.h"

#include <QHash>
#include <QHostAddress>
#include <QObject>
#include <QString>
#include <QStringList>
#include <QTimer>
#include <QUdpSocket>
#include <QVariant>
#include <QVariantList>
#include <functional>

namespace hmi {

class TagEngine : public QObject {
    Q_OBJECT
    Q_PROPERTY(QQmlPropertyMap *tags READ tagMap CONSTANT)
    Q_PROPERTY(bool online READ online NOTIFY onlineChanged)
    Q_PROPERTY(int rxErrors READ rxErrors NOTIFY rxErrorsChanged)
    Q_PROPERTY(int historyVersion READ historyVersion NOTIFY historyVersionChanged)
    Q_PROPERTY(QVariantList activeAlarms READ activeAlarms NOTIFY activeAlarmsChanged)
    Q_PROPERTY(int alarmCount READ alarmCount NOTIFY activeAlarmsChanged)

public:
    static constexpr int kMaxDatagramBytes = 8192;
    static constexpr int kWatchdogIntervalMs = 2500;
    static constexpr int kSubscribeIntervalMs = 2000;
    static constexpr int kSubscribeTtlS = 5;
    static constexpr int kBlockingReplyTimeoutMs = 2000;   // list_tags / unsubscribe

    struct Options {
        quint16 rxPort = 5001;          // 0 = ephemeral (tests)
        bool allowAnyPort = false;      // fall back to ephemeral when rxPort is taken
        QString daemonHost = "127.0.0.1";
        quint16 daemonPort = 5000;
        int historyDepth = 600;
    };

    // Seeds every expected tag (dotted and underscored) as a null QVariant,
    // seeds "online" = false, tracks expected + alarm tags in the history,
    // binds the socket, starts the watchdog and subscribe timers and sends
    // the first subscribe. A failed bind is logged and leaves rxPort() == 0.
    TagEngine(const QStringList &expectedTags, const QVariantList &alarmDefs,
              const Options &options, QObject *parent = nullptr);

    TagMap *tagMap() const;
    quint16 rxPort() const;          // port actually bound; 0 when offline for good
    bool online() const;
    int rxErrors() const;
    int historyVersion() const;
    QVariantList activeAlarms() const;
    int alarmCount() const;

    History &historyBuffer();
    AlarmEngine &alarmEngine();

    // "do_relay1" -> "do.relay1" via the alias table; dotted names and unknown
    // aliases pass through unchanged (the daemon then answers unknown_tag).
    QString toWireName(const QString &name) const;

public slots:
    void write(const QString &tag, const QVariant &value);
    void pulse(const QString &tag, int ms);
    void uart_tx(const QString &data);
    void ping();
    // Defensive read: dotted or underscored; null/unknown -> fallback.
    QVariant value(const QString &name, const QVariant &fallback = QVariant());
    // Sends {"cmd":"list"} and spins a local event loop for the ack (2 s max).
    // Emits listReceived() with the result (empty on timeout) and returns it.
    QVariantList list_tags();
    // Sends {"cmd":"unsubscribe"} and waits for the ack (2 s max); emits
    // unsubscribed() only on an ok ack.
    void unsubscribe();
    // Last <= n samples for a tracked tag, oldest first (History::samples).
    QVariantList history(const QString &tag, int n = 100);
    void acknowledge(const QString &tag);

signals:
    void ackReceived(const QString &id, bool ok, const QString &err);
    void onlineChanged();
    void rxErrorsChanged();
    void listReceived(const QVariantList &tags);
    void unsubscribed();
    void historyVersionChanged();
    void activeAlarmsChanged();

private slots:
    void readPendingDatagrams();
    void onWatchdogTimeout();
    void subscribeToDaemon();
    void onQmlWrite(const QString &key, const QVariant &value);

private:
    using AckHandler = std::function<void(const QString &id, bool ok, const QString &err,
                                          const QVariantList &tags)>;

    void setOnline(bool state);
    void countRxError();
    void handleTelemetry(const QVariantMap &msg);
    void handleAck(const QVariantMap &msg);
    QString nextId();
    void sendCommand(const QVariantMap &cmd);

    TagMap *m_map;
    History m_history;
    AlarmEngine *m_alarms;
    QUdpSocket *m_socket;
    QTimer *m_watchdog;
    QTimer *m_subTimer;
    QHostAddress m_daemonAddr;
    quint16 m_daemonPort;
    quint16 m_rxPort = 0;
    bool m_online = false;
    int m_rxErrors = 0;
    int m_historyVersion = 0;
    qint64 m_cmdSeq = 0;
    QHash<QString, QString> m_aliasToTag;
    QHash<QString, AckHandler> m_pendingAcks;
};

} // namespace hmi
