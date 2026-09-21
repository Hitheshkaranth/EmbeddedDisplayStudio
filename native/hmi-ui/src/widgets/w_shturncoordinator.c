// widgets/w_shturncoordinator.c -- kit widget ShTurnCoordinator (Avionics, "Turn Coordinator").
//
// Spec: ui/qml/Shadcn/ShTurnCoordinator.qml (wrapper) and
// faces/canvas/TurnCoordinatorFace.qml (canvas painter: half-circle scale, 5 ticks).
// The aircraft symbol (cross) and slip ball are wrapper elements.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define PI 3.14159265358979323846

typedef struct {
    double turnRate, slip, standardRate, slipLimit;
    lv_obj_t *bg, *face, *aircraft, *slipBall;
    lv_obj_t *innerBall;
} state_t;

static double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    hmi_draw_t d = hmi_draw_begin(e);
    (void)w;
    double W = w->width, H = w->height;
    double cx = W / 2, cy = H * 0.43, r = fmin(W * 0.38, H * 0.38);
    lv_color_t line = hmi_colour("efisLine");

    // 1. Half-circle arc from 180° to 360° (upper half in Canvas frame = left to right over top)
    hmi_draw_arc(&d, cx, cy, r, 2, 180, 360, line, LV_OPA_COVER);

    // 2. Five ticks at cx + i*r/2 for i=-2..2, vertical from cy-r to cy-r+8
    for (int i = -2; i <= 2; i++) {
        double x = cx + i * r / 2;
        hmi_draw_line(&d, x, cy - r, x, cy - r + 8, 2, line, LV_OPA_COVER);
    }
}

static void update_aircraft(hmi_widget_t *w)
{
    state_t *st = w->state;
    double rot = clamp(st->turnRate / st->standardRate, -2, 2) * 20;
    lv_obj_set_style_transform_rotation(st->aircraft, (int32_t)lround(rot * 10), 0);
}

static void update_slip_ball(hmi_widget_t *w)
{
    state_t *st = w->state;
    double W = w->width;
    double ratio = clamp(st->slip / st->slipLimit, -1, 1);
    // Ball center x: (parent.width-width)/2 + ratio * (parent.width-width) * 0.42
    // The slip ball container width is 0.56*W, inner ball is 12px
    double inner_x = (W * 0.56 - 12) / 2 + ratio * (W * 0.56 - 12) * 0.42;
    lv_obj_set_pos(st->innerBall, (int32_t)lround(inner_x), 2);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->turnRate = hmi_widget_num(w, "turnRate", 0);
    st->slip = hmi_widget_num(w, "slip", 0);
    st->standardRate = hmi_widget_num(w, "standardRate", 3);
    st->slipLimit = hmi_widget_num(w, "slipLimit", 1);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    // Background
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_bg_color(bg, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(bg, hmi_radius("radiusSm"), 0);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    // Face canvas (drawn by callback)
    lv_obj_t *face = lv_obj_create(bg);
    lv_obj_remove_style_all(face);
    lv_obj_set_size(face, (int32_t)w->width, (int32_t)w->height);
    lv_obj_remove_flag(face, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);

    // Aircraft symbol container: width=0.42*w, height=26, centered horizontally, y = 0.43*h - 13
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    st->face = face;

    lv_obj_t *acContainer = lv_obj_create(bg);
    lv_obj_remove_style_all(acContainer);
    lv_obj_set_size(acContainer, (int32_t)(w->width * 0.42), 26);
    lv_obj_align(acContainer, LV_ALIGN_CENTER, 0, (int32_t)lround(w->height * 0.43) - 13 - 13);
    lv_obj_remove_flag(acContainer, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(acContainer, LV_OPA_TRANSP, 0);

    // Horizontal bar
    lv_obj_t *hBar = lv_obj_create(acContainer);
    lv_obj_remove_style_all(hBar);
    lv_obj_set_size(hBar, LV_PCT(100), 3);
    lv_obj_set_style_bg_color(hBar, hmi_colour("efisAircraft"), 0);
    lv_obj_set_style_bg_opa(hBar, LV_OPA_COVER, 0);
    lv_obj_center(hBar);

    // Vertical bar
    lv_obj_t *vBar = lv_obj_create(acContainer);
    lv_obj_remove_style_all(vBar);
    lv_obj_set_size(vBar, 3, 16);
    lv_obj_set_style_bg_color(vBar, hmi_colour("efisAircraft"), 0);
    lv_obj_set_style_bg_opa(vBar, LV_OPA_COVER, 0);
    lv_obj_center(vBar);

    st->aircraft = acContainer;

    // Slip ball container: 0.56*w, 16, centered horizontally, anchored to bottom with 8px margin
    lv_obj_t *ballContainer = lv_obj_create(bg);
    lv_obj_remove_style_all(ballContainer);
    lv_obj_set_size(ballContainer, (int32_t)(w->width * 0.56), 16);
    lv_obj_align_to(ballContainer, bg, LV_ALIGN_BOTTOM_MID, 0, -8);
    lv_obj_remove_flag(ballContainer, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(ballContainer, hmi_colour_hex("transparent", NULL), 0);
    lv_obj_set_style_bg_opa(ballContainer, LV_OPA_TRANSP, 0);
    lv_obj_set_style_radius(ballContainer, 8, 0);
    lv_obj_set_style_border_color(ballContainer, hmi_colour("efisLine"), 0);
    lv_obj_set_style_border_width(ballContainer, 1, 0);

    // Inner ball: 12x12 radius 6
    lv_obj_t *innerBall = lv_obj_create(ballContainer);
    lv_obj_remove_style_all(innerBall);
    lv_obj_set_size(innerBall, 12, 12);
    lv_obj_set_style_radius(innerBall, 6, 0);
    lv_obj_set_style_bg_color(innerBall, hmi_colour("efisLine"), 0);
    lv_obj_set_style_bg_opa(innerBall, LV_OPA_COVER, 0);

    st->slipBall = ballContainer;
    st->innerBall = innerBall;

    read_model(w);
    update_aircraft(w);
    update_slip_ball(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "turnRate") == 0) { st->turnRate = hmi_value_as_num(value, st->turnRate); update_aircraft(w); }
    else if (strcmp(prop, "slip") == 0) { st->slip = hmi_value_as_num(value, st->slip); update_slip_ball(w); }
    else if (strcmp(prop, "standardRate") == 0) st->standardRate = hmi_value_as_num(value, st->standardRate);
    else if (strcmp(prop, "slipLimit") == 0) st->slipLimit = hmi_value_as_num(value, st->slipLimit);
    else return;
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shturncoordinator = {"ShTurnCoordinator", create, set_prop, destroy};