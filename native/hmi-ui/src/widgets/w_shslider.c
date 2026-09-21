// widgets/w_shslider.c -- kit widget ShSlider (Industrial, "Slider").
//
// Spec: ui/qml/Shadcn/ShSlider.qml (the QML component is the drawing and
// behaviour specification). Properties (kit_schema.json): value, minValue, maxValue, step, label, unit, valueWarning, valueFault, enabled, showTicks, tickCount, showValue, handleRadius, opacity, visible.
// Default size 250x64. Signals: valueChanged.
// Owner: W3 (wave 2). Until implemented, create() returns NULL and the runtime
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

const hmi_widget_ops_t hmi_widget_shslider = {"ShSlider", create, set_prop, NULL};
