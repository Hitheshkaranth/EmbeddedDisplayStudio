// widgets/w_shstatuscard.c -- kit widget ShStatusCard (Rail, "Status Card").
//
// Spec: ui/qml/Shadcn/ShStatusCard.qml -- the cab display's subsystem card
// (HVAC, PA SYSTEM, PEA ...). A rounded dark card (#26262c, 1 px #3a3a44,
// radius 16 at 240x180); the icon (44 px, iconColor) top-left; a glowing
// state dot (r 7) top-right; at the bottom the title (24 px medium, white,
// up to two lines -- the second line smaller and muted) and under it the
// status (28 px bold) coloured by state. Everything scales with
// s = min(W/240, H/180); text shrinks to fit (down to 60 %) and then elides.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "icons.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *frame, *icon, *halo, *dot, *title1, *title2, *status;
    char icon_name[64];
    char title[160];
    char status_text[160];
    char state[16];
    char icon_colour[32];
} state_t;

static lv_color_t state_dot(const char *state)
{
    if (strcmp(state, "warn") == 0) return lv_color_hex(0xf59e0b);
    if (strcmp(state, "fault") == 0) return lv_color_hex(0xef4444);
    if (strcmp(state, "idle") == 0) return lv_color_hex(0x52525b);
    return lv_color_hex(0x4ade80);
}

static lv_color_t state_text(const char *state)
{
    if (strcmp(state, "idle") == 0) return lv_color_hex(0xa1a1aa);
    return state_dot(state);
}

// The largest size <= px (down to 60 %, at least 8) at which `text` fits
// `width`; the label elides with dots past that.
static int fit_px(const char *text, int px, int weight, int width)
{
    int floor_px = (int)fmax(8, round(px * 0.6));
    for (int p = px; p > floor_px; --p) {
        if (lv_text_get_width(text, (uint32_t)strlen(text), hmi_font(p, weight), 0) <= width) return p;
    }
    return floor_px;
}

// Baseline offset from a line's top (LVGL: line height minus base_line).
static int ascent(const lv_font_t *f) { return lv_font_get_line_height(f) - f->base_line; }

