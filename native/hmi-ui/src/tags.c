// tags.c -- the daemon link (see tags.h). A port of gui/hmi_loader/tagengine.py's
// TagEngine core: one non-blocking UDP socket, a tag map with change
// detection, a 2 s subscribe timer, a 2.5 s watchdog, "gui-N" command ids.
#include "tags.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "compat.h"
#include "log.h"
#include "lvgl/lvgl.h"

#include <time.h>

#define MAX_DATAGRAM 8192
#define SUBSCRIBE_MS 2000
#define WATCHDOG_MS 2500
#define HISTORY_LEN 200

typedef struct {
    char *name;
    hmi_value_t value;
    hmi_quality_t q;
    double history[HISTORY_LEN];
    int64_t hist_ts[HISTORY_LEN];    // wall-clock epoch ms when each sample arrived
    size_t hist_count;   // values stored (<= HISTORY_LEN)
    size_t hist_next;    // ring write index
} tag_entry_t;

struct hmi_tags {
    hmi_tags_options_t opt;
    hmi_udp_t fd;
    uint16_t bound_port;
    bool online;
    uint32_t last_frame_ms;
    uint32_t last_subscribe_ms;
    bool subscribed_once;
    uint32_t rx_errors;
    unsigned next_id;
    char last_id[32];
    tag_entry_t *tags;
    size_t ntags, cap;
    hmi_tag_change_cb on_tag;
    hmi_online_cb on_online;
    hmi_ack_cb on_ack;
    hmi_history_cb on_history;
    void *history_user;          // its own: the other callbacks share `user`
    void *user;
    int64_t last_wall_ms;
};

static uint32_t now_ms(void) { return lv_tick_get(); }

// Wall-clock epoch ms. A frame's receive time is the wall clock, not LVGL's
// monotonic tick, so a backfill sample can be aged against it.
static int64_t wall_ms(void) { return hmi_wall_ms(); }

static hmi_quality_t parse_qual(const char *s)
{
    if (s && strcmp(s, "bad") == 0) return HMI_Q_BAD;
    if (s && strcmp(s, "stale") == 0) return HMI_Q_STALE;
    return HMI_Q_BAD;   // any other word is not a real quality, so the tag is bad
}

static tag_entry_t *find_tag(hmi_tags_t *t, const char *name)
{
    for (size_t i = 0; i < t->ntags; ++i)
        if (strcmp(t->tags[i].name, name) == 0) return &t->tags[i];
    return NULL;
}

static tag_entry_t *add_tag(hmi_tags_t *t, const char *name)
{
    if (t->ntags == t->cap) {
        t->cap = t->cap ? t->cap * 2 : 64;
        t->tags = realloc(t->tags, t->cap * sizeof(tag_entry_t));
    }
    tag_entry_t *e = &t->tags[t->ntags++];
    memset(e, 0, sizeof *e);
    e->name = strdup(name);
    e->value = hmi_value_null();
    return e;
}

// A frame carrying "q" marks its listed tags (bad/stale, unknown word -> bad)
// and resets every other tag to GOOD; a frame without "q" leaves quality as is.
static void apply_quality(hmi_tags_t *t, const cJSON *q)
{
    if (!q) return;
    for (size_t i = 0; i < t->ntags; ++i) t->tags[i].q = HMI_Q_GOOD;
    const cJSON *item;
    cJSON_ArrayForEach(item, q) {
        tag_entry_t *e = find_tag(t, item->string);
        if (e) e->q = parse_qual(cJSON_GetStringValue(item));
    }
}

// -- sending -----------------------------------------------------------------------

static bool send_json(hmi_tags_t *t, cJSON *obj)
{
    char *text = cJSON_PrintUnformatted(obj);
    cJSON_Delete(obj);
    if (!text) return false;
    bool ok = t->fd != HMI_UDP_INVALID &&
              hmi_udp_send(t->fd, t->opt.daemon_host, t->opt.daemon_port, text, strlen(text)) >= 0;
    if (!ok) hmi_log(HMI_LOG_DEBUG, "send failed: %s", strerror(errno));
    else hmi_log(HMI_LOG_DEBUG, "tx %s", text);
    free(text);
    return ok;
}

static const char *next_id(hmi_tags_t *t)
{
    snprintf(t->last_id, sizeof t->last_id, "gui-%u", t->next_id++);
    return t->last_id;
}

static void send_subscribe(hmi_tags_t *t)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "cmd", "subscribe");
    cJSON_AddNumberToObject(o, "ttl", 5);
    send_json(t, o);
    t->last_subscribe_ms = now_ms();
    t->subscribed_once = true;
}

