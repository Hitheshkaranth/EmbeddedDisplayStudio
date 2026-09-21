// widgets/w_shgearindicator.c -- kit widget ShGearIndicator (Automotive, "Gear Indicator").
//
// Spec: ui/qml/Shadcn/ShGearIndicator.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): gears, gear, modeNumber, showAll, opacity, visible.
// Default size 120x70. Signals: none.
// Owner: W2 (wave 2). Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W2): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W2): live property updates
}

const hmi_widget_ops_t hmi_widget_shgearindicator = {"ShGearIndicator", create, set_prop, NULL};
