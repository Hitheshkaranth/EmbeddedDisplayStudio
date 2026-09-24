// widgets/w_item.c -- kit widget Item (Navigation, "Page").
//
// Spec: ui/qml/Shadcn/Item.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): clip, opacity, visible.
// Default size 320x240. Signals: none.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *obj;
} item_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w;
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);

    item_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->obj = obj;

    // clip property
    bool clip = hmi_widget_bool(w, "clip", false);
    if (clip)
        lv_obj_add_flag(obj, LV_OBJ_FLAG_CLICKABLE); // enable clip corner logic
    else
        lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);

    w->state = st;
    return obj;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w;
    item_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *obj = st->obj;

    if (strcmp(prop, "clip") == 0) {
        bool clip = hmi_value_as_bool(value, false);
        if (clip)
            lv_obj_add_flag(obj, LV_OBJ_FLAG_CLICKABLE);
        else
            lv_obj_remove_flag(obj, LV_OBJ_FLAG_CLICKABLE);
    }
}

static void destroy(hmi_widget_t *w)
{
    item_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_item = {"Item", create, set_prop, destroy};