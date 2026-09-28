// overlay.c -- see overlay.h (CONTRACT 13.5). STUB: wave 1 W5 implements.
#include "overlay.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "compat.h"
#include "log.h"
#include "theme.h"

#define IDLE_GRACE_MS 5000u
#define MAXPATH 512

struct hmi_overlay {
    // Link banner.
    lv_obj_t *banner;             // NULL until shown
    bool has_link;
    bool online;
    uint32_t first_tick;          // ms of the first tick; 0 = never ticked
    bool grace_used;              // the 5 s grace since the first tick elapsed

    // Idle / backlight.
    int idle_dim_s;
    int idle_dim_pct;
    int idle_off_s;
    int bl_percent;               // what hmi_overlay_backlight_percent reports
    int bl_max;                   // max_brightness, read once; 0 = no backlight dir
    char dir[MAXPATH];            // the brightness-bearing directory (trailing /)
    lv_obj_t *blank;              // black full-screen object while off
    lv_obj_t *wake;               // clickable layer that swallows the waking touch
    bool blanked;
};

static const char *BANNER_TEXT = "No connection to controller - values may be stale";

// Resolve the brightness file's directory: the first entry of
// $HMI_BACKLIGHT_DIR or /sys/class/backlight/. On success store max_brightness
// in *max_out and the directory base in base (with a trailing '/').
static bool resolve_backlight_dir(char *base, size_t len, int *max_out)
{
    const char *env = getenv("HMI_BACKLIGHT_DIR");
    const char *root = (env && *env) ? env : "/sys/class/backlight";

    char cmd[MAXPATH];
    snprintf(cmd, sizeof cmd, "ls '%s' 2>/dev/null", root);
    FILE *d = popen(cmd, "r");
    if (!d) { *max_out = 0; return false; }

    char name[256] = "";
    char line[256];
    while (fgets(line, sizeof line, d)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r' || line[n - 1] == ' ' ||
                     line[n - 1] == '\t'))
            line[--n] = '\0';
        if (n && line[0] != '.') {
            snprintf(name, sizeof name, "%s", line);
            break;
        }
    }
    pclose(d);
    if (!name[0]) { *max_out = 0; return false; }

    char basep[MAXPATH];
    snprintf(basep, sizeof basep, "%s/%s/", root, name);
    char maxp[MAXPATH];
    snprintf(maxp, sizeof maxp, "%smax_brightness", basep);
    FILE *f = fopen(maxp, "r");
    if (!f) { *max_out = 0; return false; }
    long m = 1;
    if (fscanf(f, "%ld", &m) != 1 || m <= 0) m = 1;
    fclose(f);

    snprintf(base, len, "%s", basep);
    *max_out = (int)m;
    return true;
}

static void read_backlight(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    char dir[MAXPATH];
    if (!resolve_backlight_dir(dir, sizeof dir, &o->bl_max))
        o->bl_max = 0;
}

static void set_backlight(hmi_overlay_t *o_, int pct)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    o->bl_percent = pct;
    if (o->bl_max <= 0) return;                     // no backlight: only the report changes
    char abs[MAXPATH];
    snprintf(abs, sizeof abs, "%s/brightness", o->dir);
    long v = (long)lround((double)o->bl_max * pct / 100.0);
    FILE *f = fopen(abs, "w");
    if (f) { fprintf(f, "%ld\n", v); fclose(f); }
}

