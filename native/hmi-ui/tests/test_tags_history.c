// tests/test_tags_history.c -- CONTRACT 13.4 in the tag engine: quality from
// "q", the history command and backfill into the ring. Wave 1 gate for W4
// (FROZEN). Plays daemon on a loopback UDP socket.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdlib.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "cJSON.h"
#include "check.h"
#include "compat.h"
#include "lvgl/lvgl.h"
#include "tags.h"

static int g_fd;
static struct sockaddr_in g_client;
static bool g_have_client;
static hmi_tags_t *g_t;
static int g_history_calls;
static char g_history_tag[64];

static uint32_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

static int64_t wall_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void on_history(const char *tag, void *user)
{
    (void)user;
    ++g_history_calls;
    snprintf(g_history_tag, sizeof g_history_tag, "%s", tag);
}

static cJSON *next_cmd(int timeout_ms)
{
    uint32_t end = mono_ms() + (uint32_t)timeout_ms;
    while ((int32_t)(end - mono_ms()) > 0) {
        hmi_tags_poll(g_t);
        struct pollfd p = {g_fd, POLLIN, 0};
        if (poll(&p, 1, 5) > 0) {
            char buf[9000];
            socklen_t len = sizeof g_client;
            ssize_t n = recvfrom(g_fd, buf, sizeof buf - 1, 0, (struct sockaddr *)&g_client, &len);
            if (n <= 0) continue;
            buf[n] = 0;
            g_have_client = true;
            cJSON *j = cJSON_Parse(buf);
            const char *cmd = cJSON_GetStringValue(cJSON_GetObjectItem(j, "cmd"));
            if (cmd && strcmp(cmd, "subscribe") && strcmp(cmd, "ping") && strcmp(cmd, "unsubscribe")) return j;
            cJSON_Delete(j);
        }
    }
    return NULL;
}

static void send_json(const char *json)
{
    while (!g_have_client) cJSON_Delete(next_cmd(50));
    sendto(g_fd, json, strlen(json), 0, (struct sockaddr *)&g_client, sizeof g_client);
    uint32_t end = mono_ms() + 40;
    while ((int32_t)(end - mono_ms()) > 0) { hmi_tags_poll(g_t); hmi_sleep_ms(2); }
}

static void frame(const char *tags, const char *q)
{
    char buf[8192];
    if (q) snprintf(buf, sizeof buf, "{\"t\":\"tags\",\"seq\":1,\"ts\":0,\"src\":\"t\",\"tags\":%s,\"q\":%s}", tags, q);
    else snprintf(buf, sizeof buf, "{\"t\":\"tags\",\"seq\":1,\"ts\":0,\"src\":\"t\",\"tags\":%s}", tags);
    send_json(buf);
}

static void test_quality(void)
{
    frame("{\"a.b\":1,\"c.d\":null,\"e.f\":5,\"g.h\":2}", "{\"c.d\":\"bad\",\"e.f\":\"stale\",\"g.h\":\"weird\"}");
    CHECK(hmi_tags_quality(g_t, "a.b") == HMI_Q_GOOD);
    CHECK(hmi_tags_quality(g_t, "c.d") == HMI_Q_BAD);
    CHECK(hmi_tags_quality(g_t, "e.f") == HMI_Q_STALE);
    CHECK(hmi_tags_quality(g_t, "g.h") == HMI_Q_BAD);        // unknown word
    CHECK(hmi_tags_quality(g_t, "never.seen") == HMI_Q_GOOD);
    frame("{\"a.b\":2}", NULL);                              // no "q": nothing changes
    CHECK(hmi_tags_quality(g_t, "c.d") == HMI_Q_BAD);
    frame("{\"a.b\":3}", "{\"e.f\":\"bad\"}");               // listed or reset to good
    CHECK(hmi_tags_quality(g_t, "c.d") == HMI_Q_GOOD);
    CHECK(hmi_tags_quality(g_t, "e.f") == HMI_Q_BAD);
    frame("{\"a.b\":4}", "{}");
    CHECK(hmi_tags_quality(g_t, "e.f") == HMI_Q_GOOD);
}

static void test_request(void)
{
    const char *id = hmi_tags_request_history(g_t, "x.y", 99999999, 500);
    CHECK(id && id[0]);
    char keep[32];
    snprintf(keep, sizeof keep, "%s", id ? id : "");
    cJSON *c = next_cmd(800);
    CHECK(c != NULL);
    CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(c, "cmd")), "history");
    CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(c, "tag")), "x.y");
    CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(c, "id")), keep);
    CHECK(cJSON_GetObjectItem(c, "seconds") && cJSON_GetObjectItem(c, "seconds")->valueint == 604800);
    CHECK(cJSON_GetObjectItem(c, "points") && cJSON_GetObjectItem(c, "points")->valueint == 200);
    cJSON_Delete(c);
    id = hmi_tags_request_history(g_t, "x.y", 0, 0);
    c = next_cmd(800);
    CHECK(c && cJSON_GetObjectItem(c, "seconds")->valueint == 1 && cJSON_GetObjectItem(c, "points")->valueint == 1);
    cJSON_Delete(c);
}