// One line in the slot [top, top + line height at the nominal px]: the text
// shrinks to fit `width` (then elides) and keeps the nominal baseline.
static void place_text(lv_obj_t *label, const char *text, int px, int weight, int width, int x, int top,
                       lv_color_t colour)
{
    int p = fit_px(text, px, weight, width);
    const lv_font_t *f = hmi_font(p, weight);
    lv_obj_set_style_text_font(label, f, 0);
    lv_obj_set_style_text_color(label, colour, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
    lv_label_set_text(label, text);
    lv_obj_set_size(label, width, lv_font_get_line_height(f));
    lv_obj_set_pos(label, x, top + ascent(hmi_font(px, weight)) - ascent(f));
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double s = fmin(W / 240.0, H / 180.0);
    int pad = hmi_px_min(20 * s, 4);
    int textW = (int)fmax(10, W - 2 * pad);

    lv_obj_set_size(st->face, (int32_t)W, (int32_t)H);
    lv_obj_set_style_radius(st->face, hmi_px(16 * s), 0);
    lv_obj_set_size(st->frame, (int32_t)W, (int32_t)H);
    lv_obj_set_style_radius(st->frame, hmi_px(16 * s), 0);

    // icon, top-left
    int iconSz = hmi_px_min(44 * s, 8);
    lv_color_t ic = hmi_colour_hex(st->icon_colour[0] == '#' ? st->icon_colour : "#38bdf8", NULL);
    hmi_icon_set(st->icon, st->icon_name, iconSz, ic);
    lv_obj_set_pos(st->icon, pad, hmi_px(18 * s));

    // state dot with its glow, top-right
    lv_color_t dc = state_dot(st->state);
    double r = fmax(2, 7 * s), hr = r * 1.9;
    double cx = W - pad - r, cy = 18 * s + iconSz / 2.0 - 8 * s;
    if (cy < pad * 0.5 + hr) cy = pad * 0.5 + hr;
    lv_obj_set_size(st->halo, hmi_px(2 * hr), hmi_px(2 * hr));
    lv_obj_set_pos(st->halo, hmi_px(cx - hr), hmi_px(cy - hr));
    lv_obj_set_style_bg_color(st->halo, dc, 0);
    lv_obj_set_size(st->dot, hmi_px(2 * r), hmi_px(2 * r));
    lv_obj_set_pos(st->dot, hmi_px(cx - r), hmi_px(cy - r));
    lv_obj_set_style_bg_color(st->dot, dc, 0);

    // status, bottom
    int statusPx = hmi_px_min(28 * s, 8);
    int statusH = lv_font_get_line_height(hmi_font(statusPx, 700));
    int statusY = (int)H - pad - statusH + hmi_px(2 * s);
    place_text(st->status, st->status_text, statusPx, 700, textW, pad, statusY, state_text(st->state));

    // title above it: one or two lines
    char line1[160], line2[160];
    line2[0] = '\0';
    snprintf(line1, sizeof line1, "%s", st->title);
    char *nl = strchr(line1, '\n');
    if (nl) {
        *nl = '\0';
        snprintf(line2, sizeof line2, "%s", nl + 1);
        char *nl2 = strchr(line2, '\n');
        if (nl2) *nl2 = '\0';
    }
    int titlePx = hmi_px_min(24 * s, 8);
    int subPx = hmi_px_min(16 * s, 7);
    int gap = hmi_px(2 * s);
    int y = statusY - gap;
    if (line2[0]) {
        int subH = lv_font_get_line_height(hmi_font(subPx, 500));
        y -= subH;
        place_text(st->title2, line2, subPx, 500, textW, pad, y, lv_color_hex(0xa1a1aa));
        lv_obj_remove_flag(st->title2, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(st->title2, LV_OBJ_FLAG_HIDDEN);
    }
    int titleH = lv_font_get_line_height(hmi_font(titlePx, 500));
    y -= titleH;
    place_text(st->title1, line1, titlePx, 500, textW, pad, y, lv_color_hex(0xfafafa));
}

// "\n" typed into a property field arrives as backslash + n.
static void copy_title(char *dst, size_t n, const char *src)
{
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 1 < n; ++i) {
        if (src[i] == '\\' && src[i + 1] == 'n') { dst[j++] = '\n'; ++i; }
        else dst[j++] = src[i];
    }
    dst[j] = '\0';
}

static lv_obj_t *make_disc(lv_obj_t *parent, lv_opa_t opa)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_radius(o, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(o, opa, 0);
    return o;
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(face, lv_color_hex(0x26262c), 0);
    lv_obj_set_style_bg_opa(face, LV_OPA_COVER, 0);
    lv_obj_set_style_clip_corner(face, false, 0);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    // The 1 px border lives on its own child: on the face itself LVGL would
    // move every child's origin in by the border width.
    st->frame = lv_obj_create(face);
    lv_obj_remove_style_all(st->frame);
    lv_obj_remove_flag(st->frame, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_border_color(st->frame, lv_color_hex(0x3a3a44), 0);
    lv_obj_set_style_border_width(st->frame, 1, 0);
    st->icon = hmi_icon_create(face, "", 16, lv_color_hex(0x38bdf8));
    st->halo = make_disc(face, (lv_opa_t)(0.22 * 255));
    st->dot = make_disc(face, LV_OPA_COVER);
    st->title1 = hmi_make_label(face, 24, 500, lv_color_hex(0xfafafa), "");
    st->title2 = hmi_make_label(face, 16, 500, lv_color_hex(0xa1a1aa), "");
    st->status = hmi_make_label(face, 28, 700, lv_color_hex(0x4ade80), "");

    snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_widget_str(w, "icon", "snowflake"));
    copy_title(st->title, sizeof st->title, hmi_widget_str(w, "title", "HVAC:"));
    snprintf(st->status_text, sizeof st->status_text, "%s", hmi_widget_str(w, "status", "ACTIVE (21\xc2\xb0" "C)"));
    snprintf(st->state, sizeof st->state, "%s", hmi_widget_str(w, "state", "ok"));
    snprintf(st->icon_colour, sizeof st->icon_colour, "%s", hmi_widget_str(w, "iconColor", "#38bdf8"));
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "icon") == 0)
        snprintf(st->icon_name, sizeof st->icon_name, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "title") == 0)
        copy_title(st->title, sizeof st->title, hmi_value_as_str(value, ""));
    else if (strcmp(prop, "status") == 0)
        snprintf(st->status_text, sizeof st->status_text, "%s",
                 value->kind == HMI_V_NUM ? hmi_value_debug(value) : hmi_value_as_str(value, ""));
    else if (strcmp(prop, "state") == 0)
        snprintf(st->state, sizeof st->state, "%s", hmi_value_as_str(value, "ok"));
    else if (strcmp(prop, "iconColor") == 0)
        snprintf(st->icon_colour, sizeof st->icon_colour, "%s", hmi_value_as_str(value, "#38bdf8"));
    else
        return;
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shstatuscard = {"ShStatusCard", create, set_prop, destroy};
