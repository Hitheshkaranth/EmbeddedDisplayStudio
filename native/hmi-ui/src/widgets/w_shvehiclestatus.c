// widgets/w_shvehiclestatus.c -- kit widget ShVehicleStatus (Automotive, "Vehicle Status").
//
// Spec: ui/qml/Shadcn/faces/canvas/VehicleStatusFace.qml (wheels, body,
// window lines) and ShVehicleStatus.qml (corner readouts, unit, label).
// Geometry from the wrapper: body 0.42 w x 0.7 h centred, radius
// min(0.16 w, bodyW/2, bodyH/2), wheels 0.09 w x 0.14 h.
// axles 3 (a haul truck): body 0.34 w x 0.74 h, radius min(0.05 w, ...),
// wheels 0.06 w x 0.15 h, a middle pair at half the body's height; tyres
// autoGreen at 18 % with a 1.5 px autoGreen outline (amber when low), body
// autoMuted; each reading green over its unit, centred in the column
// between the widget's edge and the tyre, and no shared unit at the foot.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double fl, fr, rl, rr, ml, mr, warnBelow;
    int decimals, axles;
    char unit_text[32];
    lv_obj_t *face, *readouts[6], *units[6], *unit, *label;
} state_t;

typedef struct {
    double bw, bh, bx, by, r, ww, wh;
} geom_t;

static bool low(const state_t *st, double v) { return st->warnBelow > 0 && v < st->warnBelow; }
static bool truck(const state_t *st) { return st->axles >= 3; }