// -- receiving ---------------------------------------------------------------------

static void set_online(hmi_tags_t *t, bool online)
{
    if (t->online == online) return;
    t->online = online;
    if (t->on_online) t->on_online(online, t->user);
}

static void handle_telemetry(hmi_tags_t *t, const cJSON *obj)
{
    const cJSON *tags = cJSON_GetObjectItemCaseSensitive(obj, "tags");
    if (!cJSON_IsObject(tags)) { ++t->rx_errors; return; }
    t->last_frame_ms = now_ms();
    t->last_wall_ms = wall_ms();
    set_online(t, true);
    const cJSON *item;
    cJSON_ArrayForEach(item, tags) {
        hmi_value_t v = hmi_value_from_json(item);
        tag_entry_t *e = find_tag(t, item->string);
        bool changed;
        if (!e) { e = add_tag(t, item->string); changed = true; }
        else changed = !hmi_value_equal(&e->value, &v);
        if (v.kind == HMI_V_NUM) {
            e->history[e->hist_next] = v.n;
            e->hist_ts[e->hist_next] = t->last_wall_ms;
            e->hist_next = (e->hist_next + 1) % HISTORY_LEN;
            if (e->hist_count < HISTORY_LEN) ++e->hist_count;
        }
        if (changed) {
            hmi_value_free(&e->value);
            e->value = v;
            if (t->on_tag) t->on_tag(e->name, &e->value, t->user);
        } else {
            hmi_value_free(&v);
        }
    }
    // Apply quality after the tags exist so a frame listing them is honored.
    apply_quality(t, cJSON_GetObjectItemCaseSensitive(obj, "q"));
}

// Merge a history ack's samples in front of the tag's ring. A sample is taken
// only if its timestamp precedes the newest frame the tag actually received;
// the ring never grows past HISTORY_LEN (oldest dropped first). The
// prepended samples' receive times become their own epoch so a later backfill
// still ages them.
static size_t merge_history(hmi_tags_t *t, tag_entry_t *e, const cJSON *samples)
{
    (void)t;
    if (!e || !cJSON_IsArray(samples)) return 0;
    // Only samples older than the oldest one held go in front (13.4).
    int64_t oldest_recv = e->hist_count
        ? e->hist_ts[(e->hist_next + HISTORY_LEN - e->hist_count) % HISTORY_LEN] : INT64_MAX;
    int n = cJSON_GetArraySize(samples);

    // Oldest-first list: the accepted backfill samples, then the ring's values.
    double  merge_v[2 * HISTORY_LEN];
    int64_t merge_ts[2 * HISTORY_LEN];
    size_t  m = 0;
    for (int i = 0; i < n && m < 2 * HISTORY_LEN; ++i) {
        const cJSON *s = cJSON_GetArrayItem(samples, i);
        if (!cJSON_IsArray(s) || cJSON_GetArraySize(s) < 2) continue;
        int64_t ts = (int64_t)(cJSON_GetArrayItem(s, 0)->valuedouble + 0.5);
        if (ts >= oldest_recv) continue;
        if (m && (int64_t)(merge_ts[m - 1]) >= ts) continue;   // keep strictly oldest-first
        merge_v[m] = cJSON_GetArrayItem(s, 1)->valuedouble;
        merge_ts[m] = ts;
        ++m;
    }
    size_t accepted = m;
    if (accepted == 0) return 0;
    if (e->hist_count > 0) {
        size_t oldest = (e->hist_next + HISTORY_LEN - e->hist_count) % HISTORY_LEN;
        for (size_t i = 0; i < e->hist_count && m < 2 * HISTORY_LEN; ++i) {
            size_t slot = (oldest + i) % HISTORY_LEN;
            merge_v[m] = e->history[slot];
            merge_ts[m] = e->hist_ts[slot];
            ++m;
        }
    }
    // Keep the newest HISTORY_LEN of the oldest-first list (oldest dropped first).
    size_t keep = m < HISTORY_LEN ? m : HISTORY_LEN;
    size_t drop = m - keep;

    // Reading starts at index 0 when hist_next == keep, so write from 0.
    for (size_t i = 0; i < keep; ++i) {
        e->history[i] = merge_v[drop + i];
        e->hist_ts[i] = merge_ts[drop + i];
    }
    e->hist_count = keep;
    e->hist_next = keep % HISTORY_LEN;
    return accepted;
}