static void show_banner(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (o->banner) { lv_obj_clear_flag(o->banner, LV_OBJ_FLAG_HIDDEN); return; }
    lv_obj_t *bar = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, lv_pct(100), LV_SIZE_CONTENT);
    lv_obj_align(bar, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(bar, hmi_colour("destructive"), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_t *lbl = lv_label_create(bar);
    lv_label_set_text(lbl, BANNER_TEXT);
    lv_obj_align(lbl, LV_ALIGN_TOP_MID, 0, 6);
    lv_obj_update_layout(bar);
    o->banner = bar;
}

static void hide_banner(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (!o->banner) return;
    lv_obj_add_flag(o->banner, LV_OBJ_FLAG_HIDDEN);
}

static void show_blank(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    // The black full-screen object is the visible "off" screen; the separate
    // clickable wake object above it swallows the touch that wakes it.
    lv_obj_t *blk = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(blk);
    lv_obj_set_size(blk, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(blk, lv_color_hex(0x000000), LV_OPA_COVER);
    lv_obj_set_style_bg_opa(blk, LV_OPA_COVER, 0);
    lv_obj_set_radius(blk, 0);
    lv_obj_remove_flag(blk, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *wake = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(wake);
    lv_obj_set_size(wake, lv_pct(100), lv_pct(100));
    lv_obj_set_style_bg_color(wake, lv_color_hex(0x000000), LV_OPA_TRANSP);
    lv_obj_set_radius(wake, 0);
    lv_obj_add_flag(wake, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_remove_flag(wake, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_SCROLL_ON_FOCUS);
    lv_obj_add_event_cb(wake, wake_cb, LV_EVENT_CLICKED, o);

    o->blank = blk;
    o->wake = wake;
    o->blanked = true;
}

static void hide_blank(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (o->blank) { lv_obj_delete(o->blank); o->blank = NULL; }
    if (o->wake) { lv_obj_delete(o->wake); o->wake = NULL; }
    o->blanked = false;
}

static void wake_cb(lv_event_t *e)
{
    // The touch that wakes an off screen is swallowed here; hmi_overlay_wake
    // performs the unblank on the next tick / call.
    (void)e;
}

bool hmi_overlay_banner_visible(const hmi_overlay_t *o)
{
    return o && o->banner && !lv_obj_has_flag(o->banner, LV_OBJ_FLAG_HIDDEN);
}

int hmi_overlay_backlight_percent(const hmi_overlay_t *o)
{
    return o ? o->bl_percent : 100;
}

bool hmi_overlay_blanked(const hmi_overlay_t *o)
{
    return o && o->blanked;
}

bool hmi_overlay_wake(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (!o || !o->blanked) return false;
    set_backlight(o, 100);                          // the touch restores full brightness
    hide_blank(o);
    return true;
}

void hmi_overlay_link(hmi_overlay_t *o_, bool online)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (!o) return;
    o->online = online;
    hide_banner(o);
}

void hmi_overlay_tick(hmi_overlay_t *o_, uint32_t now_ms, uint32_t inactive_ms)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (!o) return;
    if (!o->first_tick) o->first_tick = now_ms;
    if (now_ms - o->first_tick >= IDLE_GRACE_MS) o->grace_used = true;

    // Link banner: after the 5 s grace while still offline, or once online is
    // dropped again.
    if (o->has_link && !o->online) {
        if (o->grace_used) show_banner(o);
    } else {
        hide_banner(o);
    }

    // Idle: off first, then dim, else full.
    int target = 100;
    bool blank = false;
    if (o->idle_off_s && inactive_ms >= (uint32_t)o->idle_off_s * 1000u) {
        target = 0;
        blank = true;
    } else if (o->idle_dim_s && inactive_ms >= (uint32_t)o->idle_dim_s * 1000u) {
        target = o->idle_dim_pct;
    }
    if (target != o->bl_percent) set_backlight(o, target);
    if (blank) {
        if (!o->blanked) show_blank(o);
    } else if (o->blanked) {
        hide_blank(o);
    }
}

void hmi_overlay_destroy(hmi_overlay_t *o_)
{
    struct hmi_overlay *o = (struct hmi_overlay *)o_;
    if (!o) return;
    hide_blank(o);
    if (o->banner) { lv_obj_delete(o->banner); o->banner = NULL; }
    free(o);
}

hmi_overlay_t *hmi_overlay_create(const hmi_project_t *project, bool has_link)
{
    hmi_overlay_t *o = calloc(1, sizeof *o);
    if (!o) return NULL;
    o->has_link = has_link;
    o->bl_percent = 100;
    if (project) {
        o->idle_dim_s = project->idle_dim_s;
        o->idle_dim_pct = project->idle_dim_pct;
        o->idle_off_s = project->idle_off_s;
    }
    char dir[MAXPATH];
    if (!resolve_backlight_dir(dir, sizeof dir, &o->bl_max))
        o->bl_max = 0;
    return o;
}