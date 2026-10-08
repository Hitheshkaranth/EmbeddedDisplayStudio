/*
 * proto.h -- the CONTRACT section 2 wire protocol, without sockets: parse a
 * datagram into a command, build acks and telemetry frames. daemon.c owns
 * the sockets and calls these; tests/test_proto.c drives them directly.
 *
 * FROZEN.
 */
#ifndef HWD_PROTO_H
#define HWD_PROTO_H

#include "hwd.h"
#include "tagstore.h"
#include "cJSON.h"

typedef enum {
    HWD_CMD_NONE = 0,
    HWD_CMD_SET, HWD_CMD_PULSE, HWD_CMD_UART_TX, HWD_CMD_SUBSCRIBE,
    HWD_CMD_UNSUBSCRIBE, HWD_CMD_LIST, HWD_CMD_PING, HWD_CMD_HISTORY,
    HWD_CMD_DISCOVER,          /* only on the discovery socket */
} hwd_cmd_kind;

typedef struct {
    hwd_cmd_kind kind;
    char id[HWD_MAX_ID + 1];   /* "" when the command carried none */
    bool has_id;
    char tag[HWD_MAX_TAG + 1];
    hwd_value value;           /* set: the value as sent (bool/int/float) */
    int ms;                    /* pulse */
    char *data;                /* uart_tx (owned) */
    double ttl;                /* subscribe; <= 0 = default */
    double seconds;            /* history, default 3600 */
    double points;             /* history, default 200 */
} hwd_cmd;

/* Parse one datagram. Returns HWD_OK and fills cmd, or the error to answer
 * (bad_json, not_an_object, too_large, unknown_cmd, bad_value). Even on an
 * error, cmd->id/has_id carry the id when one could be recovered (the
 * Python recovers it best-effort from malformed JSON too, so the sender
 * still gets its nack). */
hwd_err hwd_proto_parse(const char *data, size_t len, hwd_cmd *cmd);
void hwd_cmd_free(hwd_cmd *cmd);

/* {"t":"ack","id":..,"ok":true} / {"t":"ack","id":..,"ok":false,"err":".."}.
 * Returns a malloc'd compact JSON string. */
char *hwd_proto_ack(const char *id, hwd_err err);
/* The `list` ack: {"t":"ack","id":..,"ok":true,"tags":[sorted names]}. */
char *hwd_proto_list_ack(const char *id, hwd_tagstore *store);
/* The `ping` ack carries uptime like the Python: {"t":"ack","id":..,"ok":true}. */
char *hwd_proto_ping_ack(const char *id);
/* The `history` ack: samples is a cJSON array of [epoch_ms, number]
 * (ownership taken). Falls back to an empty sample list when the reply
 * would exceed HWD_MAX_DGRAM. */
char *hwd_proto_history_ack(const char *id, const char *tag, cJSON *samples);

/* One telemetry frame (CONTRACT 2.4 + 13.4 "q"):
 * {"t":"tags","seq":N,"ts":wall,"src":"hmi-hwd","tags":{...},"q":{...}}
 * "q" only when some tag is not good. Returns malloc'd compact JSON. */
char *hwd_proto_frame(hwd_tagstore *store, uint32_t seq, double ts);

#endif