// Match a history ack by id: merge its older samples into the tag's ring, then
// fire the history callback. A sample is ignored unless it is older than the
// newest frame the tag received; the ring never grows past HISTORY_LEN.
static void handle_history_ack(hmi_tags_t *t, const cJSON *hist)
{
    if (!hist || !cJSON_IsObject(hist)) return;
    const cJSON *tag = cJSON_GetObjectItemCaseSensitive(hist, "tag");
    if (!cJSON_IsString(tag)) return;
    tag_entry_t *e = find_tag(t, cJSON_GetStringValue(tag));
    if (!e) return;
    if (merge_history(t, e, cJSON_GetObjectItemCaseSensitive(hist, "samples")) && t->on_history)
        t->on_history(e->name, t->history_user);
}

static void handle_ack(hmi_tags_t *t, const cJSON *obj)
{
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(obj, "id");
    const cJSON *ok = cJSON_GetObjectItemCaseSensitive(obj, "ok");
    const cJSON *err = cJSON_GetObjectItemCaseSensitive(obj, "err");
    hmi_value_t tags = hmi_value_from_json(cJSON_GetObjectItemCaseSensitive(obj, "tags"));
    const char *id_str = cJSON_IsString(id) ? cJSON_GetStringValue(id) : "";
    if (t->on_ack)
        t->on_ack(id_str, cJSON_IsTrue(ok), cJSON_IsString(err) ? cJSON_GetStringValue(err) : "", &tags, t->user);
    hmi_value_free(&tags);
    if (cJSON_IsTrue(ok)) handle_history_ack(t, cJSON_GetObjectItemCaseSensitive(obj, "history"));
}

static void drain(hmi_tags_t *t)
{
    static char buf[MAX_DATAGRAM + 1024];
    // Bounded so a flooding sender cannot starve the LVGL loop: whatever is
    // left waits for the next poll (a few ms away).
    for (int i = 0; i < 64; ++i) {
        int n = hmi_udp_recv(t->fd, buf, sizeof buf);
        if (n <= 0) {
            if (n < 0) hmi_log(HMI_LOG_DEBUG, "recv failed: %s", strerror(errno));
            return;
        }
        if (n > MAX_DATAGRAM) { ++t->rx_errors; continue; }
        buf[n] = '\0';
        cJSON *obj = cJSON_ParseWithLength(buf, (size_t)n);
        if (!obj || !cJSON_IsObject(obj)) { ++t->rx_errors; cJSON_Delete(obj); continue; }
        const cJSON *type = cJSON_GetObjectItemCaseSensitive(obj, "t");
        const char *tt = cJSON_IsString(type) ? cJSON_GetStringValue(type) : "";
        if (strcmp(tt, "tags") == 0) handle_telemetry(t, obj);
        else if (strcmp(tt, "ack") == 0) handle_ack(t, obj);
        else ++t->rx_errors;
        cJSON_Delete(obj);
    }
}

// -- API ---------------------------------------------------------------------------

hmi_tags_t *hmi_tags_create(const hmi_tags_options_t *opt)
{
    hmi_tags_t *t = calloc(1, sizeof *t);
    t->opt = *opt;
    t->next_id = 1;
    t->fd = hmi_udp_open(opt->rx_port);
    if (t->fd != HMI_UDP_INVALID) {
        t->bound_port = hmi_udp_bound_port(t->fd);
        hmi_log(HMI_LOG_DEBUG, "telemetry socket bound to 127.0.0.1:%u", t->bound_port);
        send_subscribe(t);
    } else {
        hmi_log(HMI_LOG_ERROR, "Could not bind telemetry port %u (%s); UI will run offline",
                opt->rx_port, strerror(errno));
    }
    return t;
}

void hmi_tags_destroy(hmi_tags_t *t)
{
    if (!t) return;
    if (t->fd != HMI_UDP_INVALID) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "cmd", "unsubscribe");
        cJSON_AddStringToObject(o, "id", next_id(t));
        send_json(t, o);
        hmi_udp_close(t->fd);
    }
    for (size_t i = 0; i < t->ntags; ++i) { free(t->tags[i].name); hmi_value_free(&t->tags[i].value); }
    free(t->tags);
    free(t);
}

void hmi_tags_set_callbacks(hmi_tags_t *t, hmi_tag_change_cb on_tag, hmi_online_cb on_online,
                            hmi_ack_cb on_ack, void *user)
{
    t->on_tag = on_tag; t->on_online = on_online; t->on_ack = on_ack; t->user = user;
}

