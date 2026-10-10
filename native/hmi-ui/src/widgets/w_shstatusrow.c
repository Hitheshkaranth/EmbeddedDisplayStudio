// widgets/w_shstatusrow.c -- kit widget ShStatusRow (Industrial, "Status row").
//
// Spec: ui/qml/Shadcn/ShStatusRow.qml -- one line of a "Key Status" list:
//     (o) Main Drive                         [ RUNNING ]
// a glossy lamp dot, the label (foreground) and a status badge at the right
// whose colours follow `state`: ok = Theme.success with dark text, warn =
// Theme.warning with dark text, fault = Theme.destructive with white text,
// idle = Theme.muted with mutedForeground text (its lamp mutedForeground).
// The lamp is the state colour with a rim 35 % darker and a highlight 55 %
// lighter up and to the left.
//
// Geometry (shared with the QML): lamp clamp(round(0.55 H), 6, 18) at x
// round(0.15 H); the label after a gap of max(6, round(0.6 H)), regular
// clamp(round(0.5 H), 8, 18), shrinking to 75 % then eliding; the badge
// clamp(round(0.72 H), 10, 28) tall, max(text + h, round(0.29 W)) wide
// (at most half the row), right-aligned, radius 2, semibold
// clamp(round(0.6 badge), 7, 16), centred. Stacked rows line their badges up.
//
// Children of the root, in order: lamp (-> highlight), label, badge (-> text).
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"
#include "text_util.h"

typedef struct {
    lv_obj_t *root, *lamp, *shine, *label, *badge, *btext;
    char label_text[96], status_text[48], state[16];
} state_t;

static int clampi(double v, int lo, int hi)
{
    int r = (int)lround(v);
    return r < lo ? lo : r > hi ? hi : r;
}

// The state's lamp/badge fill and the badge's ink.
static void state_colours(const char *state, lv_color_t *fill, lv_color_t *lamp, lv_color_t *ink)
{
    if (strcmp(state, "ok") == 0) {
        *fill = *lamp = hmi_colour("success");
        *ink = lv_color_hex(0x07130b);
    } else if (strcmp(state, "warn") == 0) {
        *fill = *lamp = hmi_colour("warning");
        *ink = lv_color_hex(0x1a1203);
    } else if (strcmp(state, "fault") == 0) {
        *fill = *lamp = hmi_colour("destructive");
        *ink = lv_color_hex(0xffffff);
    } else {
        *fill = hmi_colour("muted");
        *lamp = hmi_colour("mutedForeground");
        *ink = hmi_colour("mutedForeground");
    }
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    int Wi = (int)lround(W), Hi = (int)lround(H);
    lv_obj_set_size(st->root, Wi, Hi);
    lv_color_t fill, lampc, ink;
    state_colours(st->state, &fill, &lampc, &ink);

    int d = clampi(H * 0.55, 6, 18);
    int dx = (int)lround(H * 0.15);
    lv_obj_set_pos(st->lamp, dx, (Hi - d) / 2);
    lv_obj_set_size(st->lamp, d, d);
    lv_obj_set_style_radius(st->lamp, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(st->lamp, lampc, 0);
    lv_obj_set_style_bg_opa(st->lamp, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(st->lamp, hmi_shade(lampc, -35), 0);
    lv_obj_set_style_border_width(st->lamp, d >= 10 ? 1 : 0, 0);
    int s = (int)fmax(2, lround(d * 0.36));
    lv_obj_set_size(st->shine, s, s);
    lv_obj_set_pos(st->shine, (int)lround(d * 0.22) - (d >= 10 ? 1 : 0), (int)lround(d * 0.18) - (d >= 10 ? 1 : 0));
    lv_obj_set_style_radius(st->shine, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(st->shine, hmi_shade(lampc, 55), 0);
    lv_obj_set_style_bg_opa(st->shine, (lv_opa_t)200, 0);

    int bh = clampi(H * 0.72, 10, 28);
    int bpx = clampi(bh * 0.6, 7, 16);
    int tw = hmi_text_w(st->status_text, bpx, 600);
    int bw = (int)fmax(tw + bh, lround(W * 0.29));
    if (bw > Wi / 2) bw = Wi / 2;
    if (st->status_text[0] == '\0') bw = 0;
    int bx = Wi - bw;
    if (bw > 0) {
        lv_obj_set_pos(st->badge, bx, (Hi - bh) / 2);
        lv_obj_set_size(st->badge, bw, bh);
        lv_obj_set_style_radius(st->badge, 2, 0);
        lv_obj_set_style_bg_color(st->badge, fill, 0);
        lv_obj_set_style_bg_opa(st->badge, LV_OPA_COVER, 0);
        int lh = hmi_text_line_h(bpx, 600);
        hmi_text_place(st->btext, st->status_text, bpx, 600, 0.75, 2, (bh - lh) / 2, bw - 4, ink, LV_OPA_COVER,
                       LV_TEXT_ALIGN_CENTER);
        lv_obj_remove_flag(st->badge, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->badge, LV_OBJ_FLAG_HIDDEN);
    }

    int lpx = clampi(H * 0.5, 8, 18);
    int lx = dx + d + (int)fmax(6, lround(H * 0.6));
    int lw = (bw > 0 ? bx - 6 : Wi) - lx;
    if (lw > 0 && st->label_text[0]) {
        hmi_text_place(st->label, st->label_text, lpx, 400, 0.75, lx, (Hi - hmi_text_line_h(lpx, 400)) / 2, lw,
                       hmi_colour("foreground"), LV_OPA_COVER, LV_TEXT_ALIGN_LEFT);
    } else {
        lv_obj_add_flag(st->label, LV_OBJ_FLAG_HIDDEN);
    }
}

static lv_obj_t *plain(lv_obj_t *parent)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_CLICKABLE);
    return o;
}

static void copy_text(char *dst, size_t n, const hmi_value_t *v)
{
    char tmp[64];
    snprintf(dst, n, "%s", hmi_text_of(v, tmp, sizeof tmp, ""));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *root = plain(parent);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->root = root;
    st->lamp = plain(root);
    st->shine = plain(st->lamp);
    st->label = hmi_make_label(root, 13, 400, hmi_colour("foreground"), "");
    st->badge = plain(root);
    st->btext = hmi_make_label(st->badge, 11, 600, hmi_colour("foreground"), "");
    copy_text(st->label_text, sizeof st->label_text, hmi_widget_get(w, "label"));
    copy_text(st->status_text, sizeof st->status_text, hmi_widget_get(w, "status"));
    copy_text(st->state, sizeof st->state, hmi_widget_get(w, "state"));
    layout(w);
    return root;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "label") == 0) copy_text(st->label_text, sizeof st->label_text, value);
    else if (strcmp(prop, "status") == 0) copy_text(st->status_text, sizeof st->status_text, value);
    else if (strcmp(prop, "state") == 0) copy_text(st->state, sizeof st->state, value);
    else return;
    layout(w);
}

static void destroy(hmi_widget_t *w)
{
    lv_free(w->state);
    w->state = NULL;
}

const hmi_widget_ops_t hmi_widget_shstatusrow = {"ShStatusRow", create, set_prop, destroy};
