// widgets/w_shattitude.c -- kit widget ShAttitude (Avionics, "Attitude Indicator").
//
// Spec: ui/qml/Shadcn/ShAttitude.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): pitch, roll, pixelsPerDegree, opacity, visible.
// Default size 220x220. Signals: none.
// Owner: W1 (wave 2). Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W1): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W1): live property updates
}

const hmi_widget_ops_t hmi_widget_shattitude = {"ShAttitude", create, set_prop, NULL};