void hmi_tags_poll(hmi_tags_t *t)
{
    if (t->fd == HMI_UDP_INVALID) return;
    drain(t);
    uint32_t now = now_ms();
    if (!t->subscribed_once || now - t->last_subscribe_ms >= SUBSCRIBE_MS)
        send_subscribe(t);
    if (t->online && now - t->last_frame_ms >= WATCHDOG_MS)
        set_online(t, false);
}

const hmi_value_t *hmi_tags_value(const hmi_tags_t *t, const char *tag)
{
    tag_entry_t *e = find_tag((hmi_tags_t *)t, tag);
    return e ? &e->value : NULL;
}

hmi_value_t hmi_tags_history(const hmi_tags_t *t, const char *tag, size_t count)
{
    hmi_value_t out = hmi_value_null();
    out.kind = HMI_V_LIST;
    tag_entry_t *e = find_tag((hmi_tags_t *)t, tag);
    if (!e || e->hist_count == 0 || count == 0) return out;
    if (count > e->hist_count) count = e->hist_count;
    out.items = calloc(count, sizeof(hmi_value_t));
    out.count = count;
    // oldest of the last `count` values first
    size_t start = (e->hist_next + HISTORY_LEN - count) % HISTORY_LEN;
    for (size_t i = 0; i < count; ++i)
        out.items[i] = hmi_value_num(e->history[(start + i) % HISTORY_LEN]);
    return out;
}

bool hmi_tags_online(const hmi_tags_t *t) { return t->online; }
uint32_t hmi_tags_rx_errors(const hmi_tags_t *t) { return t->rx_errors; }
uint16_t hmi_tags_rx_port(const hmi_tags_t *t) { return t->bound_port; }

static cJSON *command(hmi_tags_t *t, const char *cmd)
{
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "id", next_id(t));
    cJSON_AddStringToObject(o, "cmd", cmd);
    return o;
}

const char *hmi_tags_write(hmi_tags_t *t, const char *tag, const hmi_value_t *value)
{
    if (t->fd == HMI_UDP_INVALID) return "";
    cJSON *o = command(t, "set");
    cJSON_AddStringToObject(o, "tag", tag);
    cJSON_AddItemToObject(o, "value", hmi_value_to_json(value));
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_pulse(hmi_tags_t *t, const char *tag, int ms)
{
    if (t->fd == HMI_UDP_INVALID) return "";
    cJSON *o = command(t, "pulse");
    cJSON_AddStringToObject(o, "tag", tag);
    cJSON_AddNumberToObject(o, "ms", ms);
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_uart_tx(hmi_tags_t *t, const char *data)
{
    if (t->fd == HMI_UDP_INVALID) return "";
    cJSON *o = command(t, "uart_tx");
    cJSON_AddStringToObject(o, "data", data);
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_list(hmi_tags_t *t)
{
    if (t->fd == HMI_UDP_INVALID) return "";
    return send_json(t, command(t, "list")) ? t->last_id : "";
}

void hmi_tags_ping(hmi_tags_t *t)
{
    if (t->fd == HMI_UDP_INVALID) return;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "cmd", "ping");
    cJSON_AddStringToObject(o, "id", "qml-ping");
    send_json(t, o);
}

// ---- wave 1 additions (CONTRACT 13.4) ---------------------------------------

// A tag missing from "q" is good again; one never seen was never marked bad, so
// it reports GOOD (its value was never received either).
hmi_quality_t hmi_tags_quality(const hmi_tags_t *t, const char *tag)
{
    tag_entry_t *e = find_tag((hmi_tags_t *)t, tag);
    return e ? e->q : HMI_Q_GOOD;
}

// Registers the backfill callback, fired with the tag name after a history ack
// whose samples were merged into the tag's ring.
void hmi_tags_set_history_callback(hmi_tags_t *t, hmi_history_cb cb, void *user)
{
    t->on_history = cb;
    t->history_user = user;
}

// seconds 1..604800 (default 3600), points 1..200 (default 200); return the id
// sent, or "" when the socket is closed. The matching ack backfills the ring.
const char *hmi_tags_request_history(hmi_tags_t *t, const char *tag, int seconds, int points)
{
    if (t->fd == HMI_UDP_INVALID) return "";
    if (seconds < 1) seconds = 1; else if (seconds > 604800) seconds = 604800;
    if (points < 1) points = 1; else if (points > 200) points = 200;
    cJSON *o = command(t, "history");
    cJSON_AddStringToObject(o, "tag", tag);
    cJSON_AddNumberToObject(o, "seconds", seconds);
    cJSON_AddNumberToObject(o, "points", points);
    return send_json(t, o) ? t->last_id : "";
}
