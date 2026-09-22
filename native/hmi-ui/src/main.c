// main.c -- hmi-ui: the Qt-free panel GUI runtime.
//
//   hmi-ui --apps-dir DIR [--display /dev/dri/card1] [--rx-port N]
//          [--daemon-host H] [--daemon-port N] [--ready-file F]
//          [--exit-after MS] [--log-level L] [--kit DIR] [--theme dark|light]
//       Loads DIR/project.edsui, shows its first page on the display, talks
//       to hmi-hwd. The flags are the loaders' (CONTRACT section 5) so
//       hmi-gui-launch and the test harness need no special case.
//   hmi-ui --apps-dir DIR --headless OUT.png [--size WxH]
//       Renders the first page once (no daemon) into a PNG and exits.
//   hmi-ui --render-widget TYPE --headless OUT.png [--size WxH] [--props JSON]
//       Renders one kit widget with the given properties (JSON object) at
//       its registered default size unless --size is given: the parity gate.
//   The headless build (HMI_UI_WITH_DRM=0: the Studio's preview binary on
//   Windows) has no display or touch input; without --headless it says so
//   and exits.
#include <getopt.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "cJSON.h"
#include "compat.h"
#include "display.h"
#include "gen/kit_schema.h"
#include "log.h"
#include "lvgl/lvgl.h"
#include "model.h"
#include "registry.h"
#include "runtime.h"
#include "tags.h"
#include "theme.h"

static volatile sig_atomic_t g_stop;
static void on_signal(int sig) { (void)sig; g_stop = 1; }
#ifndef _WIN32
// SIGUSR1 asks for a picture of the glass: the loop writes /run/hmi/screen.png
// (or $HMI_UI_SNAPSHOT) on its next turn.
static volatile sig_atomic_t g_snapshot;
static void on_snapshot(int sig) { (void)sig; g_snapshot = 1; }
#endif

static uint32_t now_ms(void) { return (uint32_t)hmi_millis(); }

static void write_ready(const char *path)
{
    if (!path || !*path) return;
    FILE *f = fopen(path, "w");
    if (f) { fputs("ready\n", f); fclose(f); hmi_log(HMI_LOG_INFO, "Marked ready at %s", path); }
    else hmi_log(HMI_LOG_WARNING, "cannot write ready file %s", path);
}

typedef struct { hmi_runtime_t *rt; } cbs_t;
static void on_tag(const char *tag, const hmi_value_t *v, void *user) { hmi_runtime_on_tag(((cbs_t *)user)->rt, tag, v); }
static void on_online(bool online, void *user) { hmi_runtime_on_online(((cbs_t *)user)->rt, online); }
static void on_ack(const char *id, bool ok, const char *err, const hmi_value_t *tags, void *user)
{
    (void)tags; (void)user;
    hmi_log(HMI_LOG_DEBUG, "ack %s ok=%d err=%s", id, ok, err ? err : "");
}

// A one-widget project built in memory for --render-widget.
static hmi_project_t *widget_project(const char *type, int w, int h, const char *props_json, char *err, size_t errlen)
{
    const hmi_type_schema_t *ts = hmi_kit_find(type);
    if (!ts) { snprintf(err, errlen, "unknown widget type %s", type); return NULL; }
    if (w <= 0) w = ts->default_width;
    if (h <= 0) h = ts->default_height;
    cJSON *root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "name", "widget");
    cJSON *screen = cJSON_AddObjectToObject(root, "screen");
    cJSON_AddNumberToObject(screen, "width", w);
    cJSON_AddNumberToObject(screen, "height", h);
    cJSON_AddStringToObject(screen, "background", "#101318");
    cJSON_AddStringToObject(screen, "theme", "dark");
    cJSON *pages = cJSON_AddArrayToObject(root, "pages");
    cJSON *page = cJSON_CreateObject();
    cJSON_AddStringToObject(page, "id", "main");
    cJSON *widgets = cJSON_AddArrayToObject(page, "widgets");
    cJSON *widget = cJSON_CreateObject();
    cJSON_AddStringToObject(widget, "type", type);
    cJSON_AddStringToObject(widget, "id", "sample");
    cJSON *geom = cJSON_AddObjectToObject(widget, "geometry");
    cJSON_AddNumberToObject(geom, "x", 0); cJSON_AddNumberToObject(geom, "y", 0);
    cJSON_AddNumberToObject(geom, "width", w); cJSON_AddNumberToObject(geom, "height", h);
    cJSON *props = props_json ? cJSON_Parse(props_json) : NULL;
    if (props_json && !props) { snprintf(err, errlen, "--props is not valid JSON"); cJSON_Delete(root); return NULL; }
    cJSON_AddItemToObject(widget, "properties", props ? props : cJSON_CreateObject());
    cJSON_AddItemToArray(widgets, widget);
    cJSON_AddItemToArray(pages, page);
    char *text = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    char path[512];
    FILE *f = hmi_tmpfile(path, sizeof path);
    if (!f) { snprintf(err, errlen, "cannot create a temporary file"); free(text); return NULL; }
    fputs(text, f);
    fclose(f);
    free(text);
    hmi_project_t *p = hmi_project_load(path, err, errlen);
    hmi_remove(path);
    return p;
}

