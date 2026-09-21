// widgets/w_shstatdot.c -- kit widget ShStatDot (Industrial, "Status Indicator").
// Spec: ui/qml/Shadcn/ShStatDot.qml: a disc filling the item, coloured by
// `state` (ok success / warn warning / fault destructive / else
// mutedForeground). The fault blink is not reproduced in wave 1.
#include <stdio.h>
#include <string.h>

#include "draw_util.h"
#include "registry.h"

typedef struct { char state[16]; lv_obj_t *dot; } state_t;

static lv_color_t colour_for(const char *s)
{
    if (strcmp(s, "ok") == 0) return hmi_colour("success");
    if (strcmp(s, "warn") == 0) return hmi_colour("warning");
    if (strcmp(s, "fault") == 0) return hmi_colour("destructive");
    return hmi_colour("mutedForeground");
}

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    lv_obj_t *dot = lv_obj_create(parent);
    lv_obj_remove_style_all(dot);
    lv_obj_set_size(dot, (int32_t)w->width, (int32_t)w->height);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    state_t *st = lv_malloc_zeroed(sizeof *st);
    w->state = st;
    st->dot = dot;
    snprintf(st->state, sizeof st->state, "%s", hmi_widget_str(w, "state", "idle"));
    lv_obj_set_style_bg_color(dot, colour_for(st->state), 0);
    return dot;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    state_t *st = w->state;
    if (!st || strcmp(prop, "state") != 0) return;
    snprintf(st->state, sizeof st->state, "%s", hmi_value_as_str(value, st->state));
    lv_obj_set_style_bg_color(st->dot, colour_for(st->state), 0);
}

static void destroy(hmi_widget_t *w) { lv_free(w->state); }

const hmi_widget_ops_t hmi_widget_shstatdot = {"ShStatDot", create, set_prop, destroy};
