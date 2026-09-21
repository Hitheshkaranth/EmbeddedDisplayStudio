// widgets/w_shtoggle.c -- kit widget ShToggle (Industrial, "Toggle").
//
// Spec: ui/qml/Shadcn/ShToggle.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): checked, label, onLabel, offLabel, enabled, opacity, visible.
// Default size 160x40. Signals: toggled.
// Owner: wave 2. Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(wave 2): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(wave 2): live property updates
}

const hmi_widget_ops_t hmi_widget_shtoggle = {"ShToggle", create, set_prop, NULL};
