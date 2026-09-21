// widgets/w_rectangle.c -- kit widget Rectangle (Basic, "Rectangle").
//
// Spec: ui/qml/Shadcn/Rectangle.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): color, borderColor, borderWidth, radius, opacity, visible.
// Default size 140x90. Signals: none.
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

const hmi_widget_ops_t hmi_widget_rectangle = {"Rectangle", create, set_prop, NULL};
