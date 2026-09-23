// widgets/w_shattitude.c -- kit widget ShAttitude (Aviation, "Attitude Indicator").
//
// Spec: ui/qml/Shadcn/ShAttitude.qml (horizon: an oversized sky/ground
// square rotated by -roll and slid by pitch * pixelsPerDegree, clipped to
// the item; a 2 px horizon line; a pitch ladder at -20..20 in 5-degree
// steps, majors 70 px with numbers, minors 36 px) and
// faces/canvas/AttitudeFace.qml (the fixed bank scale and aircraft symbol).
//
// The horizon is painted scanline by scanline: in the rotated frame the
// horizon is the line y' = -pitchOff where y' = (x-cx) sinR + (y-cy) cosR
// (R = -roll); everything with y' < -pitchOff is sky.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    double pitch, roll, pixelsPerDegree;
    lv_obj_t *face, *numbers[8];
} state_t;

static const double kTicks[8] = {-20, -15, -10, -5, 5, 10, 15, 20};

// Position along the ladder for a pitch value, in widget coordinates.
static void ladder_point(const hmi_widget_t *w, const state_t *st, double tick, double *x, double *y)
{
    double R = -st->roll * M_PI / 180;
    double dy = (st->pitch - tick) * st->pixelsPerDegree;   // the ladder slides with pitch
    *x = w->width / 2 - dy * sin(R);
    *y = w->height / 2 + dy * cos(R);
}

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height, cx = W / 2, cy = H / 2;
    double R = -st->roll * M_PI / 180, sinR = sin(R), cosR = cos(R);
    lv_color_t sky = hmi_colour("efisSky"), ground = hmi_colour("efisGround");
    lv_color_t line = hmi_colour("efisLine"), aircraft = hmi_colour("efisAircraft");

    // 1. sky / ground. The boundary is the horizon line itself -- the same
    // point and direction the ladder and the drawn line use -- so the fill
    // cannot drift away from the line it is supposed to meet. Taking the
    // frame from anywhere else inverted both axes here: a climb showed
    // ground and a right bank dropped the wrong wing, while the line and
    // the ladder over the top of it moved correctly.
    //   y'' = -(x - hx) sinR + (y - hy) cosR, and the sky is y'' < 0.
    double hx, hy;
    ladder_point(w, st, 0, &hx, &hy);
    for (int yi = 0; yi < (int)H; ++yi) {
        double y = yi + 0.5;
        double base = -(cx - hx) * sinR + (y - hy) * cosR;    // y'' at x = cx
        if (fabs(sinR) < 1e-6) {
            hmi_draw_fill(&d, 0, yi, W, 1, base < 0 ? sky : ground, LV_OPA_COVER, 0);
            continue;
        }
        double xh = hx + (y - hy) * cosR / sinR;               // where y'' crosses 0
        bool skyLeft = sinR < 0;                               // y'' falls with x when sinR > 0
        if (xh <= 0) hmi_draw_fill(&d, 0, yi, W, 1, skyLeft ? ground : sky, LV_OPA_COVER, 0);
        else if (xh >= W) hmi_draw_fill(&d, 0, yi, W, 1, skyLeft ? sky : ground, LV_OPA_COVER, 0);
        else {
            hmi_draw_fill(&d, 0, yi, xh, 1, skyLeft ? sky : ground, LV_OPA_COVER, 0);
            hmi_draw_fill(&d, xh, yi, W - xh, 1, skyLeft ? ground : sky, LV_OPA_COVER, 0);
        }
    }
    // 2. horizon line (2 px) through the ladder's zero, along the roll direction
    {
        double hx, hy;
        ladder_point(w, st, 0, &hx, &hy);
        double len = fmax(W, H) * 1.5;
        hmi_draw_line(&d, hx - cosR * len, hy - sinR * len, hx + cosR * len, hy + sinR * len, 2, line, LV_OPA_COVER);
    }
    // 3. pitch ladder
    for (int i = 0; i < 8; ++i) {
        double tx, ty;
        ladder_point(w, st, kTicks[i], &tx, &ty);
        double half = ((int)kTicks[i] % 10 == 0 ? 70 : 36) / 2.0;
        hmi_draw_line(&d, tx - cosR * half, ty - sinR * half, tx + cosR * half, ty + sinR * half, 2, line, LV_OPA_COVER);
    }
    // 4. bank scale, fixed to the case
    double r = fmin(W, H) * 0.44;
    static const int marks[11] = {-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60};
    for (int i = 0; i < 11; ++i) {
        double a = (marks[i] - 90) * M_PI / 180;
        double inner = marks[i] % 30 == 0 ? r - 12 : r - 7;
        hmi_draw_line(&d, cx + cos(a) * r, cy + sin(a) * r, cx + cos(a) * inner, cy + sin(a) * inner, 2, line, LV_OPA_COVER);
    }
    // 5. aircraft symbol
    hmi_draw_line(&d, cx - 46, cy, cx - 16, cy, 3, aircraft, LV_OPA_COVER);
    hmi_draw_line(&d, cx + 16, cy, cx + 46, cy, 3, aircraft, LV_OPA_COVER);
    hmi_draw_disc(&d, cx, cy, 3, aircraft, LV_OPA_COVER);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;
    double R = -st->roll * M_PI / 180, sinR = sin(R), cosR = cos(R);
    for (int i = 0; i < 8; ++i) {
        lv_obj_t *l = st->numbers[i];
        if ((int)kTicks[i] % 10 != 0) { lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN); continue; }
        lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text_fmt(l, "%d", (int)fabs(kTicks[i]));
        lv_obj_update_layout(l);
        double tx, ty;
        ladder_point(w, st, kTicks[i], &tx, &ty);
        // the number sits 42 px left of the rung's centre (anchors.right: horizontalCenter, margin 42)
        double nx = tx - cosR * 42, ny = ty - sinR * 42;
        lv_obj_set_pos(l, (int32_t)lround(nx - lv_obj_get_width(l)), (int32_t)lround(ny - lv_obj_get_height(l) / 2.0));
    }
    lv_obj_invalidate(st->face);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->pitch = hmi_widget_num(w, "pitch", 0);
    st->roll = hmi_widget_num(w, "roll", 0);
    st->pixelsPerDegree = hmi_widget_num(w, "pixelsPerDegree", 4);
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
    for (int i = 0; i < 8; ++i)
        st->numbers[i] = hmi_make_label(face, hmi_font_size("fontSizeXs"), 400, hmi_colour("efisText"), "");
    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    read_model(w);
    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "pitch") == 0) st->pitch = hmi_value_as_num(value, st->pitch);
    else if (strcmp(prop, "roll") == 0) st->roll = hmi_value_as_num(value, st->roll);
    else if (strcmp(prop, "pixelsPerDegree") == 0) st->pixelsPerDegree = hmi_value_as_num(value, st->pixelsPerDegree);
    else return;
    layout(w);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shattitude = {"ShAttitude", create, set_prop, destroy};
