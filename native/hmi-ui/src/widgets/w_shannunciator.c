// widgets/w_shannunciator.c -- kit widget ShAnnunciator (Avionics, "Annunciator").
//
// Spec: ui/qml/Shadcn/ShAnnunciator.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): text, severity, lit, opacity, visible.
// Default size 140x38. Signals: none.
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

const hmi_widget_ops_t hmi_widget_shannunciator = {"ShAnnunciator", create, set_prop, NULL};
