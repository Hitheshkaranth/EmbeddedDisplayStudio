// widgets/w_shstatdot.c -- kit widget ShStatDot (Industrial, "Status Indicator").
//
// Spec: ui/qml/Shadcn/ShStatDot.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): state, size, opacity, visible.
// Default size 36x36. Signals: none.
// Owner: W3. Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W3): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W3): live property updates
}

const hmi_widget_ops_t hmi_widget_shstatdot = {"ShStatDot", create, set_prop, NULL};
