// widgets/w_shflightdirector.c -- kit widget ShFlightDirector (Avionics, "Flight Director").
//
// Spec: ui/qml/Shadcn/ShFlightDirector.qml -- command bars: a horizontal
// pitch bar and a vertical roll bar, hidden when inactive.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct {
    lv_obj_t *face, *modeText, *bgRect;
    double pitchCommand, rollCommand, pitchLimit, rollLimit;
    bool active;
} state_t;

static void draw_cb(lv_event_t *e)
{
    hmi_widget_t *w = lv_event_get_user_data(e);
    state_t *st = w->state;
    hmi_draw_t d = hmi_draw_begin(e);
    double W = w->width, H = w->height;

    if (!st->active) return;

    double _pitch = fmax(-st->pitchLimit, fmin(st->pitchLimit, st->pitchCommand));
    double _roll = fmax(-st->rollLimit, fmin(st->rollLimit, st->rollCommand));

    lv_color_t navCol = hmi_colour("efisNav");

    // Horizontal pitch bar
    double barH = H * 0.035;
    if (barH < 3) barH = 3;
    double barW = W * 0.48;
    double barY = H / 2 - barH / 2 + (_pitch / st->pitchLimit) * H * 0.32;
    hmi_draw_fill(&d, (W - barW) / 2, barY, barW, barH, navCol, LV_OPA_COVER, 0);

    // Vertical roll bar
    double barWv = W * 0.022;
    if (barWv < 3) barWv = 3;
    double barHv = H * 0.58;
    double barX = W / 2 - barWv / 2 + (_roll / st->rollLimit) * W * 0.32;
    hmi_draw_fill(&d, barX, (H - barHv) / 2, barWv, barHv, navCol, LV_OPA_COVER, 0);
}

static void layout(hmi_widget_t *w)
{
    state_t *st = w->state;

    /* Background */
    lv_obj_set_style_bg_color(st->face, hmi_colour("efisPanel"), 0);
    lv_obj_set_style_bg_opa(st->face, LV_OPA_COVER, 0);

    /* Mode text */
    const char *text = st->active ? "FD" : "FD OFF";
    lv_label_set_text(st->modeText, text);
    lv_obj_set_style_text_font(st->modeText, hmi_font(hmi_font_size("fontSizeXs"), 600), 0);
    lv_obj_set_style_text_color(st->modeText, st->active ? hmi_colour("efisNormal") : hmi_colour("mutedForeground"), 0);
    lv_obj_align(st->modeText, LV_ALIGN_TOP_MID, 0, 0);
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

    st->modeText = lv_label_create(face);
    lv_obj_remove_style_all(st->modeText);
    lv_label_set_long_mode(st->modeText, LV_LABEL_LONG_CLIP);

    lv_obj_add_event_cb(face, draw_cb, LV_EVENT_DRAW_MAIN, w);
    lv_obj_add_flag(face, LV_OBJ_FLAG_CLICKABLE);

    st->pitchCommand = hmi_widget_num(w, "pitchCommand", 0);
    st->rollCommand = hmi_widget_num(w, "rollCommand", 0);
    st->pitchLimit = hmi_widget_num(w, "pitchLimit", 15);
    st->rollLimit = hmi_widget_num(w, "rollLimit", 30);
    st->active = hmi_widget_bool(w, "active", true);

    layout(w);
    return face;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "pitchCommand") == 0) st->pitchCommand = hmi_value_as_num(value, st->pitchCommand);
    else if (strcmp(prop, "rollCommand") == 0) st->rollCommand = hmi_value_as_num(value, st->rollCommand);
    else if (strcmp(prop, "pitchLimit") == 0) st->pitchLimit = hmi_value_as_num(value, st->pitchLimit);
    else if (strcmp(prop, "rollLimit") == 0) st->rollLimit = hmi_value_as_num(value, st->rollLimit);
    else if (strcmp(prop, "active") == 0) { st->active = hmi_value_as_bool(value, st->active); }
    else if (strcmp(prop, "mode") == 0) { /* mode text handled by active */ }
    else return;

    layout(w);
    lv_obj_invalidate(st->face);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shflightdirector = {"ShFlightDirector", create, set_prop, destroy};