// tags.h -- the daemon link: CONTRACT section 2 over UDP, a tag map and
// the command API. The C port of gui/hmi_loader/tagengine.py's TagEngine
// core (and of native/hmi-gui/src/tagengine.cpp), minus the QML shim:
// consumers are callbacks, not properties.
//
// Behaviour of tags.c, matching
// the Python/C++ engines and tests/native (which are the acceptance tests):
//   * bind UDP 127.0.0.1:rx_port; 0 = any free port; bind failure is logged
//     "Could not bind telemetry port N (...); UI will run offline" and the
//     engine stays offline.
//   * {"cmd":"subscribe","ttl":5} at start and every 2000 ms (no id).
//   * inbound {"t":"tags","tags":{...}}: online=true, watchdog restart
//     (2500 ms -> online=false), each tag whose value differs from the map is
//     stored and reported through the change callback (both spellings are
//     the same tag here: "ai.pot"; the '_' alias is a QML artefact).
//   * inbound {"t":"ack","id","ok","err","tags"}: ack callback.
//   * datagrams > 8192 bytes, non-object JSON, unknown "t", tags not an
//     object: dropped and counted in rx_errors.
//   * commands carry ids "gui-1", "gui-2", ... (subscribe and ping do not
//     consume the counter): set {"id","cmd":"set","tag","value"}, pulse
//     {"id","cmd":"pulse","tag","ms"}, uart_tx {"id","cmd":"uart_tx","data"},
//     ping {"cmd":"ping","id":"qml-ping"}, list {"cmd":"list","id"},
//     unsubscribe {"cmd":"unsubscribe","id"} (sent once on shutdown).
//   * outbound JSON is compact; key order is not significant.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "value.h"

typedef struct hmi_tags hmi_tags_t;

typedef struct {
    uint16_t rx_port;         // 0 = any
    const char *daemon_host;  // "127.0.0.1"
    uint16_t daemon_port;     // 5000
} hmi_tags_options_t;

// tag changed (new value stored); online changed; ack arrived.
typedef void (*hmi_tag_change_cb)(const char *tag, const hmi_value_t *value, void *user);
typedef void (*hmi_online_cb)(bool online, void *user);
typedef void (*hmi_ack_cb)(const char *id, bool ok, const char *err, const hmi_value_t *tags, void *user);

hmi_tags_t *hmi_tags_create(const hmi_tags_options_t *opt);
void hmi_tags_destroy(hmi_tags_t *t);          // sends unsubscribe, closes the socket
void hmi_tags_set_callbacks(hmi_tags_t *t, hmi_tag_change_cb on_tag, hmi_online_cb on_online,
                            hmi_ack_cb on_ack, void *user);

// Call from the main loop every few ms: drains the socket, runs the
// subscribe and watchdog timers (uses lv_tick_get / monotonic time).
void hmi_tags_poll(hmi_tags_t *t);

// Current state.
const hmi_value_t *hmi_tags_value(const hmi_tags_t *t, const char *tag);   // NULL = never seen
// The last `count` numeric values received for `tag` (oldest first, at most
// 200 kept per tag; non-numeric frames are skipped) as an HMI_V_LIST the
// caller frees. Feeds series bindings (ShTrendChart).
hmi_value_t hmi_tags_history(const hmi_tags_t *t, const char *tag, size_t count);
bool hmi_tags_online(const hmi_tags_t *t);
uint32_t hmi_tags_rx_errors(const hmi_tags_t *t);
uint16_t hmi_tags_rx_port(const hmi_tags_t *t);    // the bound port (0 when unbound)

// Commands; each returns the id it sent ("gui-N"), or "" when not sent.
const char *hmi_tags_write(hmi_tags_t *t, const char *tag, const hmi_value_t *value);
const char *hmi_tags_pulse(hmi_tags_t *t, const char *tag, int ms);
const char *hmi_tags_uart_tx(hmi_tags_t *t, const char *data);
const char *hmi_tags_list(hmi_tags_t *t);
void hmi_tags_ping(hmi_tags_t *t);
