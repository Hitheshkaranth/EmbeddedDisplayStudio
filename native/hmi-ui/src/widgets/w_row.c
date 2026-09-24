// widgets/w_row.c -- kit widget Row (Containers, "Row").
//
// Spec: ui/qml/Shadcn/Row.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): spacing, layoutDirection, opacity, visible.
// Default size 300x80. Signals: none.
#include <string.h>
#include "registry.h"
#include "theme.h"

typedef struct {
    lv_obj_t *obj;
} row_state_t;

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w;
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_style_bg_opa(obj, LV_OPA_TRANSP, 0);

    lv_obj_set_flex_flow(obj, LV_FLEX_FLOW_ROW);
    int spacing = (int)hmi_widget_num(w, "spacing", 8);
    lv_obj_set_style_pad_column(obj, spacing, 0);
    lv_obj_set_style_pad_row(obj, 0, 0);

    row_state_t *st = lv_malloc_zeroed(sizeof *st);
    st->obj = obj;
    w->state = st;
    return obj;
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w;
    row_state_t *st = w->state;
    if (!st) return;
    lv_obj_t *obj = st->obj;

    if (strcmp(prop, "spacing") == 0) {
        lv_obj_set_style_pad_column(obj, (int)hmi_value_as_num(value, 8), 0);
    }
}

static void destroy(hmi_widget_t *w)
{
    row_state_t *st = w->state;
    if (st) lv_free(st);
}

const hmi_widget_ops_t hmi_widget_row = {"Row", create, set_prop, destroy};