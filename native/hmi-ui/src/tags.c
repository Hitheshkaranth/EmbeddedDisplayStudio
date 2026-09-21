// tags.c -- the daemon link (see tags.h). A port of gui/hmi_loader/tagengine.py's
// TagEngine core: one non-blocking UDP socket, a tag map with change
// detection, a 2 s subscribe timer, a 2.5 s watchdog, "gui-N" command ids.
#include "tags.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "cJSON.h"
#include "log.h"
#include "lvgl/lvgl.h"

#define MAX_DATAGRAM 8192
#define SUBSCRIBE_MS 2000
#define WATCHDOG_MS 2500
#define HISTORY_LEN 200

typedef struct {
    char *name;
    hmi_value_t value;
    double history[HISTORY_LEN];
    size_t hist_count;   // values stored (<= HISTORY_LEN)
    size_t hist_next;    // ring write index
} tag_entry_t;

struct hmi_tags {
    hmi_tags_options_t opt;
    int fd;
    uint16_t bound_port;
    struct sockaddr_in daemon;
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
    void *user;
};

static uint32_t now_ms(void) { return lv_tick_get(); }

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

// -- sending -----------------------------------------------------------------------

static bool send_json(hmi_tags_t *t, cJSON *obj)
{
    char *text = cJSON_PrintUnformatted(obj);
    cJSON_Delete(obj);
    if (!text) return false;
    bool ok = t->fd >= 0 &&
              sendto(t->fd, text, strlen(text), 0, (struct sockaddr *)&t->daemon, sizeof t->daemon) >= 0;
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
}

static void handle_ack(hmi_tags_t *t, const cJSON *obj)
{
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(obj, "id");
    const cJSON *ok = cJSON_GetObjectItemCaseSensitive(obj, "ok");
    const cJSON *err = cJSON_GetObjectItemCaseSensitive(obj, "err");
    hmi_value_t tags = hmi_value_from_json(cJSON_GetObjectItemCaseSensitive(obj, "tags"));
    if (t->on_ack)
        t->on_ack(cJSON_IsString(id) ? cJSON_GetStringValue(id) : "", cJSON_IsTrue(ok),
                  cJSON_IsString(err) ? cJSON_GetStringValue(err) : "", &tags, t->user);
    hmi_value_free(&tags);
}

static void drain(hmi_tags_t *t)
{
    static char buf[MAX_DATAGRAM + 1024];
    for (;;) {
        ssize_t n = recvfrom(t->fd, buf, sizeof buf, 0, NULL, NULL);
        if (n < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK)
                hmi_log(HMI_LOG_DEBUG, "recv failed: %s", strerror(errno));
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
    t->fd = -1;
    t->next_id = 1;
    t->daemon.sin_family = AF_INET;
    t->daemon.sin_port = htons(opt->daemon_port);
    if (inet_pton(AF_INET, opt->daemon_host ? opt->daemon_host : "127.0.0.1", &t->daemon.sin_addr) != 1)
        inet_pton(AF_INET, "127.0.0.1", &t->daemon.sin_addr);

    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd >= 0) {
        struct sockaddr_in addr;
        memset(&addr, 0, sizeof addr);
        addr.sin_family = AF_INET;
        addr.sin_port = htons(opt->rx_port);
        inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
        if (bind(fd, (struct sockaddr *)&addr, sizeof addr) == 0) {
            socklen_t len = sizeof addr;
            getsockname(fd, (struct sockaddr *)&addr, &len);
            t->bound_port = ntohs(addr.sin_port);
            fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
            t->fd = fd;
            hmi_log(HMI_LOG_DEBUG, "telemetry socket bound to 127.0.0.1:%u", t->bound_port);
        } else {
            hmi_log(HMI_LOG_ERROR, "Could not bind telemetry port %u (%s); UI will run offline",
                    opt->rx_port, strerror(errno));
            close(fd);
        }
    } else {
        hmi_log(HMI_LOG_ERROR, "Could not bind telemetry port %u (%s); UI will run offline",
                opt->rx_port, strerror(errno));
    }
    if (t->fd >= 0) send_subscribe(t);
    return t;
}

void hmi_tags_destroy(hmi_tags_t *t)
{
    if (!t) return;
    if (t->fd >= 0) {
        cJSON *o = cJSON_CreateObject();
        cJSON_AddStringToObject(o, "cmd", "unsubscribe");
        cJSON_AddStringToObject(o, "id", next_id(t));
        send_json(t, o);
        close(t->fd);
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
    if (t->fd < 0) return;
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
    if (t->fd < 0) return "";
    cJSON *o = command(t, "set");
    cJSON_AddStringToObject(o, "tag", tag);
    cJSON_AddItemToObject(o, "value", hmi_value_to_json(value));
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_pulse(hmi_tags_t *t, const char *tag, int ms)
{
    if (t->fd < 0) return "";
    cJSON *o = command(t, "pulse");
    cJSON_AddStringToObject(o, "tag", tag);
    cJSON_AddNumberToObject(o, "ms", ms);
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_uart_tx(hmi_tags_t *t, const char *data)
{
    if (t->fd < 0) return "";
    cJSON *o = command(t, "uart_tx");
    cJSON_AddStringToObject(o, "data", data);
    return send_json(t, o) ? t->last_id : "";
}

const char *hmi_tags_list(hmi_tags_t *t)
{
    if (t->fd < 0) return "";
    return send_json(t, command(t, "list")) ? t->last_id : "";
}

void hmi_tags_ping(hmi_tags_t *t)
{
    if (t->fd < 0) return;
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "cmd", "ping");
    cJSON_AddStringToObject(o, "id", "qml-ping");
    send_json(t, o);
}