int main(int argc, char **argv)
{
    const char *apps_dir = "/opt/hmi_apps/current";
    const char *display = "/dev/dri/card1";
    const char *touch = getenv("HMI_UI_TOUCH");   // /dev/input/eventN; unset = none
    const char *headless = NULL;
    const char *ready_file = NULL;
    const char *kit = NULL;
    const char *theme = NULL;
    const char *render_widget = NULL;
    const char *props = NULL;
    int size_w = 0, size_h = 0;
    long exit_after = 0;
    hmi_tags_options_t topt = {5001, "127.0.0.1", 5000};

    static const struct option opts[] = {
        {"apps-dir", 1, 0, 'a'}, {"display", 1, 0, 'd'}, {"headless", 1, 0, 'H'},
        {"rx-port", 1, 0, 'r'}, {"daemon-host", 1, 0, 'h'}, {"daemon-port", 1, 0, 'p'},
        {"ready-file", 1, 0, 'f'}, {"exit-after", 1, 0, 'e'}, {"log-level", 1, 0, 'l'},
        {"kit", 1, 0, 'k'}, {"theme", 1, 0, 't'}, {"render-widget", 1, 0, 'W'},
        {"size", 1, 0, 's'}, {"props", 1, 0, 'P'}, {"windowed", 0, 0, 'w'}, {"shell", 1, 0, 'S'},
        {"touch", 1, 0, 'T'},
        {0, 0, 0, 0}};
    int c;
    while ((c = getopt_long(argc, argv, "", opts, NULL)) != -1) {
        switch (c) {
        case 'a': apps_dir = optarg; break;
        case 'd': display = optarg; break;
        case 'H': headless = optarg; break;
        case 'r': topt.rx_port = (uint16_t)atoi(optarg); break;
        case 'h': topt.daemon_host = optarg; break;
        case 'p': topt.daemon_port = (uint16_t)atoi(optarg); break;
        case 'f': ready_file = optarg; break;
        case 'e': exit_after = atol(optarg); break;
        case 'l': hmi_log_set_level(optarg); break;
        case 'k': kit = optarg; break;
        case 't': theme = optarg; break;
        case 'W': render_widget = optarg; break;
        case 's': sscanf(optarg, "%dx%d", &size_w, &size_h); break;
        case 'P': props = optarg; break;
        case 'T': touch = optarg; break;
        case 'w': case 'S': break;   // accepted for flag compatibility with hmi-gui; no effect
        default: fprintf(stderr, "usage: see main.c\n"); return 2;
        }
    }

#if !HMI_UI_WITH_DRM
    if (!headless) {
        fprintf(stderr, "this is the headless build of hmi-ui (no display); use --headless\n");
        return 2;
    }
#endif

    signal(SIGTERM, on_signal);   // systemd stop / harness terminate: leave cleanly
    signal(SIGINT, on_signal);
#ifndef _WIN32
    signal(SIGUSR1, on_snapshot);
#endif
    lv_init();
    lv_tick_set_cb(now_ms);
    hmi_kit_register_all();

    char err[256] = "";
    hmi_project_t *project;
    if (render_widget) {
        project = widget_project(render_widget, size_w, size_h, props, err, sizeof err);
    } else {
        char path[1024];
        snprintf(path, sizeof path, "%s/project.edsui", apps_dir);
        project = hmi_project_load(path, err, sizeof err);
    }
    if (!project) {
        hmi_log(HMI_LOG_CRITICAL, "%s", err);
        return 1;
    }
    if (theme) { free(project->theme); project->theme = strdup(theme); }
    const char *kit_dir = hmi_theme_init(kit, strcmp(project->theme, "light") != 0);
    hmi_log(HMI_LOG_INFO, "hmi-ui %s: %s (%dx%d, theme %s, kit %s)", HMI_UI_VERSION, project->name,
            project->width, project->height, project->theme, kit_dir[0] ? kit_dir : "none");

    lv_display_t *disp;
    if (headless) {
        int w = size_w > 0 ? size_w : project->width, h = size_h > 0 ? size_h : project->height;
        disp = hmi_display_headless(w, h);
    } else {
#if HMI_UI_WITH_DRM
        disp = hmi_display_drm(display);
        if (touch && *touch) {
            lv_indev_t *indev = lv_evdev_create(LV_INDEV_TYPE_POINTER, touch);
            if (indev) { lv_indev_set_display(indev, disp); hmi_log(HMI_LOG_INFO, "touch input %s", touch); }
            else hmi_log(HMI_LOG_WARNING, "cannot open touch device %s", touch);
        }
#else
        (void)display; (void)touch;
        return 0;   // unreachable: refused above, before anything was loaded
#endif
    }
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);

    hmi_tags_t *tags = NULL;
    cbs_t cbs = {NULL};
    if (!headless) {
        tags = hmi_tags_create(&topt);
    }
    hmi_runtime_t *rt = hmi_runtime_create(project, screen, tags, render_widget ? NULL : apps_dir);
    cbs.rt = rt;
    if (tags)
        hmi_tags_set_callbacks(tags, on_tag, on_online, on_ack, &cbs);

    int status = 0;
    if (headless) {
        status = hmi_display_headless_save(disp, headless) ? 0 : 1;
        hmi_log(HMI_LOG_INFO, "rendered %s", headless);
    } else {
        write_ready(ready_file);
        uint32_t t0 = now_ms();
        for (;;) {
            lv_timer_handler();
            if (tags) hmi_tags_poll(tags);
            hmi_runtime_tick(rt);
#ifndef _WIN32
            if (g_snapshot) {
                g_snapshot = 0;
                const char *snap = getenv("HMI_UI_SNAPSHOT");
                hmi_display_snapshot(snap && *snap ? snap : "/run/hmi/screen.png");
            }
#endif
            if (g_stop) break;
            if (exit_after > 0 && now_ms() - t0 >= (uint32_t)exit_after) break;
            hmi_sleep_ms(4);
        }
        hmi_log(HMI_LOG_INFO, g_stop ? "exiting on signal" : "exiting after %ld ms", exit_after);
    }
    hmi_runtime_destroy(rt);
    if (tags) hmi_tags_destroy(tags);
    hmi_project_free(project);
    return status;
}
