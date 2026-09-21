// widgets/w_shautolevel.c -- kit widget ShAutoLevel (Automotive, "Level Bar").
//
// Spec: ui/qml/Shadcn/ShAutoLevel.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minimumValue, maximumValue, topLabel, midLabel, bottomLabel, redZone, redZoneSpan, icon, curved, showTicks, opacity, visible.
// Default size 90x220. Signals: none.
// Owner: W4. Until implemented, create() returns NULL and the runtime
// draws a labelled placeholder.
#include "registry.h"
#include "theme.h"

static lv_obj_t *create(hmi_widget_t *w, lv_obj_t *parent)
{
    (void)w; (void)parent;
    return NULL;   // TODO(W4): build the LVGL objects
}

static void set_prop(hmi_widget_t *w, const char *prop, const hmi_value_t *value)
{
    (void)w; (void)prop; (void)value;   // TODO(W4): live property updates
}

const hmi_widget_ops_t hmi_widget_shautolevel = {"ShAutoLevel", create, set_prop, NULL};
