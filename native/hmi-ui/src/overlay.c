// overlay.c -- see overlay.h (CONTRACT 13.5). Wave 1 W5 implements.
//
// Both objects live on lv_layer_top() and are created lazily: a panel that
// never loses its link and never idles has nothing extra in its tree.
#include "overlay.h"

#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "log.h"
#include "theme.h"

#define LINK_GRACE_MS 5000u
#define MAXPATH 512

struct hmi_overlay {
    // Link banner.
    bool has_link;
    bool online;
    bool was_online;              // a link(false) only counts after an online period
    bool ticked;
    bool grace_over;              // 5 s since the first tick
    uint32_t first_tick;
    lv_obj_t *banner;             // NULL until first shown

    // Idle / backlight.
    int dim_s, dim_pct, off_s;
    int bl_percent;               // what hmi_overlay_backlight_percent reports
    int bl_max;                   // max_brightness, read once; 0 = no backlight
    char bright_path[MAXPATH];    // <dir>/brightness
    lv_obj_t *blank;              // black, clickable, full screen while off
};

static const char *BANNER_TEXT = "No connection to controller - values may be stale";

// The first directory in $HMI_BACKLIGHT_DIR or /sys/class/backlight/ with a
// readable max_brightness; false (and nothing set) when there is none.
static bool find_backlight(hmi_overlay_t *o)
{
    const char *env = getenv("HMI_BACKLIGHT_DIR");
    const char *root = (env && *env) ? env : "/sys/class/backlight";
    DIR *d = opendir(root);
    if (!d) return false;
    char name[256] = "";
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        if (ent->d_name[0] == '.') continue;
        snprintf(name, sizeof name, "%s", ent->d_name);
        break;
    }
    closedir(d);
    if (!name[0]) return false;

    char path[MAXPATH];
    snprintf(path, sizeof path, "%s/%s/max_brightness", root, name);
    FILE *f = fopen(path, "r");
    if (!f) return false;
    long m = 0;
    if (fscanf(f, "%ld", &m) != 1) m = 0;
    fclose(f);
    if (m <= 0) {
        hmi_log(HMI_LOG_WARNING, "backlight %s: unreadable max_brightness", path);
        return false;
    }
    o->bl_max = (int)m;
    snprintf(o->bright_path, sizeof o->bright_path, "%s/%s/brightness", root, name);
    return true;
}

// Callers only come here on a change, so the file is written only then.
static void set_backlight(hmi_overlay_t *o, int pct)
{
    o->bl_percent = pct;
    if (o->bl_max <= 0) return;   // no backlight: the overlay alone
    FILE *f = fopen(o->bright_path, "w");
    if (!f) {
        hmi_log(HMI_LOG_WARNING, "backlight %s: cannot write", o->bright_path);
        return;
    }
    fprintf(f, "%ld\n", lround((double)o->bl_max * pct / 100.0));
    fclose(f);
}

static void set_banner(hmi_overlay_t *o, bool show)
{
    if (!show) {
        if (o->banner) lv_obj_add_flag(o->banner, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    if (!o->banner) {
        lv_obj_t *bar = lv_obj_create(lv_layer_top());
        lv_obj_remove_style_all(bar);
        lv_obj_set_size(bar, lv_pct(100), LV_SIZE_CONTENT);
        lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_remove_flag(bar, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_remove_flag(bar, LV_OBJ_FLAG_CLICKABLE);   // the page under it stays usable
        lv_obj_set_style_bg_color(bar, hmi_colour("destructive"), 0);
        lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
        lv_obj_set_style_pad_ver(bar, 6, 0);
        lv_obj_t *lbl = lv_label_create(bar);
        lv_obj_set_style_text_font(lbl, hmi_font(hmi_font_size("fontSizeSm"), 600), 0);
        lv_obj_set_style_text_color(lbl, hmi_colour("destructiveForeground"), 0);
        lv_label_set_text(lbl, BANNER_TEXT);
        lv_obj_align(lbl, LV_ALIGN_TOP_MID, 0, 0);
        o->banner = bar;
    }
    lv_obj_remove_flag(o->banner, LV_OBJ_FLAG_HIDDEN);
}

static void update_banner(hmi_overlay_t *o)
{
    if (!o->has_link || o->online) set_banner(o, false);
    else set_banner(o, o->was_online || o->grace_over);
}

static void blank_pressed_cb(lv_event_t *e)
{
    hmi_overlay_wake(lv_event_get_user_data(e));
}

static void set_blank(hmi_overlay_t *o, bool on)
{
    if (!on) {
        if (o->blank) { lv_obj_delete(o->blank); o->blank = NULL; }
        return;
    }
    if (o->blank) return;
    // Clickable and on top of everything: the waking touch lands here and
    // never reaches the widget underneath.
    lv_obj_t *b = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(b, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_add_flag(b, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(b, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(b, blank_pressed_cb, LV_EVENT_PRESSED, o);
    o->blank = b;
}

hmi_overlay_t *hmi_overlay_create(const hmi_project_t *project, bool has_link)
{
    hmi_overlay_t *o = calloc(1, sizeof *o);
    if (!o) return NULL;
    o->has_link = has_link;
    o->bl_percent = 100;
    if (project) {
        o->dim_s = project->idle_dim_s > 0 ? project->idle_dim_s : 0;
        o->dim_pct = project->idle_dim_pct;
        if (o->dim_pct < 10 || o->dim_pct > 100) o->dim_pct = 30;
        o->off_s = project->idle_off_s > 0 ? project->idle_off_s : 0;
    }
    // Only a panel that can idle needs the backlight.
    if (o->dim_s || o->off_s) find_backlight(o);
    return o;
}

void hmi_overlay_destroy(hmi_overlay_t *o)
{
    if (!o) return;
    set_blank(o, false);
    if (o->banner) lv_obj_delete(o->banner);
    free(o);
}

void hmi_overlay_link(hmi_overlay_t *o, bool online)
{
    if (!o) return;
    o->online = online;
    if (online) o->was_online = true;
    update_banner(o);
}

void hmi_overlay_tick(hmi_overlay_t *o, uint32_t now_ms, uint32_t inactive_ms)
{
    if (!o) return;
    if (!o->ticked) { o->ticked = true; o->first_tick = now_ms; }
    if (!o->grace_over && now_ms - o->first_tick >= LINK_GRACE_MS) {
        o->grace_over = true;
        update_banner(o);
    }

    int pct = 100;
    bool off = false;
    if (o->off_s && inactive_ms >= (uint32_t)o->off_s * 1000u) {
        pct = 0;
        off = true;
    } else if (o->dim_s && inactive_ms >= (uint32_t)o->dim_s * 1000u) {
        pct = o->dim_pct;
    }
    if (pct != o->bl_percent) set_backlight(o, pct);
    set_blank(o, off);
}

bool hmi_overlay_banner_visible(const hmi_overlay_t *o)
{
    return o && o->banner && !lv_obj_has_flag(o->banner, LV_OBJ_FLAG_HIDDEN);
}

int hmi_overlay_backlight_percent(const hmi_overlay_t *o) { return o ? o->bl_percent : 100; }

bool hmi_overlay_blanked(const hmi_overlay_t *o) { return o && o->blank != NULL; }

bool hmi_overlay_wake(hmi_overlay_t *o)
{
    if (!o) return false;
    bool was_blank = o->blank != NULL;
    if (o->bl_percent != 100) set_backlight(o, 100);
    // Deleting the pressed object from its own PRESSED callback is safe in
    // LVGL 9 (the indev is reset), and that reset is what drops the release.
    set_blank(o, false);
    return was_blank;
}
