// widgets/w_shprogress.c -- kit widget ShProgress (Industrial, "Progress Bar").
//
// Spec: ui/qml/Shadcn/ShProgress.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, indeterminate, opacity, visible.
// Default size 200x24. Signals: none.
// Owner: W3.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *track;
    lv_obj_t *indicator;
} shprogress_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w;
    // Track rectangle
    lv_obj_t *track = lv_obj_create(parent);
    lv_obj_remove_style_all(track);
    lv_obj_set_style_radius(track, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(track, hmi_colour("secondary"), 0);
    lv_obj_set_style_bg_opa(track, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(track, 0, 0);

    // Indicator rectangle
    lv_obj_t *indicator = lv_obj_create(track);
    lv_obj_remove_style_all(indicator);
    lv_obj_set_style_radius(indicator, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(indicator, hmi_colour("primary"), 0);
    lv_obj_set_style_bg_opa(indicator, LV_OPA_COVER, 0);
    lv_obj_set_size(indicator, 0, lv_obj_get_height(track));

    shprogress_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->track = track;
    st->indicator = indicator;

    w->state = st;
    return track;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    shprogress_state_t *st = w->state;
    if (!st) return;

    if (strcmp(prop, "value") == 0) {
        double v = hmi_value_as_num(value, 0);
        v = v < 0 ? 0 : (v > 1 ? 1 : v);
        int track_w = (int)lv_obj_get_width(st->track);
        int new_w = (int)(track_w * v);
        lv_obj_set_size(st->indicator, new_w, lv_obj_get_height(st->indicator));
    } else if (strcmp(prop, "indeterminate") == 0) {
        bool indet = hmi_value_as_bool(value, false);
        (void)indet;
        // Indeterminate mode would need animation; for now just use value=1
        if (indet) {
            lv_obj_set_size(st->indicator, lv_obj_get_width(st->track), lv_obj_get_height(st->indicator));
        }
    }
}

static void destroy(hmi_widget_t *w)
{
    shprogress_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_shprogress = {"ShProgress", create, set_prop, destroy};