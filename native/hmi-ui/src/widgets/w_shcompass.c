// widgets/w_shcompass.c -- kit widget ShCompass (Avionics, "Heading Compass").
// Minimal first-pass implementation.
#include <string.h>

#include "draw_util.h"
#include "registry.h"

#define PI 3.14159265358979323846

typedef struct {
    double heading, headingBug, course;
    lv_obj_t *bg, *card, *courseNeedle, *headingBugRect;
    lv_obj_t *labels[12];
} state_t;

static void draw_card_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;
    double cx = W / 2, cy = H / 2, r = fmin(W, H) / 2.0 - 4;
    double heading = st->heading;
    lv_color_t line = hmi_colour("efisLine");

    for (int deg = 0; deg < 360; deg += 5) {
        bool major = (deg % 30 == 0);
        double a = (deg - heading - 90) * PI / 180;
        double inner = r - (major ? 14 : 7);
        hmi_draw_line(&d, cx + cos(a) * r, cy + sin(a) * r,
                       cx + cos(a) * inner, cy + sin(a) * inner, major ? 2 : 1, line, LV_OPA_COVER);
    }
    // Course needle: 3 px, 0.62 h long, through the centre, rotating with the card.
    if (st->course >= 0) {
        double a = (st->course - heading - 90) * PI / 180, half = H * 0.31;
        hmi_draw_line(&d, cx - cos(a) * half, cy - sin(a) * half, cx + cos(a) * half, cy + sin(a) * half,
                      3, hmi_colour("efisNav"), LV_OPA_COVER);
    }
    // Heading bug: a 14 x 10 block at the rim (its centre 7 px in from the top edge).
    if (st->headingBug >= 0) {
        double a = (st->headingBug - heading - 90) * PI / 180, rb = H / 2 - 7;
        double bx = cx + cos(a) * rb, by = cy + sin(a) * rb;
        double tx = -sin(a) * 7, ty = cos(a) * 7;   // tangent, half the bug's 14 px width
        hmi_draw_line(&d, bx - tx, by - ty, bx + tx, by + ty, 10, hmi_colour("efisBug"), LV_OPA_COVER);
    }
}

static void update_needles(hmi_widget_t *w)
{
    // The card's labels follow the heading (the glyphs stay upright: LVGL
    // cannot rotate text; the QML rotates each label to the tangent).
    state_t *st = w->state;
    double cx = w->width / 2, cy = w->height / 2, r = fmin(w->width, w->height) / 2.0 - 28;
    for (int i = 0; i < 12; i++) {
        double a = (i * 30 - st->heading - 90) * PI / 180;
        lv_obj_update_layout(st->labels[i]);
        int lw = lv_obj_get_width(st->labels[i]), lh = lv_obj_get_height(st->labels[i]);
        lv_obj_set_pos(st->labels[i], (int32_t)lround(cx + cos(a) * r - lw / 2.0), (int32_t)lround(cy + sin(a) * r - lh / 2.0));
    }
    lv_obj_add_flag(st->courseNeedle, LV_OBJ_FLAG_HIDDEN);     // drawn in the callback
    lv_obj_add_flag(st->headingBugRect, LV_OBJ_FLAG_HIDDEN);
}

static void read_model(hmi_widget_t *w)
{
    state_t *st = w->state;
    st->heading = hmi_widget_num(w, "heading", 0);
    st->headingBug = hmi_widget_num(w, "headingBug", -1);
    st->course = hmi_widget_num(w, "course", -1);
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *bg = lv_obj_create(parent);
    lv_obj_remove_style_all(bg);
    lv_obj_set_size(bg, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_bg_color(bg, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(bg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(bg, hmi_colour("border"), 0);
    lv_obj_set_style_border_width(bg, 1, 0);
    lv_obj_set_style_radius(bg, (int32_t)w->width / 2, 0);
    lv_obj_remove_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *card = lv_obj_create(bg);
    lv_obj_remove_style_all(card);
    lv_obj_set_size(card, (int32_t)w->width, (int32_t)w->height);
    lv_obj_align(card, LV_ALIGN_CENTER, 0, 0);
    lv_obj_remove_flag(card, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_opa(card, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(card, 0, 0);

    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->bg = bg;
    st->card = card;

    // Card draw callback (on bg so it always fires, MAIN = before children)
    lv_obj_add_event_cb(bg, draw_card_cb, LV_EVENT_DRAW_MAIN, w);

    // Course needle
    lv_obj_t *courseNeedle = lv_obj_create(bg);
    lv_obj_remove_style_all(courseNeedle);
    lv_obj_set_size(courseNeedle, 3, (int32_t)(w->height * 0.62));
    lv_obj_set_style_bg_color(courseNeedle, hmi_colour("efisNav"), 0);
    lv_obj_set_style_bg_opa(courseNeedle, LV_OPA_COVER, 0);
    lv_obj_center(courseNeedle);
    st->courseNeedle = courseNeedle;

    // Heading bug
    lv_obj_t *bug = lv_obj_create(bg);
    lv_obj_remove_style_all(bug);
    lv_obj_set_size(bug, 14, 10);
    lv_obj_set_style_bg_color(bug, hmi_colour("efisBug"), 0);
    lv_obj_set_style_bg_opa(bug, LV_OPA_COVER, 0);
    lv_obj_set_pos(bug, (int32_t)w->width / 2 - 7, 2);
    lv_obj_add_flag(bug, LV_OBJ_FLAG_HIDDEN);
    st->headingBugRect = bug;

    // Lubbar line
    lv_obj_t *lubber = lv_obj_create(bg);
    lv_obj_remove_style_all(lubber);
    lv_obj_set_size(lubber, 2, 14);
    lv_obj_set_style_bg_color(lubber, hmi_colour("efisAircraft"), 0);
    lv_obj_set_style_bg_opa(lubber, LV_OPA_COVER, 0);
    lv_obj_align(lubber, LV_ALIGN_TOP_MID, 0, 0);

    // Compass labels (children of card so they rotate with it)
    double cx = w->width / 2, cy = w->height / 2, r = fmin(w->width, w->height) / 2.0 - 28;
    const char *names[] = {"N", "3", "6", "E", "12", "15", "S", "21", "24", "W", "30", "33"};
    for (int i = 0; i < 12; i++) {
        double angle = (i * 30 - 90) * PI / 180;
        int16_t lx = (int16_t)lround(cx + cos(angle) * r);
        int16_t ly = (int16_t)lround(cy + sin(angle) * r);
        (void)lx; (void)ly;
        st->labels[i] = hmi_make_label(bg, 13, 400, hmi_colour("efisText"), names[i]);
    }

    read_model(w);
    update_needles(w);
    return bg;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;
    if (strcmp(prop, "heading") == 0) st->heading = hmi_value_as_num(value, st->heading);
    else if (strcmp(prop, "headingBug") == 0) st->headingBug = hmi_value_as_num(value, st->headingBug);
    else if (strcmp(prop, "course") == 0) st->course = hmi_value_as_num(value, st->course);
    else return;
    update_needles(w);
    lv_obj_invalidate(st->bg);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shcompass = {"ShCompass", create, set_prop, destroy};