static void test_backfill(void)
{
    frame("{\"h.t\":10}", NULL);
    frame("{\"h.t\":11}", NULL);
    frame("{\"h.t\":12}", NULL);
    int64_t now = wall_ms();

    // ok:false changes nothing
    char id[32];
    snprintf(id, sizeof id, "%s", hmi_tags_request_history(g_t, "h.t", 3600, 200));
    cJSON_Delete(next_cmd(800));
    char buf[8192];
    snprintf(buf, sizeof buf, "{\"t\":\"ack\",\"id\":\"%s\",\"ok\":false,\"err\":\"no_history\"}", id);
    g_history_calls = 0;
    send_json(buf);
    CHECK(g_history_calls == 0);
    hmi_value_t h = hmi_tags_history(g_t, "h.t", 200);
    CHECK(h.count == 3);
    hmi_value_free(&h);

    // older samples go in front; a sample newer than the ring is ignored
    snprintf(id, sizeof id, "%s", hmi_tags_request_history(g_t, "h.t", 3600, 200));
    cJSON_Delete(next_cmd(800));
    snprintf(buf, sizeof buf,
             "{\"t\":\"ack\",\"id\":\"%s\",\"ok\":true,\"history\":{\"tag\":\"h.t\",\"samples\":"
             "[[%lld,1],[%lld,2],[%lld,3],[%lld,99]]}}",
             id, (long long)(now - 30000), (long long)(now - 20000), (long long)(now - 10000),
             (long long)(now + 60000));
    send_json(buf);
    CHECK(g_history_calls == 1);
    CHECK_EQ_STR(g_history_tag, "h.t");
    h = hmi_tags_history(g_t, "h.t", 200);
    CHECK(h.count == 6);
    if (h.count == 6) {
        double want[6] = {1, 2, 3, 10, 11, 12};
        for (int i = 0; i < 6; i++) CHECK_NEAR(h.items[i].n, want[i], 1e-9);
    }
    hmi_value_free(&h);

    // the ring never passes 200: the oldest backfilled samples are dropped
    frame("{\"k.t\":1000}", NULL);
    frame("{\"k.t\":1001}", NULL);
    frame("{\"k.t\":1002}", NULL);
    now = wall_ms();
    snprintf(id, sizeof id, "%s", hmi_tags_request_history(g_t, "k.t", 3600, 200));
    cJSON_Delete(next_cmd(800));
    char *big = malloc(16000);
    int off = snprintf(big, 16000, "{\"t\":\"ack\",\"id\":\"%s\",\"ok\":true,\"history\":{\"tag\":\"k.t\",\"samples\":[", id);
    for (int i = 0; i < 250; i++)
        off += snprintf(big + off, 16000 - (size_t)off, "%s[%lld,%d]", i ? "," : "",
                        (long long)(now - 400000 + i * 1000), i);
    snprintf(big + off, 16000 - (size_t)off, "]}}");
    // (more than 8192 bytes would be dropped by the engine; 250 short samples fit)
    CHECK(strlen(big) < 8192);
    send_json(big);
    free(big);
    h = hmi_tags_history(g_t, "k.t", 1000);
    CHECK(h.count == 200);
    if (h.count == 200) {
        CHECK_NEAR(h.items[0].n, 53, 1e-9);        // 250 - 197 = 53
        CHECK_NEAR(h.items[196].n, 249, 1e-9);
        CHECK_NEAR(h.items[199].n, 1002, 1e-9);
    }
    hmi_value_free(&h);
}

int main(void)
{
    lv_init();
    lv_tick_set_cb(mono_ms);
    g_fd = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bind(g_fd, (struct sockaddr *)&a, sizeof a);
    socklen_t len = sizeof a;
    getsockname(g_fd, (struct sockaddr *)&a, &len);
    hmi_tags_options_t opt = {0, "127.0.0.1", ntohs(a.sin_port)};
    g_t = hmi_tags_create(&opt);
    hmi_tags_set_history_callback(g_t, on_history, NULL);

    test_quality();
    test_request();
    test_backfill();

    hmi_tags_destroy(g_t);
    close(g_fd);
    return check_summary("test_tags_history");
}
