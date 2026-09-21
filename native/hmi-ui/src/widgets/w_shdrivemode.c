// widgets/w_shdrivemode.c -- kit widget ShDriveMode (Automotive, "Drive Mode").
//
// Spec: ui/qml/Shadcn/ShDriveMode.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): label, modes, currentIndex, enabled, opacity, visible.
// Default size 180x56. Signals: activated.
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

const hmi_widget_ops_t hmi_widget_shdrivemode = {"ShDriveMode", create, set_prop, NULL};
