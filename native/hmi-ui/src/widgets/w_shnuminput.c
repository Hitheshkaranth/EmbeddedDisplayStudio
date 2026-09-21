// widgets/w_shnuminput.c -- kit widget ShNumInput (Industrial, "Numeric Input").
//
// Spec: ui/qml/Shadcn/ShNumInput.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minValue, maxValue, step, unit, label, enabled, decimalPlaces, opacity, visible.
// Default size 240x64. Signals: valueChanged.
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

const hmi_widget_ops_t hmi_widget_shnuminput = {"ShNumInput", create, set_prop, NULL};