static geom_t geometry(const hmi_widget_t *w)
{
    const state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    geom_t g;
    bool t = truck(st);
    g.bw = W * (t ? 0.34 : 0.42);
    g.bh = H * (t ? 0.74 : 0.7);
    g.bx = (W - g.bw) / 2;
    g.by = (H - g.bh) / 2;
    g.r = fmin(W * (t ? 0.05 : 0.16), fmin(g.bw / 2, g.bh / 2));
    g.ww = W * (t ? 0.06 : 0.09);
    g.wh = H * (t ? 0.15 : 0.14);
    return g;
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    geom_t g = geometry(w);
    double bw = g.bw, bh = g.bh, bx = g.bx, by = g.by, ww = g.ww, wh = g.wh;
    bool t = truck(st);
    lv_color_t wheel = t ? hmi_colour("autoGreen") : hmi_colour_hex("#c9d3df", NULL);
    lv_opa_t wheelOpa = (lv_opa_t)((t ? 0.18 : 0.7) * 255);
    lv_color_t wheelLow = hmi_colour("autoAmber");
    lv_color_t bodyFill = t ? hmi_colour("autoMuted") : hmi_colour("autoAccentDeep");
    lv_color_t bodyLine = t ? hmi_colour("autoMuted") : hmi_colour("autoAccent");
    // Wheels first (the body's edge sits over them).
    struct { double x, y, v; } wheels[6] = {
        {bx - ww * 0.6, by + bh * 0.12, st->fl}, {bx + bw - ww * 0.4, by + bh * 0.12, st->fr},
        {bx - ww * 0.6, by + bh * 0.88 - wh, st->rl}, {bx + bw - ww * 0.4, by + bh * 0.88 - wh, st->rr},
        {bx - ww * 0.6, by + bh * 0.5 - wh / 2, st->ml}, {bx + bw - ww * 0.4, by + bh * 0.5 - wh / 2, st->mr}};
    int n = t ? 6 : 4;
    for (int i = 0; i < n; ++i) {
        bool l = low(st, wheels[i].v);
        int radius = (int)lround(ww * 0.3);
        if (!t) {
            hmi_draw_fill(&d, wheels[i].x, wheels[i].y, ww, wh, l ? wheelLow : wheel,
                          l ? LV_OPA_COVER : wheelOpa, radius);
            continue;
        }
        lv_draw_rect_dsc_t td;
        lv_draw_rect_dsc_init(&td);
        td.bg_color = l ? wheelLow : wheel;
        td.bg_opa = l ? LV_OPA_COVER : wheelOpa;
        td.border_color = l ? wheelLow : wheel;
        td.border_opa = LV_OPA_COVER;
        td.border_width = 2;
        td.radius = radius;
        lv_area_t ta = {(int32_t)lround(d.coords.x1 + wheels[i].x), (int32_t)lround(d.coords.y1 + wheels[i].y),
                        (int32_t)lround(d.coords.x1 + wheels[i].x + ww) - 1,
                        (int32_t)lround(d.coords.y1 + wheels[i].y + wh) - 1};
        lv_draw_rect(d.layer, &td, &ta);
    }
    // Body: fill at 25 % (15 % for the truck), 1.5 px stroke.
    lv_draw_rect_dsc_t rd;
    lv_draw_rect_dsc_init(&rd);
    rd.bg_color = bodyFill; rd.bg_opa = (lv_opa_t)((t ? 0.15 : 0.25) * 255);
    rd.border_color = bodyLine; rd.border_opa = LV_OPA_COVER; rd.border_width = 2;
    rd.radius = (int32_t)lround(g.r);
    lv_area_t a = {(int32_t)lround(d.coords.x1 + bx), (int32_t)lround(d.coords.y1 + by),
                   (int32_t)lround(d.coords.x1 + bx + bw) - 1, (int32_t)lround(d.coords.y1 + by + bh) - 1};
    lv_draw_rect(d.layer, &rd, &a);
    // Windscreen and rear window at 60 % accent (muted for the truck).
    double inset = bw * 0.12;
    lv_color_t glass = t ? hmi_colour("autoMuted") : hmi_colour("autoAccent");
    hmi_draw_line(&d, bx + inset, by + bh * 0.28, bx + bw - inset, by + bh * 0.28, 1.2, glass, (lv_opa_t)(0.6 * 255));
    hmi_draw_line(&d, bx + inset, by + bh * 0.72, bx + bw - inset, by + bh * 0.72, 1.2, glass, (lv_opa_t)(0.6 * 255));
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    geom_t g = geometry(w);
    double bw = g.bw, bh = g.bh, bx = g.bx, by = g.by, ww = g.ww, wh = g.wh;
    // frontLeft, frontRight, rearLeft, rearRight, midLeft, midRight
    double vals[6] = {st->fl, st->fr, st->rl, st->rr, st->ml, st->mr};
    if (!truck(st)) {
        int fs = hmi_px_min(H * 0.12, 7);
        for (int i = 0; i < 4; ++i) {
            lv_obj_t *l = st->readouts[i];
            lv_label_set_text_fmt(l, "%.*f", st->decimals, vals[i]);
            lv_obj_set_style_text_font(l, hmi_font(fs, 600), 0);
            lv_obj_set_style_text_color(l, low(st, vals[i]) ? hmi_colour("autoRed") : hmi_colour("autoText"), 0);
            lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
            lv_obj_update_layout(l);
            int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
            bool right = i % 2 == 1, bottom = i >= 2;
            int x = right ? (int)lround(bx + bw + ww + 2) : (int)lround(bx - ww - lw - 2);
            int y = bottom ? (int)lround(by + bh - H * 0.06 - lh) : (int)lround(by + H * 0.06);
            lv_obj_set_pos(l, x, y);
        }
        for (int i = 0; i < 6; ++i) lv_obj_add_flag(st->units[i], LV_OBJ_FLAG_HIDDEN);
        for (int i = 4; i < 6; ++i) lv_obj_add_flag(st->readouts[i], LV_OBJ_FLAG_HIDDEN);
    } else {
        double colW = bx - ww * 0.6;
        int fs = hmi_px_min(fmin(H * 0.11, colW * 0.38), 7);
        int ufs = hmi_px_min(H * 0.06, 7);
        for (int i = 0; i < 6; ++i) {
            bool right = i % 2 == 1;
            int row = i < 2 ? 0 : i < 4 ? 2 : 1;   // the value order above
            double cy = row == 0 ? by + bh * 0.12 + wh / 2 : row == 1 ? by + bh * 0.5 : by + bh * 0.88 - wh / 2;
            double cx = right ? W - colW / 2 : colW / 2;
            lv_obj_t *l = st->readouts[i], *u = st->units[i];
            lv_label_set_text_fmt(l, "%.*f", st->decimals, vals[i]);
            lv_obj_set_style_text_font(l, hmi_font(fs, 600), 0);
            lv_obj_set_style_text_color(l, low(st, vals[i]) ? hmi_colour("autoRed") : hmi_colour("autoGreen"), 0);
            lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(u, st->unit_text);
            lv_obj_set_style_text_font(u, hmi_font(ufs, 400), 0);
            if (st->unit_text[0]) lv_obj_remove_flag(u, LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(u, LV_OBJ_FLAG_HIDDEN);
            lv_obj_update_layout(l);
            lv_obj_update_layout(u);
            int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
            int uw = lv_obj_get_width(u), uh = st->unit_text[0] ? lv_obj_get_height(u) : 0;
            int top = (int)lround(cy - (lh + uh) / 2.0);
            lv_obj_set_pos(l, (int)lround(cx - lw / 2.0), top);
            lv_obj_set_pos(u, (int)lround(cx - uw / 2.0), top + lh);
        }
    }
    int sfs = hmi_px_min(H * 0.08, 7);
    lv_label_set_text(st->unit, st->unit_text);
    lv_obj_set_style_text_font(st->unit, hmi_font(sfs, 400), 0);
    lv_obj_align(st->unit, LV_ALIGN_BOTTOM_MID, 0, 0);
    if (truck(st) || !st->unit_text[0]) lv_obj_add_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(st->unit, LV_OBJ_FLAG_HIDDEN);
    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));
    lv_obj_set_style_text_font(st->label, hmi_font(sfs, 400), 0);
    lv_obj_align(st->label, LV_ALIGN_TOP_MID, 0, 0);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->fl = hmi_widget_num(w, "frontLeft", 2.6); st->fr = hmi_widget_num(w, "frontRight", 2.5);
    st->rl = hmi_widget_num(w, "rearLeft", 1.6); st->rr = hmi_widget_num(w, "rearRight", 2.2);
    st->ml = hmi_widget_num(w, "midLeft", 2.4); st->mr = hmi_widget_num(w, "midRight", 2.4);
    st->warnBelow = hmi_widget_num(w, "warnBelow", 1.8);
    st->decimals = (int)hmi_widget_num(w, "decimals", 1);
    st->axles = (int)hmi_widget_num(w, "axles", 2);
    snprintf(st->unit_text, sizeof st->unit_text, "%s", hmi_widget_str(w, "unit", ""));
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *face = lv_obj_create(parent);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->face = face;
    for (int i = 0; i < 6; ++i) {
        st->readouts[i] = hmi_make_label(face, 12, 600, hmi_colour("autoText"), "");
        st->units[i] = hmi_make_label(face, 10, 400, hmi_colour("autoMuted"), "");
    }
    st->unit = hmi_make_label(face, 10, 400, hmi_colour("autoMuted"), "");
    st->label = hmi_make_label(face, 10, 400, hmi_colour("autoMuted"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "frontLeft") == 0) st->fl = hmi_value_as_num(value, st->fl);
    else if (strcmp(prop, "frontRight") == 0) st->fr = hmi_value_as_num(value, st->fr);
    else if (strcmp(prop, "rearLeft") == 0) st->rl = hmi_value_as_num(value, st->rl);
    else if (strcmp(prop, "rearRight") == 0) st->rr = hmi_value_as_num(value, st->rr);
    else if (strcmp(prop, "midLeft") == 0) st->ml = hmi_value_as_num(value, st->ml);
    else if (strcmp(prop, "midRight") == 0) st->mr = hmi_value_as_num(value, st->mr);
    else if (strcmp(prop, "axles") == 0) st->axles = (int)hmi_value_as_num(value, st->axles);
    else if (strcmp(prop, "warnBelow") == 0) st->warnBelow = hmi_value_as_num(value, st->warnBelow);
    else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "unit") == 0)
        snprintf(st->unit_text, sizeof st->unit_text, "%s", hmi_value_as_str(value, ""));
    else if (strcmp(prop, "label") == 0) { lv_label_set_text(st->label, hmi_value_as_str(value, "")); return; }
    else return;
    layout(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shvehiclestatus = {"ShVehicleStatus", create, set_prop, destroy};
