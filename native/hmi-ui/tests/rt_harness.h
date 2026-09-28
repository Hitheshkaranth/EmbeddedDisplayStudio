// tests/rt_harness.h -- a runtime on a headless display with a fake daemon.
// Wave 1 gates (FROZEN). Linux only (POSIX sockets), like the rest of ctest.
//
//   rt_t h; rt_open(&h, DESIGN_JSON, true);   // true: with a daemon link
//   hmi_widget_t *w = rt_widget(&h, "button1");
//   hmi_runtime_signal(w, "clicked", NULL);
//   cJSON *cmd = rt_next_command(&h, 500);    // the next command sent, or NULL
//   ...
//   rt_close(&h);
#pragma once

#include <arpa/inet.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "cJSON.h"
#include "compat.h"
#include "display.h"
#include "model.h"
#include "registry.h"
#include "runtime.h"
#include "tags.h"
#include "theme.h"

typedef struct {
    hmi_project_t *project;
    hmi_runtime_t *rt;
    hmi_tags_t *tags;
    int daemon_fd;                 // the fake daemon's socket
    struct sockaddr_in client;     // where the runtime's tag engine listens
    bool have_client;
} rt_t;

static bool g_rt_lvgl_ready;

static void rt_lvgl_once(void)
{
    if (g_rt_lvgl_ready) return;
    g_rt_lvgl_ready = true;
    lv_init();
    hmi_kit_register_all();
    hmi_theme_init(HMI_REPO_ROOT "/ui/qml/Shadcn", true);
    hmi_display_headless(800, 480);
}

static hmi_project_t *rt_load_json(const char *json)
{
    char path[512], err[256];
    FILE *f = hmi_tmpfile(path, sizeof path);
    if (!f) return NULL;
    fputs(json, f);
    fclose(f);
    hmi_project_t *p = hmi_project_load(path, err, sizeof err);
    hmi_remove(path);
    if (!p) fprintf(stderr, "rt_load_json: %s\n", err);
    return p;
}

static void rt_pump(rt_t *h, int ms)
{
    uint32_t end = lv_tick_get() + (uint32_t)ms;
    do {
        lv_timer_handler();
        if (h->tags) hmi_tags_poll(h->tags);
        hmi_runtime_tick(h->rt);
        hmi_sleep_ms(2);
    } while ((int32_t)(end - lv_tick_get()) > 0);
}

static uint32_t rt_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

// The tag engine -> runtime wiring main.c does (tag changes reach bindings
// and alarms; the link state reaches the overlay).
static void rt_on_tag(const char *tag, const hmi_value_t *value, void *user)
{
    hmi_runtime_on_tag((hmi_runtime_t *)user, tag, value);
}

static void rt_on_online(bool online, void *user)
{
    hmi_runtime_on_online((hmi_runtime_t *)user, online);
}

// apps_dir may be NULL (no manifest alarms).
static bool rt_open_dir(rt_t *h, const char *design_json, bool with_link, const char *apps_dir)
{
    memset(h, 0, sizeof *h);
    h->daemon_fd = -1;
    rt_lvgl_once();
    lv_tick_set_cb(rt_now_ms);
    h->project = rt_load_json(design_json);
    if (!h->project) return false;
    if (with_link) {
        h->daemon_fd = socket(AF_INET, SOCK_DGRAM, 0);
        struct sockaddr_in a = {0};
        a.sin_family = AF_INET;
        a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        a.sin_port = 0;
        bind(h->daemon_fd, (struct sockaddr *)&a, sizeof a);
        socklen_t len = sizeof a;
        getsockname(h->daemon_fd, (struct sockaddr *)&a, &len);
        hmi_tags_options_t opt = {0, "127.0.0.1", ntohs(a.sin_port)};
        h->tags = hmi_tags_create(&opt);
    }
    h->rt = hmi_runtime_create(h->project, lv_screen_active(), h->tags, apps_dir);
    if (h->tags && h->rt) hmi_tags_set_callbacks(h->tags, rt_on_tag, rt_on_online, NULL, h->rt);
    return h->rt != NULL;
}

