// widgets/w_shvehiclestatus.c -- kit widget ShVehicleStatus (Automotive, "Vehicle Status").
//
// Spec: ui/qml/Shadcn/faces/canvas/VehicleStatusFace.qml (wheels, body,
// window lines) and ShVehicleStatus.qml (corner readouts, unit, label).
// Geometry from the wrapper: body 0.42 w x 0.7 h centred, radius
// min(0.16 w, bodyW/2, bodyH/2), wheels 0.09 w x 0.14 h.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double fl, fr, rl, rr, warnBelow;
    int decimals;
    lv_obj_t *face, *readouts[4], *unit, *label;
} state_t;

static bool low(const state_t *st, double v) { return st->warnBelow > 0 && v < st->warnBelow; }

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double bw = W * 0.42, bh = H * 0.7, bx = (W - bw) / 2, by = (H - bh) / 2;
    double r = fmin(W * 0.16, fmin(bw / 2, bh / 2));
    double ww = W * 0.09, wh = H * 0.14;
    lv_color_t wheel = hmi_colour_hex("#c9d3df", NULL), wheelLow = hmi_colour("autoAmber");
    lv_color_t bodyFill = hmi_colour("autoAccentDeep"), bodyLine = hmi_colour("autoAccent");
    // Wheels first (the body's edge sits over them).
    struct { double x, y, v; } wheels[4] = {
        {bx - ww * 0.6, by + bh * 0.12, st->fl}, {bx + bw - ww * 0.4, by + bh * 0.12, st->fr},
        {bx - ww * 0.6, by + bh * 0.88 - wh, st->rl}, {bx + bw - ww * 0.4, by + bh * 0.88 - wh, st->rr}};
    for (int i = 0; i < 4; ++i)
        hmi_draw_fill(&d, wheels[i].x, wheels[i].y, ww, wh, low(st, wheels[i].v) ? wheelLow : wheel,
                      low(st, wheels[i].v) ? LV_OPA_COVER : (lv_opa_t)(0.7 * 255), (int)lround(ww * 0.3));
    // Body: fill at 25 %, 1.5 px stroke.
    lv_draw_rect_dsc_t rd;
    lv_draw_rect_dsc_init(&rd);
    rd.bg_color = bodyFill; rd.bg_opa = (lv_opa_t)(0.25 * 255);
    rd.border_color = bodyLine; rd.border_opa = LV_OPA_COVER; rd.border_width = 2;
    rd.radius = (int32_t)lround(r);
    lv_area_t a = {(int32_t)lround(d.coords.x1 + bx), (int32_t)lround(d.coords.y1 + by),
                   (int32_t)lround(d.coords.x1 + bx + bw) - 1, (int32_t)lround(d.coords.y1 + by + bh) - 1};
    lv_draw_rect(d.layer, &rd, &a);
    // Windscreen and rear window at 60 % accent.
    double inset = bw * 0.12;
    lv_color_t glass = hmi_colour("autoAccent");
    hmi_draw_line(&d, bx + inset, by + bh * 0.28, bx + bw - inset, by + bh * 0.28, 1.2, glass, (lv_opa_t)(0.6 * 255));
    hmi_draw_line(&d, bx + inset, by + bh * 0.72, bx + bw - inset, by + bh * 0.72, 1.2, glass, (lv_opa_t)(0.6 * 255));
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = fmax(1, w->width), H = fmax(1, w->height);
    double bw = W * 0.42, bh = H * 0.7, bx = (W - bw) / 2, by = (H - bh) / 2, ww = W * 0.09;
    double vals[4] = {st->fl, st->fr, st->rl, st->rr};
    int fs = hmi_px_min(H * 0.12, 7);
    for (int i = 0; i < 4; ++i) {
        lv_obj_t *l = st->readouts[i];
        lv_label_set_text_fmt(l, "%.*f", st->decimals, vals[i]);
        lv_obj_set_style_text_font(l, hmi_font(fs, 600), 0);
        lv_obj_set_style_text_color(l, low(st, vals[i]) ? hmi_colour("autoRed") : hmi_colour("autoText"), 0);
        lv_obj_update_layout(l);
        int lw = lv_obj_get_width(l), lh = lv_obj_get_height(l);
        bool right = i % 2 == 1, bottom = i >= 2;
        int x = right ? (int)lround(bx + bw + ww + 2) : (int)lround(bx - ww - lw - 2);
        int y = bottom ? (int)lround(by + bh - H * 0.06 - lh) : (int)lround(by + H * 0.06);
        lv_obj_set_pos(l, x, y);
    }
    int sfs = hmi_px_min(H * 0.08, 7);
    lv_label_set_text(st->unit, hmi_widget_str(w, "unit", ""));
    lv_obj_set_style_text_font(st->unit, hmi_font(sfs, 400), 0);
    lv_obj_align(st->unit, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_label_set_text(st->label, hmi_widget_str(w, "label", ""));
    lv_obj_set_style_text_font(st->label, hmi_font(sfs, 400), 0);
    lv_obj_align(st->label, LV_ALIGN_TOP_MID, 0, 0);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->fl = hmi_widget_num(w, "frontLeft", 2.6); st->fr = hmi_widget_num(w, "frontRight", 2.5);
    st->rl = hmi_widget_num(w, "rearLeft", 1.6); st->rr = hmi_widget_num(w, "rearRight", 2.2);
    st->warnBelow = hmi_widget_num(w, "warnBelow", 1.8);
    st->decimals = (int)hmi_widget_num(w, "decimals", 1);
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
    for (int i = 0; i < 4; ++i) st->readouts[i] = hmi_make_label(face, 12, 600, hmi_colour("autoText"), "");
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
    else if (strcmp(prop, "warnBelow") == 0) st->warnBelow = hmi_value_as_num(value, st->warnBelow);
    else if (strcmp(prop, "decimals") == 0) st->decimals = (int)hmi_value_as_num(value, st->decimals);
    else if (strcmp(prop, "unit") == 0) { lv_label_set_text(st->unit, hmi_value_as_str(value, "")); return; }
    else if (strcmp(prop, "label") == 0) { lv_label_set_text(st->label, hmi_value_as_str(value, "")); return; }
    else return;
    layout(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shvehiclestatus = {"ShVehicleStatus", create, set_prop, destroy};