static bool rt_open(rt_t *h, const char *design_json, bool with_link)
{
    return rt_open_dir(h, design_json, with_link, NULL);
}

static void rt_close(rt_t *h)
{
    if (h->rt) hmi_runtime_destroy(h->rt);
    if (h->tags) hmi_tags_destroy(h->tags);
    if (h->project) hmi_project_free(h->project);
    if (h->daemon_fd >= 0) close(h->daemon_fd);
    lv_obj_clean(lv_layer_top());
    memset(h, 0, sizeof *h);
    h->daemon_fd = -1;
}

static hmi_widget_t *rt_widget(rt_t *h, const char *id)
{
    for (size_t p = 0; p < h->project->npages; ++p) {
        hmi_page_t *pg = h->project->pages[p];
        for (size_t i = 0; i < pg->nwidgets; ++i)
            if (strcmp(pg->widgets[i]->id, id) == 0) return pg->widgets[i];
    }
    return NULL;
}

// The next command datagram (skipping subscribe/ping/unsubscribe), or NULL
// after timeout_ms. Caller cJSON_Delete()s it.
static cJSON *rt_next_command(rt_t *h, int timeout_ms)
{
    if (h->daemon_fd < 0) return NULL;
    uint32_t end = lv_tick_get() + (uint32_t)timeout_ms;
    for (;;) {
        if (h->tags) hmi_tags_poll(h->tags);
        struct pollfd pfd = {h->daemon_fd, POLLIN, 0};
        if (poll(&pfd, 1, 5) > 0) {
            char buf[9000];
            struct sockaddr_in from;
            socklen_t len = sizeof from;
            ssize_t n = recvfrom(h->daemon_fd, buf, sizeof buf - 1, 0, (struct sockaddr *)&from, &len);
            if (n > 0) {
                buf[n] = 0;
                h->client = from;
                h->have_client = true;
                cJSON *j = cJSON_Parse(buf);
                const char *cmd = j ? cJSON_GetStringValue(cJSON_GetObjectItem(j, "cmd")) : NULL;
                if (cmd && strcmp(cmd, "subscribe") != 0 && strcmp(cmd, "ping") != 0 &&
                    strcmp(cmd, "unsubscribe") != 0)
                    return j;
                cJSON_Delete(j);
            }
        }
        if ((int32_t)(end - lv_tick_get()) <= 0) return NULL;
    }
}

// Make sure the engine has subscribed (so the harness knows its address).
static bool rt_wait_client(rt_t *h, int timeout_ms)
{
    uint32_t end = lv_tick_get() + (uint32_t)timeout_ms;
    while (!h->have_client) {
        cJSON *j = rt_next_command(h, 50);
        cJSON_Delete(j);
        if ((int32_t)(end - lv_tick_get()) <= 0) break;
    }
    return h->have_client;
}

// Send raw JSON to the runtime's tag engine, then let it deliver.
static void rt_send(rt_t *h, const char *json)
{
    if (!rt_wait_client(h, 3000)) return;
    sendto(h->daemon_fd, json, strlen(json), 0, (struct sockaddr *)&h->client, sizeof h->client);
    rt_pump(h, 30);
}

// A telemetry frame with the given "tags" object text, e.g. "{\"a.b\":1}".
static void rt_frame(rt_t *h, const char *tags_obj)
{
    char buf[8192];
    snprintf(buf, sizeof buf, "{\"t\":\"tags\",\"seq\":1,\"ts\":0,\"src\":\"test\",\"tags\":%s}", tags_obj);
    rt_send(h, buf);
}

static const char *rt_cmd_str(cJSON *cmd, const char *key)
{
    return cmd ? cJSON_GetStringValue(cJSON_GetObjectItem(cmd, key)) : NULL;
}

static double rt_cmd_num(cJSON *cmd, const char *key, double def)
{
    cJSON *v = cmd ? cJSON_GetObjectItem(cmd, key) : NULL;
    if (cJSON_IsBool(v)) return cJSON_IsTrue(v) ? 1 : 0;
    return cJSON_IsNumber(v) ? v->valuedouble : def;
}
